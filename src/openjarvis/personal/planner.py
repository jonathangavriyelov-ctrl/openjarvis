"""Turn a chief-of-staff request into specialist tasks.

The deterministic planner is the source of truth used in tests and whenever
no model is reachable. An optional model may propose a plan; unknown
specialist ids are dropped, and an empty proposal falls back here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from openjarvis.personal.specialists import Specialist, list_specialists


@dataclass(slots=True)
class PlannedTask:
    specialist_id: str
    title: str
    brief: str

    def to_dict(self) -> dict[str, str]:
        return {
            "specialist_id": self.specialist_id,
            "title": self.title,
            "brief": self.brief,
        }


_AUDIENCE_HINTS = (
    "audience",
    "public",
    "customers",
    "users",
    "announce",
    "launch",
)

# Counted asks become one task per piece. Five is enough to run in parallel
# without flooding the desk.
MAX_PARALLEL = 5

_COUNT_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

_NOUN_RE = re.compile(
    r"^(?:ideas?|posts?|drafts?|options?|versions?|variants?"
    r"|emails?|messages?|captions?|pieces?)$",
    re.IGNORECASE,
)
# Dates are not counts. "2026-12-01" must not become "12 posts".
_DATE_RE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
)

_CONTENT_NOUNS = frozenset(
    {"idea", "ideas", "post", "posts", "draft", "drafts", "caption", "captions"}
)
_MESSAGE_NOUNS = frozenset({"email", "emails", "message", "messages"})


def _workers() -> list[Specialist]:
    return list_specialists(include_chief=False)


def plan_request(
    request: str,
    specialists: Sequence[Specialist] | None = None,
    *,
    command: Any = None,
) -> list[PlannedTask]:
    """Assign the request to every specialist whose triggers match.

    A ``/sc:`` command routes to the specialists that command names. A request
    that matches nobody still gets a real split: the executive assistant owns
    the next actions, and the second brain captures it. An audience-facing
    general request also includes marketing.
    """
    text = (request or "").strip()
    lowered = text.lower()
    roster = list(specialists) if specialists is not None else _workers()
    if command is not None:
        by_id = {spec.id: spec for spec in roster}
        directed = [
            by_id[spec_id]
            for spec_id in getattr(command, "specialists", ())
            if spec_id in by_id
        ]
        if directed:
            label = getattr(command, "name", "command")
            return [
                PlannedTask(
                    specialist_id=spec.id,
                    title=f"/sc:{label} — {spec.name}",
                    brief=spec.task_brief(text),
                )
                for spec in directed
            ]
    matched = [
        spec
        for spec in roster
        if spec.id != "chief_of_staff"
        and any(trigger in lowered for trigger in spec.triggers)
    ]
    if not matched:
        by_id = {spec.id: spec for spec in roster}
        matched = [
            by_id[spec_id]
            for spec_id in ("executive_assistant", "second_brain")
            if spec_id in by_id
        ]
        if any(hint in lowered for hint in _AUDIENCE_HINTS):
            marketing = by_id.get("marketing_content")
            if marketing and marketing not in matched:
                matched.append(marketing)
        if not matched:
            matched = [spec for spec in roster if spec.id != "chief_of_staff"]
    planned = [
        PlannedTask(
            specialist_id=spec.id,
            title=spec.task_title(text),
            brief=spec.task_brief(text),
        )
        for spec in matched
    ]
    return apply_count_split(text, planned)


def plan_from_model_text(
    raw: str,
    *,
    request: str,
    specialists: Sequence[Specialist] | None = None,
) -> list[PlannedTask] | None:
    """Parse a model's JSON plan. Return None when it is not usable."""
    if not raw or not raw.strip():
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload: Any = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return None
    roster = list(specialists) if specialists is not None else _workers()
    known = {spec.id: spec for spec in roster if spec.id != "chief_of_staff"}
    planned: list[PlannedTask] = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        spec_id = str(item.get("specialist_id") or item.get("specialist") or "")
        spec = known.get(spec_id)
        if spec is None:
            continue
        title = str(item.get("title") or "").strip() or spec.task_title(request)
        brief = str(item.get("brief") or "").strip() or spec.task_brief(request)
        planned.append(PlannedTask(spec_id, title[:160], brief))
    if not planned:
        return None
    return apply_count_split(request, planned)


def _counted_ask(request: str) -> tuple[int, str] | None:
    """Return ``(count, label)`` when the request asks for several pieces.

    The label keeps the words between the number and the piece noun, so
    "3 Instagram post ideas" becomes "Instagram post idea". When both
    "post" and "ideas" sit in that window, the later noun wins.
    """
    scrubbed = _DATE_RE.sub(" ", request or "")
    tokens = re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", scrubbed)
    for index, token in enumerate(tokens):
        low = token.lower()
        if low.isdigit():
            count = int(low)
        elif low in _COUNT_WORDS:
            count = _COUNT_WORDS[low]
        else:
            continue
        if count <= 1 or count > 24:
            continue
        window = tokens[index + 1 : index + 6]
        noun_at = [pos for pos, word in enumerate(window) if _NOUN_RE.match(word)]
        if not noun_at:
            continue
        end = noun_at[-1]
        phrase = window[: end + 1]
        if phrase[-1].lower().endswith("s"):
            phrase[-1] = phrase[-1][:-1]
        label = " ".join(phrase).strip()[:80]
        return min(count, MAX_PARALLEL), label or "piece"
    return None


def _split_target(tasks: Sequence[PlannedTask], noun: str) -> str | None:
    ids: list[str] = []
    for task in tasks:
        if task.specialist_id not in ids:
            ids.append(task.specialist_id)
    if not ids:
        return None
    if noun in _CONTENT_NOUNS and "marketing_content" in ids:
        return "marketing_content"
    if noun in _MESSAGE_NOUNS and "executive_assistant" in ids:
        return "executive_assistant"
    return ids[0]


def apply_count_split(request: str, tasks: list[PlannedTask]) -> list[PlannedTask]:
    """Turn "draft 3 posts" into one task per piece, capped at five.

    A plan that already has that many tasks for the specialist is kept.
    Other specialists stay as a single assignment. ``/sc:`` commands are
    left alone.
    """
    if not tasks:
        return tasks
    if all(task.title.startswith("/sc:") for task in tasks):
        return tasks
    found = _counted_ask(request)
    if found is None:
        return tasks
    count, label = found
    noun = label.split()[-1].lower() if label else ""
    target = _split_target(tasks, noun)
    if target is None:
        return tasks
    existing = [task for task in tasks if task.specialist_id == target]
    others = [task for task in tasks if task.specialist_id != target]
    if len(existing) >= count:
        return existing[:count] + others
    pieces = [
        PlannedTask(
            specialist_id=target,
            title=f"{label} {index} of {count}"[:160],
            brief=(
                f"Write only this piece ({index} of {count}). "
                "Do not draft the other pieces.\n\n"
                f"{request.strip()}"
            ),
        )
        for index in range(1, count + 1)
    ]
    return pieces + others

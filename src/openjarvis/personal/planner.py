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


def _workers() -> list[Specialist]:
    return list_specialists(include_chief=False)


def plan_request(
    request: str,
    specialists: Sequence[Specialist] | None = None,
) -> list[PlannedTask]:
    """Assign the request to every specialist whose triggers match.

    A request that matches nobody still gets a real split: the executive
    assistant owns the next actions, and the second brain captures it. An
    audience-facing general request also includes marketing.
    """
    text = (request or "").strip()
    lowered = text.lower()
    roster = list(specialists) if specialists is not None else _workers()
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
    return [
        PlannedTask(
            specialist_id=spec.id,
            title=spec.task_title(text),
            brief=spec.task_brief(text),
        )
        for spec in matched
    ]


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
    seen: set[str] = set()
    for item in tasks:
        if not isinstance(item, dict):
            continue
        spec_id = str(item.get("specialist_id") or item.get("specialist") or "")
        spec = known.get(spec_id)
        if spec is None or spec_id in seen:
            continue
        seen.add(spec_id)
        title = str(item.get("title") or "").strip() or spec.task_title(request)
        brief = str(item.get("brief") or "").strip() or spec.task_brief(request)
        planned.append(PlannedTask(spec_id, title[:160], brief))
    return planned or None

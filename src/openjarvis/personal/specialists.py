"""Specialist roster for the personal AI OS.

Add another agent by calling :func:`register_specialist`. The chief of staff
delegates only to registered specialists, so a new entry is enough for it to
show up in the eco world, the planner, and the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from openjarvis.personal.goals import (
    assess_goal,
    looks_like_goal,
    pace_label,
    propose_goal,
)
from openjarvis.skills.types import SkillManifest

_REGISTRY: dict[str, "Specialist"] = {}
_BUILTINS: set[str] = set()


@dataclass(slots=True)
class Produced:
    """What a specialist hands back to the chief of staff."""

    title: str
    kind: str
    body: str
    goal: dict[str, Any] | None = None
    note: dict[str, Any] | None = None
    visual_prompt: str = ""
    want_video: bool = False


@dataclass(slots=True)
class ProduceContext:
    """Inputs a specialist can see while it works."""

    request: str
    brief: str
    model_text: str | None = None
    memory_hits: list[str] = field(default_factory=list)
    goals: list[Mapping[str, Any]] = field(default_factory=list)
    eli5: bool = False
    persona_note: str = ""
    world_note: str = ""
    google_briefing: str = ""


Producer = Callable[[ProduceContext], Produced]


@dataclass(slots=True)
class Specialist:
    """One member of Jonathan's agent team."""

    id: str
    name: str
    title: str
    description: str
    niche: str
    accent: str
    skills: tuple[str, ...]
    triggers: tuple[str, ...]
    system_prompt: str
    kind: str
    prefers_hermes: bool = False
    produce: Producer | None = None

    def task_title(self, request: str) -> str:
        del request
        return f"{self.name} — {self.title}"

    def task_brief(self, request: str) -> str:
        return (
            f"You are {self.name}, {self.title}. "
            "The chief of staff assigned you this part of Jonathan's request. "
            f"Do only your job and hand back a finished piece of work.\n\n"
            f"{request.strip()}"
        )

    def skill_manifests(self) -> list[SkillManifest]:
        """Skill manifests that describe this specialist's procedure."""
        return [
            _SKILL_MANIFESTS[name] for name in self.skills if name in _SKILL_MANIFESTS
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "niche": self.niche,
            "accent": self.accent,
            "skills": list(self.skills),
            "prefers_hermes": self.prefers_hermes,
        }


def _learned_lines(ctx: ProduceContext) -> list[str]:
    if ctx.model_text:
        return []
    hits = [str(hit).strip() for hit in ctx.memory_hits if str(hit).strip()]
    if not hits:
        return []
    lines = ["", "## What Jarvis learned"]
    for hit in hits[:3]:
        lines.append(f"- {_clip(hit, 220)}")
    return lines


def _clip(text: str, limit: int = 280) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _goals_block(goals: list[Mapping[str, Any]]) -> str:
    if not goals:
        return "No goals are on the board yet."
    lines = []
    for goal in goals[:6]:
        status = pace_label(assess_goal(goal))
        deadline = goal.get("deadline") or "no deadline"
        lines.append(
            f"- {goal.get('title')} — {int(float(goal.get('progress') or 0))}%, "
            f"{status}, due {deadline}"
        )
    return "\n".join(lines)


def _with_world(body: str, ctx: ProduceContext) -> str:
    note = (ctx.world_note or "").strip()
    if not note or ctx.model_text:
        return body
    return f"{body.rstrip()}\n\n## This world\n{note}"


def _produce_executive(ctx: ProduceContext) -> Produced:
    goal = propose_goal(ctx.request)
    title = "Priorities and pace"
    if goal:
        title = f"Goal on the board: {_clip(goal['title'], 64)}"
    if ctx.model_text:
        body = ctx.model_text.strip()
    elif ctx.eli5:
        parts = [
            "## What to do today",
            "1. Pick one small thing and finish it.",
            "2. Look at your goals. Help the one that is behind.",
            "3. Write down anything new so you do not forget.",
            "",
            "## Your goals",
            _goals_block(list(ctx.goals)),
            "",
            "## A question",
            "What would make tomorrow feel good?",
        ]
        body = "\n".join(parts)
    else:
        parts = [
            "## Today's priorities",
            "1. Name the next concrete step and do it before adding more work.",
            "2. Check the goal board and move the furthest-behind item.",
            "3. Capture anything new in the second brain so it is not only in chat.",
            "",
            "## Goal board",
            _goals_block(list(ctx.goals)),
            "",
            "## Read of this request",
            _clip(ctx.request, 400),
        ]
        if goal:
            due = goal.get("deadline") or "no deadline set"
            parts.extend(
                [
                    "",
                    "## New goal",
                    f"Tracking **{goal['title']}**.",
                    f"Target: {goal['target']}. Deadline: {due}.",
                ]
            )
        parts.extend(
            [
                "",
                "## Check-in",
                "What would make tomorrow morning feel on track?",
            ]
        )
        parts.extend(_learned_lines(ctx))
        body = "\n".join(parts)
    if ctx.google_briefing.strip() and not ctx.model_text:
        body = f"{body.rstrip()}\n\n{ctx.google_briefing.strip()}"
    body = _with_world(body, ctx)
    note = None
    if looks_like_goal(ctx.request) and goal:
        note = {
            "title": f"Goal captured: {_clip(goal['title'], 80)}",
            "body": ctx.request.strip(),
            "tags": "goal,executive-assistant",
        }
    return Produced(title=title, kind="priorities", body=body, goal=goal, note=note)


def _marketing_subject(ctx: ProduceContext) -> str:
    brief = (ctx.brief or "").strip()
    if brief.startswith("Write only this piece"):
        first = brief.split("\n", 1)[0].strip()
        return _clip(first, 90)
    return _clip(ctx.request, 90) or "the work in front of you"


def _produce_marketing(ctx: ProduceContext) -> Produced:
    subject = _marketing_subject(ctx)
    title = f"Content for {_clip(subject, 48)}"
    single_piece = (ctx.brief or "").strip().startswith("Write only this piece")
    video_words = ("video", "clip", "reel", "short film")
    want_video = any(word in ctx.request.lower() for word in video_words)
    if ctx.model_text:
        body = ctx.model_text.strip()
    elif single_piece:
        body = "\n".join(
            [
                "## This piece",
                subject,
                "",
                "Write this one post only. Leave the other pieces for "
                "their own tasks.",
            ]
        )
    elif ctx.eli5:
        body = "\n".join(
            [
                "## Ideas",
                f"1. Say one clear thing about: {subject}",
                "2. Tell a tiny story of what changed.",
                "3. Show one real example.",
                "",
                "## A draft",
                f"Here is a simple post about {subject}.",
                "",
                "## This week",
                "- Monday: share the draft.",
                "- Wednesday: share one example.",
                "- Friday: say what got done.",
            ]
        )
    else:
        body = "\n".join(
            [
                "## Content ideas",
                f"1. A short post that states the point of: {subject}",
                "2. A behind-the-work note: what changed this week and why it matters.",
                "3. One proof point: a number, a before/after, or a user line.",
                "",
                "## Draft",
                f"Working on {subject}. The useful version is specific: one claim, "
                "one piece of evidence, and one next step for the reader.",
                "",
                "## Content calendar",
                "- Monday — publish the draft above.",
                "- Wednesday — one proof point, even if it is small.",
                "- Friday — a recap of what shipped and what is next.",
                "",
                "## Campaign note",
                "Keep one offer and one audience until this request is done. "
                "Add variants only after the first draft exists.",
            ]
        )
    extra = _learned_lines(ctx)
    if extra:
        body = f"{body.rstrip()}\n" + "\n".join(extra)
    body = _with_world(body, ctx)
    return Produced(
        title=title,
        kind="content",
        body=body,
        visual_prompt=subject,
        want_video=want_video,
    )


def _produce_second_brain(ctx: ProduceContext) -> Produced:
    title = f"Note: {_clip(ctx.request, 64)}"
    hits = ctx.memory_hits[:5]
    if ctx.model_text:
        body = ctx.model_text.strip()
    elif ctx.eli5:
        remembered = (
            "\n".join(f"- {_clip(hit, 160)}" for hit in hits)
            if hits
            else "- Nothing saved yet. This is the first note."
        )
        body = "\n".join(
            [
                "## Saved",
                ctx.request.strip(),
                "",
                "## In simple words",
                "I put this in your notes so you can ask about it later.",
                "",
                "## Already saved",
                remembered,
            ]
        )
    else:
        remembered = (
            "\n".join(f"- {_clip(hit, 220)}" for hit in hits)
            if hits
            else "- Nothing related is in memory yet. This note is the start."
        )
        body = "\n".join(
            [
                "## Captured",
                ctx.request.strip(),
                "",
                "## What this is",
                "A note in the second brain, kept so a later question can find it.",
                "",
                "## Related memory",
                remembered,
            ]
        )
    body = _with_world(body, ctx)
    return Produced(
        title=title,
        kind="knowledge",
        body=body,
        note={
            "title": title,
            "body": ctx.request.strip(),
            "tags": "second-brain",
        },
    )


def _produce_generic(ctx: ProduceContext) -> Produced:
    if ctx.model_text:
        body = ctx.model_text.strip()
    else:
        body = "\n".join(
            [
                "## Finished work",
                ctx.brief.strip() or ctx.request.strip(),
            ]
        )
    return Produced(title="Finished work", kind="brief", body=body)


_SKILL_MANIFESTS: dict[str, SkillManifest] = {
    "personal-goal-tracking": SkillManifest(
        name="personal-goal-tracking",
        description=(
            "Read Jonathan's goals, compare progress with the deadline, "
            "and write today's three priorities plus one check-in question."
        ),
        author="openjarvis",
        tags=["personal", "hermes", "goals"],
        markdown_content=(
            "Track the goal, the target, and the deadline. Say whether the "
            "pace is on track, at risk, or behind. End with three priorities."
        ),
    ),
    "personal-daily-check-in": SkillManifest(
        name="personal-daily-check-in",
        description="A short daily review of goals and the next actions.",
        author="openjarvis",
        tags=["personal", "hermes", "check-in"],
    ),
    "personal-content-calendar": SkillManifest(
        name="personal-content-calendar",
        description=(
            "Turn a marketing request into ideas, one draft, and a three-slot "
            "content calendar."
        ),
        author="openjarvis",
        tags=["personal", "marketing"],
    ),
    "personal-knowledge-capture": SkillManifest(
        name="personal-knowledge-capture",
        description=(
            "Store the request as a durable note and answer from notes already "
            "in memory before adding anything new."
        ),
        author="openjarvis",
        tags=["personal", "memory"],
    ),
    "personal-delegation": SkillManifest(
        name="personal-delegation",
        description=(
            "Break a request into specialist tasks, run them, and return each "
            "finished deliverable."
        ),
        author="openjarvis",
        tags=["personal", "chief-of-staff"],
    ),
}


def register_specialist(specialist: Specialist, *, builtin: bool = False) -> Specialist:
    """Add or replace a specialist. Builtins cannot be removed by accident."""
    if not specialist.id or specialist.id != specialist.id.strip():
        raise ValueError("specialist id must be a non-empty slug")
    _REGISTRY[specialist.id] = specialist
    if builtin:
        _BUILTINS.add(specialist.id)
    return specialist


def unregister_specialist(specialist_id: str) -> None:
    """Remove a specialist that was added at runtime."""
    if specialist_id in _BUILTINS:
        raise ValueError(f"{specialist_id} is a built-in specialist")
    _REGISTRY.pop(specialist_id, None)


def get_specialist(specialist_id: str) -> Specialist:
    try:
        return _REGISTRY[specialist_id]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown specialist '{specialist_id}'. Known: {known}") from exc


def list_specialists(*, include_chief: bool = True) -> list[Specialist]:
    specs = list(_REGISTRY.values())
    if not include_chief:
        specs = [spec for spec in specs if spec.id != "chief_of_staff"]
    order = {spec_id: index for index, spec_id in enumerate(_ORDER)}
    specs.sort(key=lambda spec: (order.get(spec.id, 100), spec.name))
    return specs


def render_system_prompt(spec: Specialist, *, extra: str = "") -> str:
    """System prompt plus the skill procedures this specialist is built with."""
    lines = [spec.system_prompt.strip(), "", "Procedures:"]
    manifests = spec.skill_manifests()
    if not manifests:
        lines.append("- Do the assigned brief and return finished work.")
    for manifest in manifests:
        lines.append(f"- {manifest.name}: {manifest.description}")
        if manifest.markdown_content:
            lines.append(f"  {manifest.markdown_content}")
    if extra.strip():
        lines.extend(["", extra.strip()])
    return "\n".join(lines)


def produce_for(spec: Specialist, ctx: ProduceContext) -> Produced:
    producer = spec.produce or _produce_generic
    return producer(ctx)


_ORDER = (
    "chief_of_staff",
    "executive_assistant",
    "marketing_content",
    "second_brain",
)


def _builtin_roster() -> None:
    register_specialist(
        Specialist(
            id="chief_of_staff",
            name="Chief of Staff",
            title="runs the team",
            description=(
                "Takes a goal or request, breaks it into tasks, delegates each "
                "task to a specialist, and brings the finished work back."
            ),
            niche="Heartwood",
            accent="#53d9e9",
            skills=("personal-delegation",),
            triggers=(),
            kind="brief",
            system_prompt=(
                "You are Jonathan's chief of staff. Split the request into "
                "tasks for the specialist ids you are given. Do not do their "
                "work yourself."
            ),
        ),
        builtin=True,
    )
    register_specialist(
        Specialist(
            id="executive_assistant",
            name="Executive Assistant",
            title="keeps Jonathan on his goals",
            description=(
                "Goals, milestones, daily priorities, and check-ins. Prefers a "
                "Nous Research Hermes model when one is available."
            ),
            niche="Ridge",
            accent="#f5c16c",
            skills=("personal-goal-tracking", "personal-daily-check-in"),
            triggers=(
                "goal",
                "milestone",
                "deadline",
                "priority",
                "priorities",
                "schedule",
                "check-in",
                "check in",
                "on track",
                "today",
                "this week",
            ),
            kind="priorities",
            prefers_hermes=True,
            system_prompt=(
                "You are Jonathan's executive assistant, built to run on a "
                "Nous Research Hermes model. Keep him on track toward his "
                "goals. Be concrete: priorities, pace, and the next check-in. "
                "Do not invent meetings or facts that are not in the brief. "
                "You may draft email and calendar proposals. You never send "
                "mail or change the calendar."
            ),
            produce=_produce_executive,
        ),
        builtin=True,
    )
    register_specialist(
        Specialist(
            id="marketing_content",
            name="Marketing & Content",
            title="drafts the public work",
            description=(
                "Content ideas, post drafts, campaigns, and a content calendar."
            ),
            niche="Canopy",
            accent="#7dcea0",
            skills=("personal-content-calendar",),
            triggers=(
                "marketing",
                "content",
                "post",
                "campaign",
                "calendar",
                "draft",
                "social",
                "newsletter",
                "audience",
                "launch",
                "announce",
                "blog",
            ),
            kind="content",
            system_prompt=(
                "You are Jonathan's marketing and content agent. Return "
                "content ideas, one usable draft, and a short content calendar. "
                "Write in his voice: specific, calm, and free of filler."
            ),
            produce=_produce_marketing,
        ),
        builtin=True,
    )
    register_specialist(
        Specialist(
            id="second_brain",
            name="Second Brain",
            title="keeps what Jonathan learns",
            description=(
                "Captures notes, ideas, and knowledge into long-term memory "
                "and answers questions from it."
            ),
            niche="Root library",
            accent="#c4b5fd",
            skills=("personal-knowledge-capture",),
            triggers=(
                "remember",
                "note",
                "idea",
                "knowledge",
                "second brain",
                "capture",
                "recall",
                "what do i know",
                "research",
            ),
            kind="knowledge",
            system_prompt=(
                "You are Jonathan's second brain. Capture the knowledge in the "
                "brief, relate it to memory you were given, and answer only "
                "from that material. If memory is empty, say so."
            ),
            produce=_produce_second_brain,
        ),
        builtin=True,
    )


_builtin_roster()

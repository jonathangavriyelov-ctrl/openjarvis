"""Goal targets, deadlines, and whether Jonathan is on pace."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_GOAL_HINTS = (
    "goal",
    "milestone",
    "deadline",
    "on track",
    "target",
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_when(value: str) -> datetime | None:
    """Parse an ISO date or datetime. Date-only values end that UTC day."""
    text = (value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        year, month, day = (int(part) for part in text.split("-"))
        return datetime(year, month, day, 23, 59, 59, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def parse_deadline(text: str, *, today: date | None = None) -> str | None:
    """Pull a deadline out of a free-text request, if one is stated."""
    found = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text or "")
    if found:
        when = parse_when(found.group(1))
        return when.isoformat() if when else None

    relative = re.search(r"\bin\s+(\d+)\s+days?\b", text or "", re.IGNORECASE)
    if relative:
        start = today or datetime.now(timezone.utc).date()
        day = start + timedelta(days=int(relative.group(1)))
        return datetime(
            day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc
        ).isoformat()

    named = re.search(
        r"\bby\s+([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b",
        text or "",
        re.IGNORECASE,
    )
    if not named:
        return None
    month = _MONTHS.get(named.group(1).lower())
    if month is None:
        return None
    day_num = int(named.group(2))
    year = int(named.group(3) or (today or datetime.now(timezone.utc).date()).year)
    try:
        when = datetime(year, month, day_num, 23, 59, 59, tzinfo=timezone.utc)
    except ValueError:
        return None
    return when.isoformat()


def looks_like_goal(text: str) -> bool:
    """True when a request is asking to track an outcome, not just a task."""
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _GOAL_HINTS)


def propose_goal(text: str, *, today: date | None = None) -> dict[str, Any] | None:
    """Turn a goal-shaped request into a goal record, or return None."""
    raw = " ".join((text or "").split())
    if not raw or raw.lower().startswith("daily check-in"):
        return None
    if not looks_like_goal(raw):
        return None
    title = re.sub(
        r"^(please\s+)?(set\s+)?(a\s+|my\s+)?goal\s*(to|:)?\s*",
        "",
        raw,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" .")
    # Keep the outcome, not the other jobs packed into the same sentence.
    title = re.split(r",|\band\b", title, maxsplit=1)[0].strip(" .")
    title = title[:160] or raw[:160]
    target = "Completed"
    target_match = re.search(r"\btarget\s*:\s*([^.\n]+)", raw, re.IGNORECASE)
    if target_match:
        target = target_match.group(1).strip()[:160]
    return {
        "title": title,
        "target": target,
        "deadline": parse_deadline(raw, today=today),
    }


def default_milestones(title: str) -> list[dict[str, Any]]:
    """Three checkpoints that mark 25, 50, and 100 percent of a goal."""
    short = title[:48]
    return [
        {"title": f"First checkpoint — {short}", "target_progress": 25},
        {"title": f"Midpoint review — {short}", "target_progress": 50},
        {"title": f"Hit the target — {short}", "target_progress": 100},
    ]


def assess_goal(goal: Mapping[str, Any], *, now: datetime | None = None) -> str:
    """Return complete, on_track, at_risk, or behind.

    With a deadline, expected progress is how far the calendar has moved
    between creation and the due date. Jonathan is on track when actual
    progress is within 10 points of that pace, at risk within 25, and behind
    after that. A goal with no deadline stays on track until it is complete.
    """
    progress = float(goal.get("progress") or 0)
    if progress >= 100:
        return "complete"
    deadline = parse_when(str(goal.get("deadline") or ""))
    if deadline is None:
        return "on_track"
    created = parse_when(str(goal.get("created_at") or ""))
    moment = _as_utc(now or datetime.now(timezone.utc))
    if moment >= deadline:
        return "behind"
    if created is None:
        return "on_track"
    total = (deadline - created).total_seconds()
    elapsed = (moment - created).total_seconds()
    if total <= 0:
        return "behind"
    expected = max(0.0, min(100.0, elapsed / total * 100.0))
    if progress + 10 >= expected:
        return "on_track"
    if progress + 25 >= expected:
        return "at_risk"
    return "behind"


def pace_label(status: str) -> str:
    return {
        "complete": "Complete",
        "on_track": "On track",
        "at_risk": "At risk",
        "behind": "Behind",
    }.get(status, status)

"""Send a draft or create an event only after dashboard approval.

Nothing in the specialist path imports this module. The approve route is
the only caller. A token that can only read still keeps the draft: Google's
403 is stored on the proposal and nothing is sent.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from openjarvis.connectors.google_auth import call_with_refresh

_GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_CALENDAR_INSERT = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

READONLY_NOTE = (
    "Approved on the desk. Copy this draft yourself — this Google token "
    "cannot send mail or change the calendar."
)


def fulfill(kind: str, payload: dict[str, Any], credentials_path: str) -> str:
    """Carry out one approved proposal. Raises PermissionError when read-only."""
    if not credentials_path:
        raise PermissionError(READONLY_NOTE)
    if kind == "email":
        _post_json(credentials_path, _GMAIL_SEND, {"raw": _raw_email(payload)})
        return "Sent the email draft."
    if kind == "event":
        _post_json(credentials_path, _CALENDAR_INSERT, _event_body(payload))
        return "Created the calendar event."
    raise ValueError(f"Unknown proposal kind: {kind}")


def _raw_email(payload: dict[str, Any]) -> str:
    lines = []
    to = (payload.get("to") or "").strip()
    if to:
        lines.append(f"To: {to}")
    lines.append(f"Subject: {payload.get('subject') or 'Draft'}")
    lines.append("Content-Type: text/plain; charset=utf-8")
    lines.append("")
    lines.append(payload.get("body") or "")
    raw = "\r\n".join(lines).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _event_body(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") or "Proposal"
    description = payload.get("description") or ""
    start = (payload.get("start") or "").strip()
    end = (payload.get("end") or "").strip()
    if start:
        return {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end or start},
        }
    day = datetime.now(timezone.utc).date()
    return {
        "summary": summary,
        "description": description,
        "start": {"date": day.isoformat()},
        "end": {"date": (day + timedelta(days=1)).isoformat()},
    }


def _post_json(credentials_path: str, url: str, body: dict[str, Any]) -> dict[str, Any]:
    def call(token: str) -> dict[str, Any]:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=30.0,
        )
        if response.status_code == 403:
            raise PermissionError(READONLY_NOTE)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"ok": True}

    try:
        return call_with_refresh(call, credentials_path)
    except PermissionError:
        raise
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status == 403:
            raise PermissionError(READONLY_NOTE) from exc
        raise

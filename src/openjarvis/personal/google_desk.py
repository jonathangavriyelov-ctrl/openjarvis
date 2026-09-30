"""Read-only Gmail, Calendar, and Drive for the personal desk.

The Executive Assistant reads the inbox and upcoming meetings. The Second
Brain reads Drive documents. Sending mail and creating calendar events are
not in this module. Those happen in :mod:`openjarvis.personal.google_actions`
and only after Jonathan approves a draft in the dashboard.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openjarvis.connectors.oauth import load_tokens, save_tokens

logger = logging.getLogger(__name__)

Reader = Callable[[str], dict[str, Any]]

_EMPTY = {"connected": False, "inbox": [], "meetings": [], "files": []}


def drafts_for(request: str) -> list[dict[str, Any]]:
    """Turn a request that asks to email or schedule into pending drafts.

    The wording has to be specific. A daily check-in that mentions a
    schedule does not become a calendar write.
    """
    text = (request or "").strip()
    if not text:
        return []
    drafts: list[dict[str, Any]] = []
    if re.search(
        r"\b(e-?mail|draft (an |a )?email|send (an |a )?(email|e-mail))\b",
        text,
        re.IGNORECASE,
    ):
        who = ""
        named = re.search(r"\be-?mail\s+([A-Z][\w.'-]{1,40})", text)
        if named:
            who = named.group(1)
        title = f"Email draft to {who}" if who else "Email draft"
        drafts.append(
            {
                "kind": "email",
                "title": title,
                "payload": {
                    "to": who,
                    "subject": text[:90],
                    "body": (
                        "Draft only. Jonathan has not approved sending this.\n\n" + text
                    ),
                },
            }
        )
    if re.search(
        r"\b(invite|schedule (a |an )?(meeting|call|event)|calendar event|"
        r"book (a |an )?meeting|put .{1,60} on (my |the )?calendar)\b",
        text,
        re.IGNORECASE,
    ):
        drafts.append(
            {
                "kind": "event",
                "title": "Calendar proposal",
                "payload": {
                    "summary": text[:90],
                    "description": (
                        "Proposal only. Jonathan has not approved this event.\n\n"
                        + text
                    ),
                },
            }
        )
    return drafts


def resolve_google_desk_path(db_path: str, configured: str = "") -> str:
    """Find Google credentials without ever reading them into a response.

    Order: ``GOOGLE_CREDENTIALS_PATH``, an explicit config path, then
    client id / secret / refresh token from the environment written beside
    the personal database (outside the repo), then an existing connector
    file such as ``~/.openjarvis/connectors/google.json``.
    """
    explicit = os.environ.get("GOOGLE_CREDENTIALS_PATH", "").strip()
    if not explicit:
        explicit = (configured or "").strip()
    if explicit:
        return explicit
    materialized = _materialize_env_credentials(db_path)
    if materialized:
        return materialized
    return _existing_connector_file()


def _materialize_env_credentials(db_path: str) -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    refresh = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
    access = os.environ.get("GOOGLE_ACCESS_TOKEN", "").strip()
    if not (client_id and client_secret and refresh) and not access:
        return ""
    if not db_path:
        return ""
    dest = Path(db_path).parent / "google_personal.json"
    payload: dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
    }
    if access:
        payload["access_token"] = access
        payload["token"] = access
    save_tokens(str(dest), payload)
    return str(dest)


def _existing_connector_file() -> str:
    from openjarvis.connectors.oauth import resolve_google_credentials
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    candidate = resolve_google_credentials(
        str(DEFAULT_CONFIG_DIR / "connectors" / "gmail.json")
    )
    tokens = load_tokens(candidate) or {}
    if tokens.get("access_token") or tokens.get("refresh_token") or tokens.get("token"):
        return candidate
    return ""


def _connected_tokens(path: str) -> bool:
    if not path:
        return False
    tokens = load_tokens(path) or {}
    return bool(
        tokens.get("access_token") or tokens.get("refresh_token") or tokens.get("token")
    )


class GoogleDesk:
    """Inbox, calendar, and Drive reads. A test can inject ``reader``."""

    def __init__(
        self, credentials_path: str = "", reader: Reader | None = None
    ) -> None:
        self.credentials_path = credentials_path or ""
        self._reader = reader

    def connected(self) -> bool:
        if self._reader is not None:
            return True
        return _connected_tokens(self.credentials_path)

    def public_status(self) -> dict[str, Any]:
        connected = self.connected()
        detail = (
            "Gmail, Calendar, and Drive are readable."
            if connected
            else "Google is not connected."
        )
        return {
            "connected": connected,
            "gmail": connected,
            "calendar": connected,
            "drive": connected,
            "detail": detail,
        }

    def snapshot(self, query: str = "") -> dict[str, Any]:
        if self._reader is not None:
            raw = self._reader(query) or {}
            return _normalize(raw, connected=True)
        if not self.connected():
            return dict(_EMPTY)
        try:
            return _read_live(self.credentials_path, query)
        except Exception:
            logger.debug("Google read failed", exc_info=True)
            return dict(_EMPTY)

    def briefing_text(self, snap: dict[str, Any] | None = None) -> str:
        data = snap if snap is not None else self.snapshot("")
        if not data.get("connected"):
            return ""
        lines = ["## Inbox"]
        inbox = data.get("inbox") or []
        if not inbox:
            lines.append("- Inbox is clear.")
        for item in inbox[:6]:
            sender = item.get("from") or "Someone"
            subject = item.get("subject") or "(no subject)"
            snippet = item.get("snippet") or ""
            line = f"- {sender}: {subject}"
            if snippet:
                line = f"{line} — {snippet}"
            lines.append(line)
        lines.append("")
        lines.append("## Upcoming meetings")
        meetings = data.get("meetings") or []
        if not meetings:
            lines.append("- No upcoming meetings.")
        for item in meetings[:8]:
            title = item.get("title") or "(no title)"
            when = item.get("when") or ""
            lines.append(f"- {title}" + (f" — {when}" if when else ""))
        return "\n".join(lines)


class ScopedGoogle:
    """Merge several Google accounts that belong to one world."""

    def __init__(self, desks: list[tuple[str, GoogleDesk]]) -> None:
        self._desks = desks
        self.credentials_path = ""
        if len(desks) == 1:
            self.credentials_path = desks[0][1].credentials_path

    def connected(self) -> bool:
        return any(desk.connected() for _email, desk in self._desks)

    def public_status(self) -> dict[str, Any]:
        connected = self.connected()
        return {
            "connected": connected,
            "gmail": connected,
            "calendar": connected,
            "drive": connected,
            "detail": (
                "Gmail, Calendar, and Drive are readable."
                if connected
                else "Google is not connected."
            ),
            "accounts": [email for email, _desk in self._desks],
        }

    def snapshot(self, query: str = "") -> dict[str, Any]:
        inbox: list[dict[str, Any]] = []
        meetings: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        connected = False
        for email, desk in self._desks:
            snap = desk.snapshot(query)
            if snap.get("connected"):
                connected = True
            for item in snap.get("inbox") or []:
                row = dict(item)
                row["account"] = email
                inbox.append(row)
            for item in snap.get("meetings") or []:
                row = dict(item)
                row["account"] = email
                meetings.append(row)
            for item in snap.get("files") or []:
                row = dict(item)
                row["account"] = email
                files.append(row)
        return {
            "connected": connected,
            "inbox": inbox,
            "meetings": meetings,
            "files": files,
        }

    def briefing_text(self, snap: dict[str, Any] | None = None) -> str:
        data = snap if snap is not None else self.snapshot("")
        if not data.get("connected"):
            return ""
        lines = ["## Inbox"]
        inbox = data.get("inbox") or []
        if not inbox:
            lines.append("- Inbox is clear.")
        for item in inbox[:8]:
            account = item.get("account") or ""
            who = item.get("from") or "Someone"
            subject = item.get("subject") or "(no subject)"
            prefix = f"{account}: " if account else ""
            lines.append(f"- {prefix}{who}: {subject}")
        lines.append("")
        lines.append("## Upcoming meetings")
        meetings = data.get("meetings") or []
        if not meetings:
            lines.append("- No upcoming meetings.")
        for item in meetings[:8]:
            account = item.get("account") or ""
            title = item.get("title") or "(no title)"
            prefix = f"{account}: " if account else ""
            lines.append(f"- {prefix}{title}")
        return "\n".join(lines)


def _normalize(raw: dict[str, Any], *, connected: bool) -> dict[str, Any]:
    return {
        "connected": connected,
        "inbox": list(raw.get("inbox") or []),
        "meetings": list(raw.get("meetings") or []),
        "files": list(raw.get("files") or []),
    }


def _drive_query(text: str) -> str:
    words = []
    for word in re.findall(r"[A-Za-z0-9]{4,}", text or ""):
        cleaned = word.replace("'", "")
        if cleaned and cleaned.lower() not in {"this", "that", "with", "from", "your"}:
            words.append(cleaned)
        if len(words) == 3:
            break
    if not words:
        return ""
    return " or ".join(f"name contains '{word}'" for word in words)


def _read_live(credentials_path: str, query: str) -> dict[str, Any]:
    from openjarvis.connectors.gcalendar import _gcal_api_events_list
    from openjarvis.connectors.gdrive import (
        _EXPORT_MIME_MAP,
        _gdrive_api_export,
        _gdrive_api_list_files,
    )
    from openjarvis.connectors.gmail import (
        _extract_header,
        _gmail_api_get_message,
        _gmail_api_list_messages,
    )
    from openjarvis.connectors.google_auth import call_with_refresh

    inbox: list[dict[str, str]] = []
    meetings: list[dict[str, str]] = []
    files: list[dict[str, str]] = []

    def load_inbox(token: str) -> dict[str, Any]:
        listed = _gmail_api_list_messages(token, query="in:inbox newer_than:2d")
        rows = []
        for item in (listed.get("messages") or [])[:5]:
            msg = _gmail_api_get_message(token, item.get("id") or "")
            headers = (msg.get("payload") or {}).get("headers") or []
            rows.append(
                {
                    "from": _extract_header(headers, "From"),
                    "subject": _extract_header(headers, "Subject") or "(no subject)",
                    "snippet": msg.get("snippet") or "",
                }
            )
        return {"rows": rows}

    def load_events(token: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        listed = _gcal_api_events_list(token, "primary", time_min=now)
        rows = []
        for event in (listed.get("items") or [])[:8]:
            start = event.get("start") or {}
            rows.append(
                {
                    "title": event.get("summary") or "(no title)",
                    "when": start.get("dateTime") or start.get("date") or "",
                }
            )
        return {"rows": rows}

    def load_files(token: str) -> dict[str, Any]:
        drive_q = _drive_query(query)
        if not drive_q:
            return {"rows": []}
        listed = _gdrive_api_list_files(token, query=drive_q)
        rows = []
        for item in (listed.get("files") or [])[:3]:
            file_id = item.get("id") or ""
            mime = item.get("mimeType") or ""
            text = ""
            export_as = _EXPORT_MIME_MAP.get(mime)
            if file_id and export_as:
                try:
                    text = _gdrive_api_export(token, file_id, export_as)[:4000]
                except Exception:
                    logger.debug("Drive export failed", exc_info=True)
                    text = ""
            rows.append(
                {
                    "id": file_id,
                    "name": item.get("name") or "Untitled",
                    "text": text,
                    "link": item.get("webViewLink") or "",
                }
            )
        return {"rows": rows}

    try:
        inbox = call_with_refresh(load_inbox, credentials_path)["rows"]
    except Exception:
        logger.debug("Gmail read failed", exc_info=True)
    try:
        meetings = call_with_refresh(load_events, credentials_path)["rows"]
    except Exception:
        logger.debug("Calendar read failed", exc_info=True)
    if query.strip():
        try:
            files = call_with_refresh(load_files, credentials_path)["rows"]
        except Exception:
            logger.debug("Drive read failed", exc_info=True)
    return {
        "connected": True,
        "inbox": inbox,
        "meetings": meetings,
        "files": files,
    }

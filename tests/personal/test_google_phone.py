"""Google reads, approval-gated writes, and the phone allow-list."""

from __future__ import annotations

import json
from types import SimpleNamespace

from openjarvis.personal.google_actions import READONLY_NOTE
from openjarvis.personal.google_desk import (
    GoogleDesk,
    resolve_google_desk_path,
)
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.phone import PhoneGate, resolve_phone_gate, start_phone


class _FakeChannel:
    def __init__(self, token, *, allowed_chat_ids="", parse_mode="", app_token=""):
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids
        self.app_token = app_token
        self.handlers = []
        self.sent = []
        self.connected = False

    def on_message(self, handler):
        self.handlers.append(handler)

    def connect(self):
        self.connected = True

    def send(self, channel, content, **kwargs):
        del kwargs
        self.sent.append((channel, content))
        return True

    def disconnect(self):
        self.connected = False


def _reader(query: str) -> dict:
    del query
    return {
        "inbox": [
            {"from": "Ada", "subject": "Launch", "snippet": "Ship Friday"},
        ],
        "meetings": [{"title": "Standup", "when": "Friday 9:00"}],
        "files": [{"name": "Launch notes", "text": "Price the outcome."}],
    }


def test_unconnected_google_does_not_touch_the_network(monkeypatch):
    def boom(*args, **kwargs):
        del args, kwargs
        raise AssertionError("network")

    monkeypatch.setattr("httpx.get", boom)
    monkeypatch.setattr("httpx.post", boom)
    desk = GoogleDesk("")
    assert desk.public_status()["connected"] is False
    assert desk.briefing_text() == ""
    assert desk.snapshot("pricing")["files"] == []


def test_briefing_and_drive_notes_use_the_reader(tmp_path):
    office = PersonalOffice(tmp_path / "os.db", google=GoogleDesk(reader=_reader))
    detail = office.run_mission("What are today's priorities?")
    assistant = next(
        item
        for item in detail["deliverables"]
        if item["specialist_id"] == "executive_assistant"
    )
    assert "Launch" in assistant["body"]
    assert "Standup" in assistant["body"]
    office.run_mission("remember the launch notes")
    notes = office.store.list_notes()
    assert any("Price the outcome." in note["body"] for note in notes)
    briefing = office.briefing()
    assert briefing["connected"] is True
    assert "token" not in str(briefing["google"])


def test_live_read_uses_the_google_connectors(monkeypatch, tmp_path):
    creds = tmp_path / "google.json"
    creds.write_text(
        json.dumps(
            {
                "access_token": "token-abc",
                "refresh_token": "refresh-abc",
                "client_id": "id",
                "client_secret": "sec",
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def list_messages(token, **kwargs):
        calls.append(("gmail", token, kwargs.get("query")))
        return {"messages": [{"id": "m1"}]}

    def get_message(token, msg_id):
        del token
        calls.append(("get", msg_id))
        return {
            "snippet": "Ship it",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Ada"},
                    {"name": "Subject", "value": "Launch"},
                ]
            },
        }

    def events(token, calendar_id, **kwargs):
        del token, kwargs
        calls.append(("cal", calendar_id))
        return {
            "items": [
                {
                    "summary": "Standup",
                    "start": {"dateTime": "2026-09-26T15:00:00Z"},
                }
            ]
        }

    def files(token, **kwargs):
        del token
        calls.append(("drive", kwargs.get("query")))
        return {
            "files": [
                {
                    "id": "f1",
                    "name": "Notes",
                    "mimeType": "application/vnd.google-apps.document",
                }
            ]
        }

    def export(token, file_id, mime):
        del token, mime
        calls.append(("export", file_id))
        return "Price the outcome."

    monkeypatch.setattr(
        "openjarvis.connectors.gmail._gmail_api_list_messages",
        list_messages,
    )
    monkeypatch.setattr(
        "openjarvis.connectors.gmail._gmail_api_get_message",
        get_message,
    )
    monkeypatch.setattr(
        "openjarvis.connectors.gcalendar._gcal_api_events_list",
        events,
    )
    monkeypatch.setattr(
        "openjarvis.connectors.gdrive._gdrive_api_list_files",
        files,
    )
    monkeypatch.setattr(
        "openjarvis.connectors.gdrive._gdrive_api_export",
        export,
    )
    snap = GoogleDesk(str(creds)).snapshot("pricing notes")
    assert snap["inbox"][0]["subject"] == "Launch"
    assert snap["meetings"][0]["title"] == "Standup"
    assert "Price the outcome" in snap["files"][0]["text"]
    assert calls[0][0] == "gmail"
    assert "pricing" in calls[-2][1]


def test_env_credentials_are_not_in_the_status(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh-secret-value")
    monkeypatch.delenv("GOOGLE_CREDENTIALS_PATH", raising=False)
    path = resolve_google_desk_path(str(tmp_path / "os.db"))
    status = GoogleDesk(path).public_status()
    blob = str(status)
    assert "super-secret-value" not in blob
    assert "refresh-secret-value" not in blob
    assert status["connected"] is True
    assert "refresh-secret-value" in (tmp_path / "google_personal.json").read_text()


def test_email_request_files_a_draft_and_does_not_send(tmp_path, monkeypatch):
    calls = []

    def fulfill(kind, payload, path):
        calls.append((kind, payload, path))
        return "Sent the email draft."

    monkeypatch.setattr("openjarvis.personal.google_actions.fulfill", fulfill)
    office = PersonalOffice(tmp_path / "os.db")
    office.run_mission("Email Sam about the launch notes")
    rows = office.store.list_proposals()
    assert len(rows) == 1
    assert rows[0]["kind"] == "email"
    assert rows[0]["status"] == "pending"
    assert calls == []
    approved = office.approve_proposal(rows[0]["id"])
    assert approved["status"] == "approved"
    assert len(calls) == 1
    assert calls[0][0] == "email"
    office.approve_proposal(rows[0]["id"])
    assert len(calls) == 1


def test_reject_does_not_send(tmp_path, monkeypatch):
    def fulfill(kind, payload, path):
        del kind, payload, path
        raise AssertionError("reject must not send")

    monkeypatch.setattr("openjarvis.personal.google_actions.fulfill", fulfill)
    office = PersonalOffice(tmp_path / "os.db")
    office.run_mission("Schedule a meeting with Ada")
    row = office.store.list_proposals()[0]
    assert row["kind"] == "event"
    rejected = office.reject_proposal(row["id"])
    assert rejected["status"] == "rejected"
    assert office.store.list_proposals()[0]["status"] == "rejected"


def test_readonly_token_keeps_an_approved_draft(tmp_path, monkeypatch):
    def fulfill(kind, payload, path):
        del kind, payload, path
        raise PermissionError(READONLY_NOTE)

    monkeypatch.setattr("openjarvis.personal.google_actions.fulfill", fulfill)
    office = PersonalOffice(tmp_path / "os.db")
    office.run_mission("Email Sam about the launch notes")
    row = office.store.list_proposals()[0]
    approved = office.approve_proposal(row["id"])
    assert approved["status"] == "approved"
    assert "Copy this draft" in approved["detail"]


def test_phone_denies_everyone_until_an_allow_list_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    gate = resolve_phone_gate("")
    assert gate.allows("telegram", "42") is False
    assert gate.reply_for(None, "telegram", "42", "hello") is None
    office = PersonalOffice(tmp_path / "os.db", phone=gate)

    class Boom:
        def __init__(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("must not connect without an allow-list")

    start_phone(office, telegram_token="123:secret-token", telegram_factory=Boom)
    status = office.phone_status()
    assert status["telegram"]["listening"] is False
    assert "secret-token" not in str(status)


def test_env_chat_id_wins_over_config(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("SLACK_ALLOWED_USER_ID", "U1")
    gate = resolve_phone_gate(telegram_chat_id="99", slack_user_id="U9")
    assert gate.telegram_chat_ids == ("42",)
    assert gate.slack_user_ids == ("U1",)
    assert gate.allows("slack", "U9") is False
    assert gate.allows("slack", "") is False


def test_telegram_allow_match_runs_the_mission(tmp_path):
    office = PersonalOffice(
        tmp_path / "os.db",
        phone=PhoneGate(telegram_chat_ids=("42",), slack_user_ids=("U1",)),
    )
    start_phone(
        office,
        telegram_token="tok",
        slack_bot_token="xoxb",
        slack_app_token="xapp",
        telegram_factory=_FakeChannel,
        slack_factory=_FakeChannel,
    )
    telegram = office._phone_channels["telegram"]
    slack = office._phone_channels["slack"]
    telegram.handlers[0](SimpleNamespace(conversation_id="99", content="hello"))
    assert telegram.sent == []
    telegram.handlers[0](
        SimpleNamespace(
            conversation_id="42",
            content="What are today's priorities?",
        )
    )
    assert telegram.sent[0][0] == "42"
    assert "Back from the team" in telegram.sent[0][1]
    slack.handlers[0](
        SimpleNamespace(sender="U2", conversation_id="C1", content="hello")
    )
    assert slack.sent == []
    slack.handlers[0](
        SimpleNamespace(
            sender="U1",
            conversation_id="C1",
            content="What are today's priorities?",
        )
    )
    assert slack.sent[0][0] == "C1"
    assert "Back from the team" in slack.sent[0][1]
    office.close()

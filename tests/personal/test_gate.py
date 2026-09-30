"""The desk stays closed until a scrypt password issues a session."""

from __future__ import annotations

import json
import stat
from unittest.mock import MagicMock

import pytest

from openjarvis.personal.gate import (
    COOKIE_NAME,
    path_requires_session,
    session_valid,
)
from openjarvis.personal.phone import PhoneGate


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj-home"))
    monkeypatch.delenv("OPENJARVIS_PERSONAL_OS", raising=False)
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)


def _app(tmp_path):
    from fastapi import FastAPI

    from openjarvis.personal.gate import OsGateMiddleware
    from openjarvis.personal.office import PersonalOffice
    from openjarvis.personal.routes import mount_personal

    office = PersonalOffice(tmp_path / "os.db")
    app = FastAPI()
    app.state.personal_office = office
    app.add_middleware(OsGateMiddleware)
    mount_personal(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/savings")
    def savings() -> dict[str, bool]:
        return {"ok": True}

    return app, office


def test_hash_file_never_contains_the_password(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    from openjarvis.personal.gate import set_password

    set_password("correct-horse")
    path = tmp_path / "oj-home" / "os_password.json"
    raw = path.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert "correct-horse" not in raw
    assert record["kdf"] == "scrypt"
    assert record["hash"] != "correct-horse"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_wrong_password_then_lockout(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _isolate(monkeypatch, tmp_path)
    app, office = _app(tmp_path)
    client = TestClient(app)
    try:
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200, setup.text
        client.post("/v1/personal/auth/lock")
        for _ in range(4):
            wrong = client.post(
                "/v1/personal/auth/login",
                json={"password": "not-the-password"},
            )
            assert wrong.status_code == 401
        blocked = client.post(
            "/v1/personal/auth/login",
            json={"password": "not-the-password"},
        )
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"]
        still = client.post(
            "/v1/personal/auth/login",
            json={"password": "correct-horse"},
        )
        assert still.status_code == 429
    finally:
        office.close()


def test_session_opens_the_desk_and_lock_closes_it(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _isolate(monkeypatch, tmp_path)
    app, office = _app(tmp_path)
    client = TestClient(app)
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/personal/worlds").status_code == 401
        assert client.get("/v1/personal/auth/status").json()["password_set"] is False
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200
        cookie = setup.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert COOKIE_NAME in cookie
        worlds = client.get("/v1/personal/worlds")
        assert worlds.status_code == 200
        names = {world["name"] for world in worlds.json()["worlds"]}
        assert "Quick Funders" in names
        stored = (tmp_path / "oj-home" / "os_sessions.json").read_text()
        assert client.cookies[COOKIE_NAME] not in stored
        locked = client.post("/v1/personal/auth/lock")
        assert locked.status_code == 200
        assert client.get("/v1/personal/worlds").status_code == 401
        assert client.get("/health").status_code == 200
    finally:
        office.close()


def test_other_data_routes_lock_with_the_desk(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _isolate(monkeypatch, tmp_path)
    app, office = _app(tmp_path)
    client = TestClient(app)
    try:
        assert path_requires_session("/health") is False
        assert path_requires_session("/v1/personal/worlds") is True
        assert path_requires_session("/v1/savings") is False
        assert client.get("/v1/savings").status_code == 200
        client.post("/v1/personal/auth/setup", json={"password": "correct-horse"})
        client.post("/v1/personal/auth/lock")
        assert path_requires_session("/v1/savings") is True
        assert client.get("/v1/savings").status_code == 401
        monkeypatch.setenv("OPENJARVIS_API_KEY", "desk-key")
        opened = client.get(
            "/v1/savings",
            headers={"Authorization": "Bearer desk-key"},
        )
        assert opened.status_code == 200
        personal = client.get(
            "/v1/personal/worlds",
            headers={"Authorization": "Bearer desk-key"},
        )
        assert personal.status_code == 200
    finally:
        office.close()


def test_make_os_locks_data_routes_before_a_password(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENJARVIS_PERSONAL_OS", "1")
    app, office = _app(tmp_path)
    client = TestClient(app)
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/v1/savings").status_code == 401
        assert client.get("/v1/personal/auth/status").status_code == 200
    finally:
        office.close()


def test_reset_password_closes_sessions(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from click.testing import CliRunner
    from fastapi.testclient import TestClient

    from openjarvis.cli.os_cmd import os_group

    _isolate(monkeypatch, tmp_path)
    app, office = _app(tmp_path)
    client = TestClient(app)
    try:
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200
        token = client.cookies[COOKIE_NAME]
        assert session_valid(token)
        result = CliRunner().invoke(
            os_group,
            ["reset-password", "--password", "replacement-1"],
        )
        assert result.exit_code == 0, result.output
        assert "correct-horse" not in result.output
        assert "replacement-1" not in result.output
        assert session_valid(token) is False
        assert client.get("/v1/personal/worlds").status_code == 401
        again = client.post(
            "/v1/personal/auth/login",
            json={"password": "replacement-1"},
        )
        assert again.status_code == 200
        short = CliRunner().invoke(os_group, ["reset-password", "--password", "short"])
        assert short.exit_code != 0
    finally:
        office.close()


def test_phone_replies_in_process_without_a_session():
    office = MagicMock()
    office.teach_from_phone.return_value = None
    office.run_mission.return_value = {"summary": "Shipped the slice."}
    reply = PhoneGate(telegram_chat_ids=("9",)).reply_for(
        office,
        "telegram",
        "9",
        "What are today's priorities?",
    )
    assert reply == "Shipped the slice."
    office.run_mission.assert_called_once()
    denied = PhoneGate(telegram_chat_ids=("9",)).reply_for(
        office,
        "telegram",
        "someone-else",
        "What are today's priorities?",
    )
    assert denied is None

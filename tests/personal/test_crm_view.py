"""The CRM page is a sample board. It does not call a live CRM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjarvis.personal import crm_view
from openjarvis.personal.crm_view import STAGES, crm_connection, crm_snapshot


def test_sample_board_has_the_mca_stages_and_a_next_step():
    board = crm_snapshot("owner")
    assert board["connection"]["mode"] == "sample"
    assert board["connection"]["live_read"] is False
    assert board["stages"] == list(STAGES)
    open_stages = set(STAGES) - {"Declined"}
    for deal in board["deals"]:
        if deal["stage"] in open_stages:
            assert deal["next_action"]
            assert deal["next_action_on"]
    alerts = {item["kind"] for item in board["alerts"]}
    assert "speed_to_lead" in alerts
    assert "do_not_contact" in alerts
    assert board["metrics"]["funded_volume"] == 50000
    assert board["metrics"]["response_minutes"] == 45
    assert any(row["fits"] for row in board["funders"])
    assert board["audit"]
    names = {bot["name"] for bot in board["bots"]}
    assert "QF CRM" in names
    assert "Agent Watch" in names
    assert "Assistant" in names
    assert "do not contact" in board["team_brief"].lower()
    private = json.dumps({"deals": board["deals"], "audit": board["audit"]}).lower()
    assert "ssn" not in private
    assert "social security" not in private
    assert "routing" not in private
    assert "account number" not in private


def test_watcher_hides_phone_and_email():
    board = crm_snapshot("watcher")
    assert board["deals"]
    for deal in board["deals"]:
        assert "phone" not in deal
        assert "email" not in deal
    underwriting = crm_snapshot("underwriting")
    stages = {deal["stage"] for deal in underwriting["deals"]}
    assert "New Lead" not in stages
    assert "Docs" in stages


def test_a_saved_address_is_not_called(monkeypatch):
    monkeypatch.setenv("OPENJARVIS_CRM_READONLY_URL", "https://crm.example.test/read")
    source = Path(crm_view.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "urlopen" not in source
    slot = crm_connection()
    board = crm_snapshot()
    assert slot["live_read"] is False
    assert board["connection"]["read_only_url"] == "https://crm.example.test/read"
    assert board["connection"]["live_read"] is False


def test_crm_route_stays_behind_the_password(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.personal.gate import OsGateMiddleware
    from openjarvis.personal.office import PersonalOffice
    from openjarvis.personal.routes import mount_personal

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj-home"))
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    office = PersonalOffice(tmp_path / "os.db")
    app = FastAPI()
    app.state.personal_office = office
    app.state.engine = None
    app.add_middleware(OsGateMiddleware)
    mount_personal(app)
    client = TestClient(app)
    try:
        denied = client.get("/v1/personal/crm")
        assert denied.status_code == 401
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200, setup.text
        allowed = client.get("/v1/personal/crm")
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        assert body["connection"]["mode"] == "sample"
        assert body["connection"]["live_read"] is False
        wrote = client.post("/v1/personal/crm", json={"business": "Nope"})
        assert wrote.status_code == 405
    finally:
        office.close()

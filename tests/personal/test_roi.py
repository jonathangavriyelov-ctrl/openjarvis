"""Cost, value, budgets, and model tiers for the personal desk."""

from __future__ import annotations

import pytest

from openjarvis.personal.hermes import resolve_executive_model
from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.omniroute import OmniRouteClient
from openjarvis.personal.roi import call_cost, current_month, token_cost


class _Engine:
    def __init__(self, models, reply):
        self.models = list(models)
        self.reply = reply
        self.calls = []

    def health(self):
        return True

    def list_models(self):
        return list(self.models)

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        del messages, temperature, max_tokens, kwargs
        self.calls.append(model)
        return {"content": self.reply}


def _world(office: PersonalOffice, name: str) -> dict:
    return next(item for item in office.store.list_worlds() if item["name"] == name)


def _by_name(report: dict) -> dict:
    return {world["name"]: world for world in report["worlds"]}


def _client(http, **kwargs):
    return OmniRouteClient(
        "http://127.0.0.1:20128/v1",
        "route-secret",
        http=http,
        cache_seconds=0,
        **kwargs,
    )


def _catalog(method, url, payload, header):
    del url, payload, header
    if method == "GET":
        return 200, {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
                {"id": "hermes3"},
                {"id": "NousResearch/Hermes-4"},
            ]
        }
    return 200, {
        "model": "unused",
        "choices": [{"message": {"content": "routed"}}],
    }


def test_price_table_yields_to_a_reported_omniroute_cost():
    prices = {
        "hermes": {"input": 0.4, "output": 0.4},
        "strong": {"input": 5.0, "output": 15.0},
    }
    priced = token_cost(prices, "hermes", 1_000_000, 0)
    assert priced == 0.4
    reported = call_cost(
        prices,
        "hermes",
        model="hermes3",
        input_tokens=1_000_000,
        output_tokens=0,
        reported=1.25,
    )
    assert reported == 1.25
    fallback = call_cost(
        prices,
        "strong",
        model="gpt-4o",
        input_tokens=1_000_000,
        output_tokens=0,
        reported=None,
    )
    assert fallback == 5.0


def test_hermes3_is_preferred_over_hermes4():
    both = resolve_executive_model(
        "hermes4",
        "llama",
        ["NousResearch/Hermes-4", "hermes3:8b", "llama"],
        True,
    )
    assert both.model_id == "hermes3:8b"
    assert "Hermes 4 is not used" in both.detail

    only_four = resolve_executive_model(
        "Nous-Hermes-4",
        "llama",
        ["Nous-Hermes-4", "llama"],
        True,
    )
    assert only_four.model_id == "llama"
    assert only_four.source == "fallback"

    office_models = []

    def http(method, url, payload, header):
        if method == "GET":
            return _catalog(method, url, payload, header)
        del url, header
        office_models.append(payload["model"])
        return 200, {
            "model": payload["model"],
            "choices": [{"message": {"content": "routed"}}],
        }

    client = _client(http)
    assistant = client.choice_for(
        "executive_assistant",
        hermes_model="hermes4",
        prefers_hermes=True,
    )
    chief = client.choice_for("chief_of_staff")
    notes = client.choice_for("second_brain")
    assert assistant.model_id == "hermes3"
    assert "Hermes 4 is not used" in assistant.detail
    assert chief.model_id == "gpt-4o"
    assert notes.model_id == "gpt-4o-mini"
    assert office_models == []


def test_spend_value_and_hours_stay_inside_one_world(tmp_path):
    office = PersonalOffice(tmp_path / "os.db")
    try:
        funders = _world(office, "Quick Funders")
        glatt = _world(office, "Glatt Express")
        gavco = _world(office, "JWJ / Gavco")
        briefs = {
            row["specialist_id"]: row["brief"]
            for row in office.store.team(funders["id"])
        }
        assert "lead follow-up" in briefs["chief_of_staff"]
        assert "pipeline" in briefs["chief_of_staff"]
        assert "Follow up" in briefs["executive_assistant"]
        assert "draft until Jonathan approves" in briefs["marketing_content"]
        jewelry = office.store.team(gavco["id"])
        meat = office.store.team(glatt["id"])
        jewelry_copy = next(
            row["brief"]
            for row in jewelry
            if row["specialist_id"] == "marketing_content"
        )
        meat_copy = next(
            row["brief"] for row in meat if row["specialist_id"] == "marketing_content"
        )
        assert "jewelry" in jewelry_copy
        assert "re-engagement" in jewelry_copy
        assert "kosher" in meat_copy
        assert "draft until Jonathan approves" in meat_copy

        office.run_mission("Remember the funder note", world_id=funders["id"])
        office.roi.add_revenue(
            world_id=funders["id"],
            amount=1200,
            note="Funded deal",
            source="hook",
        )
        priced = office.roi.record_llm(
            world_id=funders["id"],
            specialist_id="executive_assistant",
            model="hermes3",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        reported = office.roi.record_llm(
            world_id=funders["id"],
            specialist_id="chief_of_staff",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=10,
            reported=1.25,
        )
        assert priced == 0.4
        assert reported == 1.25
        office.roi.record_higgsfield(
            world_id=glatt["id"],
            specialist_id="marketing_content",
            kind="image",
        )
        office.roi.save_settings(
            {
                "recurring": [
                    {"name": "Neon", "amount": 19, "world_id": ""},
                    {"name": "Vercel", "amount": 20, "world_id": funders["id"]},
                ]
            }
        )
        report = office.roi.report()
        worlds = _by_name(report)
        assert worlds["Quick Funders"]["revenue"] == 1200
        assert worlds["Glatt Express"]["revenue"] == 0
        assert worlds["Quick Funders"]["hours_saved"] > 0
        assert worlds["Glatt Express"]["hours_saved"] == 0
        assert worlds["Quick Funders"]["llm"] == pytest.approx(1.65)
        assert worlds["Glatt Express"]["llm"] == 0
        assert worlds["Glatt Express"]["higgsfield"] == pytest.approx(0.08)
        assert worlds["Quick Funders"]["higgsfield"] == 0
        assert worlds["Quick Funders"]["recurring"] == 20
        assert worlds["Glatt Express"]["recurring"] == 0
        assert report["overall"]["recurring"] == 39
        assert worlds["Quick Funders"]["paying"] is True
        assert {agent["world_id"] for agent in report["agents"]} >= {funders["id"]}
        assert glatt["id"] in {agent["world_id"] for agent in report["agents"]}
        assert office.store.completed_task_count("2020-01", funders["id"]) == 0
        details = {row["detail"] for row in office.store.spend_rows(current_month())}
        assert "price table" in details
        assert "omniroute" in details
    finally:
        office.close()


def test_eighty_percent_downgrades_and_a_full_cap_blocks(tmp_path):
    posts = []

    def http(method, url, payload, header):
        if "analytics" in url:
            return 200, {"summary": {"totalCost": 3.5}}
        if method == "GET":
            return _catalog(method, url, payload, header)
        del header
        posts.append(payload["model"])
        return 200, {
            "model": payload["model"],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            "choices": [{"message": {"content": "short plan"}}],
        }

    engine = _Engine(["llama"], "from the engine")
    office = PersonalOffice(
        tmp_path / "os.db",
        engine=engine,
        hermes_model="hermes3",
        omniroute=_client(http),
    )
    try:
        funders = _world(office, "Quick Funders")
        office.roi.save_settings(
            {"budgets": {"overall": 100, "worlds": {funders["id"]: 1.0}}}
        )
        office.store.add_spend(
            world_id=funders["id"],
            specialist_id="chief_of_staff",
            kind="llm",
            amount=0.85,
            month=current_month(),
        )
        office.run_mission("Draft a follow-up", world_id=funders["id"])
        assert posts
        assert all("mini" in model for model in posts)
        warned = office.roi.report()
        assert warned["gateway"]["cost"] == 3.5
        assert any(alert["level"] == "downgrade" for alert in warned["alerts"])

        posts.clear()
        tiny = {world["id"]: 0.00001 for world in office.store.list_worlds()}
        office.roi.save_settings({"budgets": {"overall": 0.00001, "worlds": tiny}})
        blocked = office.run_mission("Draft another follow-up", world_id=funders["id"])
        assert posts == []
        assert engine.calls == []
        assert blocked["deliverables"]
        sources = {item["model_source"] for item in blocked["deliverables"]}
        assert sources == {"offline"}
        levels = {alert["level"] for alert in office.roi.report()["alerts"]}
        assert "block" in levels
    finally:
        office.close()


def test_roi_api_revenue_hook_and_settings(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.personal.routes import personal_router

    office = PersonalOffice(tmp_path / "os.db")
    app = FastAPI()
    app.state.personal_office = office
    app.include_router(personal_router)
    client = TestClient(app)
    try:
        funders = _world(office, "Quick Funders")
        loaded = client.get("/v1/personal/roi")
        assert loaded.status_code == 200
        assert loaded.json()["overall"]["budget"] == 80
        assert loaded.json()["overall"]["paying"] is False
        posted = client.post(
            "/v1/personal/roi/revenue",
            json={
                "world_id": funders["id"],
                "amount": 40,
                "source": "hook",
                "note": "lead",
            },
        )
        assert posted.status_code == 200, posted.text
        worlds = _by_name(posted.json())
        assert worlds["Quick Funders"]["revenue"] == 40
        assert worlds["Glatt Express"]["revenue"] == 0
        saved = client.put(
            "/v1/personal/roi/settings",
            json={"recurring": [{"name": "Neon", "amount": 5, "world_id": ""}]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["overall"]["recurring"] == 5
        assert saved.json()["settings"]["recurring"][0]["name"] == "Neon"
    finally:
        office.close()

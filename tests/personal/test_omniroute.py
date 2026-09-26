"""OmniRoute routing for the personal agent team."""

from __future__ import annotations

from openjarvis.personal.office import PersonalOffice
from openjarvis.personal.omniroute import OmniRouteClient, resolve_omniroute


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


def _client(http, **kwargs):
    return OmniRouteClient(
        "http://127.0.0.1:20128/v1",
        "route-secret",
        http=http,
        cache_seconds=0,
        **kwargs,
    )


def test_unconfigured_omniroute_stays_on_the_engine(monkeypatch):
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    base, key, model = resolve_omniroute()
    assert base == ""
    assert key == ""
    assert model == "auto"
    status = OmniRouteClient("").public_status()
    assert status["configured"] is False
    assert status["reachable"] is False
    assert "route-secret" not in str(status)


def test_enabled_without_a_url_uses_the_local_default():
    base, _key, model = resolve_omniroute(enabled=True, model="auto")
    assert base == "http://127.0.0.1:20128/v1"
    assert model == "auto"


def test_chief_uses_omniroute_and_the_assistant_stays_local(tmp_path):
    calls = []

    def http(method, url, payload, header):
        calls.append((method, url, payload, header))
        if method == "GET":
            return 200, {"data": [{"id": "hermes3"}, {"id": "gpt-4o"}]}
        return 200, {
            "model": payload["model"],
            "choices": [{"message": {"content": f"via {payload['model']}"}}],
        }

    gateway = _client(
        http,
        agent_models={"marketing_content": "gpt-4o"},
    )
    engine = _Engine(["hermes3"], "from the engine")
    office = PersonalOffice(
        tmp_path / "os.db",
        engine=engine,
        hermes_model="hermes3",
        omniroute=gateway,
    )
    check = office.run_mission("/sc:pm what is next")
    assistant = check["deliverables"][0]
    assert assistant["model_source"] == "hermes"
    assert assistant["model_id"] == "hermes3"
    assert "from the engine" in assistant["body"]
    assert engine.calls == ["hermes3"]
    chief = office.model_choices()["agents"]["chief_of_staff"]
    assert chief["route"] == "omniroute"
    assert chief["model_id"] == "gpt-4o"

    draft = office.run_mission("Draft a launch post")
    marketing = next(
        item
        for item in draft["deliverables"]
        if item["specialist_id"] == "marketing_content"
    )
    assert marketing["model_id"] == "gpt-4o"
    assert calls[0][3] == "Bearer route-secret"
    status = office.world()["omniroute"]
    assert status["reachable"] is True
    assert "route-secret" not in str(status)
    office.close()


def test_missing_hermes_uses_auto_on_omniroute(tmp_path):
    def http(method, url, payload, header):
        del url, header
        if method == "GET":
            return 200, {"data": [{"id": "gpt-4o"}]}
        return 200, {
            "model": "provider/fallback",
            "choices": [{"message": {"content": "routed"}}],
        }

    office = PersonalOffice(
        tmp_path / "os.db",
        engine=_Engine(["other"], "engine"),
        hermes_model="hermes3",
        omniroute=_client(http),
    )
    choice = office.model_choices()["agents"]["executive_assistant"]
    assert choice["route"] == "engine"
    assert choice["model_id"] == "other"
    chief = office.model_choices()["agents"]["chief_of_staff"]
    assert chief["route"] == "omniroute"
    assert chief["model_id"] == "gpt-4o"
    office.close()


def test_down_gateway_falls_back_to_the_engine(tmp_path):
    def http(method, url, payload, header):
        del method, url, payload, header
        raise ConnectionError("connection refused")

    engine = _Engine(["llama3"], "from the local engine")
    office = PersonalOffice(
        tmp_path / "os.db",
        engine=engine,
        fallback_model="llama3",
        omniroute=_client(http),
    )
    detail = office.run_mission("/sc:pm check the board")
    body = detail["deliverables"][0]["body"]
    assert "from the local engine" in body
    assert detail["deliverables"][0]["model_source"] == "fallback"
    assert engine.calls
    assert office.world()["omniroute"]["reachable"] is False
    office.close()

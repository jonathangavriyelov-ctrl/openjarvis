"""Per-conversation provider choice, fallback, and the credits flag."""

from __future__ import annotations

import pytest

from openjarvis.chat_switch import (
    AttemptFailed,
    attempt_order,
    clear_needs_credits,
    credits_error,
    mark_needs_credits,
    model_for,
    run_attempts,
)
from openjarvis.core.config import load_config
from openjarvis.engine.cloud import _apply_gpt6_effort, estimate_cost
from openjarvis.routing import concrete_model


@pytest.fixture(autouse=True)
def _reset_credits():
    clear_needs_credits()
    yield
    clear_needs_credits()


def test_new_choice_defaults_to_grok_and_known_models():
    assert model_for("") == "grok-4.7"
    assert model_for("claude") == "claude-opus-5-5"
    assert model_for("openai") == "gpt-6-sol"
    assert model_for("local") == "hermes3:8b"
    assert concrete_model("grok") == "grok-4.7"
    assert concrete_model("grok-4.3") == "grok-4.3"
    assert estimate_cost("grok-4.7", 1_000_000, 0) == 3.0
    assert estimate_cost("grok-3", 1_000_000, 0) == 3.0


def test_fallback_order_skips_openai_unless_it_was_chosen(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    assert attempt_order("grok") == ["grok", "claude", "local"]
    assert attempt_order("claude") == ["claude", "grok", "local"]
    assert attempt_order("openai")[0] == "openai"
    assert "openai" not in attempt_order("grok")
    assert attempt_order("grok", private=True) == ["local"]


def test_missing_key_skips_to_the_next_provider(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert attempt_order("grok") == ["claude", "local"]


def test_credits_error_is_classified_and_skipped_later(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    assert credits_error("credit_balance_exhausted") is True
    assert credits_error("insufficient_quota") is True
    assert credits_error("temporary network") is False
    mark_needs_credits("openai")
    order = attempt_order("claude")
    assert "openai" not in order
    # The explicit choice is still tried once, then the chain.
    assert attempt_order("openai")[0] == "openai"


def test_run_attempts_notes_the_model_that_answered_without_the_key(monkeypatch):
    secret = "sk-do-not-leak"
    monkeypatch.setenv("XAI_API_KEY", secret)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    def caller(provider, model):
        del model
        if provider == "grok":
            raise AttemptFailed(f"network {secret}")
        if provider == "claude":
            return "Claude wrote this."
        return "local"

    result = run_attempts("grok", caller)
    assert result["provider"] == "claude"
    assert result["model"] == "claude-opus-5-5"
    assert result["label"] == "Claude"
    assert "Claude answered" in result["note"] or "Claude" in result["note"]
    assert secret not in result["note"]
    assert secret not in result["content"]
    assert result["content"] == "Claude wrote this."


def test_openai_needs_credits_falls_through_without_crashing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def caller(provider, model):
        del model
        if provider == "openai":
            raise RuntimeError("insufficient_quota: credit_balance_exhausted")
        if provider == "grok":
            return "Grok wrote this."
        raise AttemptFailed("down")

    result = run_attempts("openai", caller)
    assert result["ok"] is True
    assert result["provider"] == "grok"
    assert result["needs_credits"] is True
    assert result["note"] == "OpenAI needs credits, so Grok answered."
    assert "sk-openai-test" not in str(result)


def test_gpt6_chat_completions_set_reasoning_effort_none():
    kwargs: dict = {"model": "gpt-6-sol"}
    _apply_gpt6_effort("gpt-6-sol", kwargs)
    assert kwargs["reasoning_effort"] == "none"
    plain: dict = {"model": "gpt-4o"}
    _apply_gpt6_effort("gpt-4o", plain)
    assert "reasoning_effort" not in plain


def test_cloud_default_model_is_grok_when_the_key_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
    load_config.cache_clear()
    cfg = load_config()
    assert cfg.intelligence.default_model == "grok-4.7"

    written = tmp_path / "named.toml"
    written.write_text(
        '[intelligence]\ndefault_model = "qwen3.5:4b"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(written))
    load_config.cache_clear()
    pinned = load_config()
    assert pinned.intelligence.default_model == "qwen3.5:4b"


def test_personal_chat_route_uses_the_fallback(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj-home"))
    monkeypatch.delenv("OPENJARVIS_PERSONAL_OS", raising=False)
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from fastapi import FastAPI

    from openjarvis.personal.gate import OsGateMiddleware
    from openjarvis.personal.office import PersonalOffice
    from openjarvis.personal.routes import mount_personal

    office = PersonalOffice(tmp_path / "os.db")
    app = FastAPI()
    app.state.personal_office = office
    app.state.engine = None

    def caller(provider, model):
        del model
        if provider == "grok":
            raise AttemptFailed("down")
        if provider == "local":
            return "Hermes answered."
        raise AttemptFailed("down")

    app.state.chat_caller = caller
    app.add_middleware(OsGateMiddleware)
    mount_personal(app)
    client = TestClient(app)
    try:
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200, setup.text
        locked = client.post(
            "/v1/personal/chat",
            json={"message": "Hello", "provider": "grok"},
        )
        assert locked.status_code == 200, locked.text
        body = locked.json()
        assert body["provider"] == "local"
        assert "Hermes" in body["note"]
        assert "xai-test" not in str(body)
        openai = client.post(
            "/v1/personal/chat",
            json={"message": "Second opinion", "provider": "openai"},
        )
        # No OpenAI key, so the choice is skipped and local answers.
        assert openai.status_code == 200
        assert openai.json()["provider"] == "local"
    finally:
        office.close()


def test_probe_marks_needs_credits_without_the_body(monkeypatch):
    from openjarvis.personal.providers import probe_provider

    secret = "sk-super-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    class _Response:
        status_code = 429
        text = f"insufficient_quota {secret}"

    def post(*args, **kwargs):
        del args, kwargs
        return _Response()

    monkeypatch.setattr("openjarvis.personal.providers.httpx.post", post)
    result = probe_provider("openai")
    assert result["ok"] is False
    assert result["needs_credits"] is True
    assert result["detail"] == "Needs credits."
    assert secret not in str(result)


class _Engine:
    def __init__(self):
        self.calls = []

    def health(self):
        return True

    def list_models(self):
        return ["hermes3:8b", "qwen3.5:4b"]

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        del messages, temperature, max_tokens, kwargs
        self.calls.append(model)
        if str(model).startswith("grok"):
            raise RuntimeError("network down")
        return {
            "content": f"from {model}",
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            "cost_usd": 0.0,
        }


def test_office_chat_provider_falls_back_and_stays_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from openjarvis.personal.office import PersonalOffice

    engine = _Engine()
    office = PersonalOffice(
        tmp_path / "os.db", engine=engine, hermes_model="hermes3:8b"
    )
    try:
        world = office.store.list_worlds()[0]
        office._turn = {
            "eli5": False,
            "command": None,
            "world_id": world["id"],
            "chat_provider": "grok",
        }
        text = office._generate(
            office._engine_choice("chief_of_staff"),
            "chief_of_staff",
            "Say hello",
        )
        assert text == "from hermes3:8b"
        assert office._turn["answered_by"] == "local"
        assert "Hermes on your Mac" in office._turn["answered_note"]
        assert "xai-secret" not in office._turn["answered_note"]
        before = list(engine.calls)
        office._generate(
            office._engine_choice("executive_assistant"),
            "executive_assistant",
            "Use @claude for this private note",
        )
        later = engine.calls[len(before) :]
        assert all(not str(model).startswith("grok") for model in later)
        office.roi.save_settings({"budgets": {"overall": 0.0001, "worlds": {}}})
        engine.calls.clear()
        office._turn["answered_note"] = ""
        office._generate(
            office._engine_choice("chief_of_staff"),
            "chief_of_staff",
            "Say hello again",
        )
        assert all(not str(model).startswith("grok") for model in engine.calls)
    finally:
        office.close()

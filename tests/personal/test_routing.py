"""Cloud routing, xAI, and provider status. Keys stay in the environment."""

from __future__ import annotations

import sys
import types

from openjarvis.core.config import RoutingConfig, RoutingRule, load_config
from openjarvis.engine.cloud import estimate_cost
from openjarvis.personal.providers import probe_provider, provider_status
from openjarvis.routing import (
    apply_mention,
    engine_is_cloud,
    host_is_remote,
    select_model,
)
from openjarvis.server.cloud_router import get_provider, is_cloud_model


def test_grok_is_an_xai_cloud_model():
    assert get_provider("grok-3") == "xai"
    assert is_cloud_model("grok-3-mini") is True
    assert estimate_cost("grok-3", 1_000_000, 0) == 3.0


def test_xai_client_uses_the_xai_base_url(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "MINIMAX_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_CODEX_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    created = {}

    class _Client:
        def __init__(self, api_key=None, base_url=None):
            created["api_key"] = api_key
            created["base_url"] = base_url

        def close(self):
            return None

    fake = types.ModuleType("openai")
    fake.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", fake)
    from openjarvis.engine.cloud import CloudEngine

    engine = CloudEngine()
    try:
        assert created["base_url"] == "https://api.x.ai/v1"
        assert created["api_key"] == "xai-test-key"
        assert engine.can_serve("grok-3") is True
        assert "grok-3" in engine.list_models()
        assert engine.health() is True
    finally:
        engine.close()


def test_rule_falls_back_to_local_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    decision = select_model(
        RoutingConfig(),
        agent="chief_of_staff",
        tags=["planning"],
        local_model="hermes3:8b",
    )
    assert decision.provider == "local"
    assert decision.model == "hermes3:8b"


def test_rule_uses_claude_when_the_key_is_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    decision = select_model(
        RoutingConfig(),
        agent="chief_of_staff",
        tags=["planning"],
        local_model="hermes3:8b",
    )
    assert decision.model == "claude-sonnet-4-6"
    assert decision.provider == "anthropic"
    assert "sk-ant-test" not in str(decision)


def test_mention_and_explicit_model_win(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    mentioned = select_model(
        RoutingConfig(),
        agent="chief_of_staff",
        tags=["planning"],
        text="Check @grok for the latest",
        local_model="hermes3:8b",
    )
    assert mentioned.model == "grok-3"
    assert mentioned.source == "mention"
    explicit = select_model(
        RoutingConfig(),
        agent="chief_of_staff",
        tags=["planning"],
        explicit_model="gpt-4o",
        local_model="hermes3:8b",
    )
    assert explicit.model == "hermes3:8b"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    explicit = select_model(
        RoutingConfig(),
        agent="chief_of_staff",
        explicit_model="gpt-4o",
        local_model="hermes3:8b",
    )
    assert explicit.model == "gpt-4o"
    assert explicit.source == "explicit"
    assert apply_mention("hermes3:8b", "ask @claude") == "claude-sonnet-4-6"


def test_private_task_stays_local(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    decision = select_model(
        RoutingConfig(private_local_only=True),
        agent="executive_assistant",
        tags=["private"],
        text="Use @claude for this",
        local_model="hermes3:8b",
        private=True,
    )
    assert decision.provider == "local"
    assert decision.model == "hermes3:8b"
    assert decision.private is True


def test_remote_openai_compatible_host_counts_as_cloud():
    assert host_is_remote("http://127.0.0.1:11434") is False
    assert host_is_remote("https://gpu.example.com/v1") is True

    class _Remote:
        is_cloud = False
        _host = "https://gpu.example.com"

    assert engine_is_cloud(_Remote()) is True


def test_keyword_rule_needs_the_provider_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    local = select_model(
        RoutingConfig(),
        agent="marketing_content",
        tags=["writing"],
        text="Draft a launch post",
        local_model="qwen3.5:4b",
    )
    assert local.provider == "local"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cloud = select_model(
        RoutingConfig(),
        agent="marketing_content",
        tags=["writing"],
        text="Draft a launch post",
        local_model="qwen3.5:4b",
    )
    assert cloud.model == "claude-sonnet-4-6"


def test_custom_rule_matches_one_keyword(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    policy = RoutingConfig(
        rules=[
            RoutingRule(
                keywords=["invoice"],
                model="gpt-4o",
                fallback="hermes3:8b",
            )
        ]
    )
    decision = select_model(policy, text="Send the invoice", local_model="hermes3:8b")
    assert decision.model == "gpt-4o"


class _Engine:
    def __init__(self, models):
        self.models = list(models)
        self.calls = []

    def health(self):
        return True

    def list_models(self):
        return list(self.models)

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        del messages, temperature, max_tokens, kwargs
        self.calls.append(model)
        return {
            "content": f"from {model}",
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "cost_usd": 0.01,
        }


def test_specialist_model_uses_the_engine_without_omniroute(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    from openjarvis.personal.office import PersonalOffice

    engine = _Engine(["hermes3:8b"])
    office = PersonalOffice(
        tmp_path / "os.db",
        engine=engine,
        specialist_models={"chief_of_staff": "claude-sonnet-4-6"},
    )
    try:
        choice = office.model_choices()["agents"]["chief_of_staff"]
        assert choice["model_id"] == "claude-sonnet-4-6"
        assert choice["route"] == "engine"
        assert choice["source"] == "cloud"
    finally:
        office.close()


def test_world_override_uses_the_engine_when_omniroute_is_down(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    from openjarvis.personal.office import PersonalOffice

    office = PersonalOffice(tmp_path / "os.db", engine=_Engine(["hermes3:8b"]))
    try:
        world = office.store.list_worlds()[0]
        office.store.update_team(
            world["id"],
            "marketing_content",
            omniroute_model="gpt-4o",
        )
        choice = office.model_choices()
        # model_choices() is not world-scoped; the roster is.
        row = next(
            agent
            for agent in office.roster(world["id"])
            if agent["id"] == "marketing_content"
        )
        assert row["model"]["model_id"] == "gpt-4o"
        assert row["model"]["route"] == "engine"
        del choice
    finally:
        office.close()


def test_private_assistant_ignores_a_cloud_mention(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from openjarvis.personal.office import PersonalOffice

    engine = _Engine(["hermes3:8b"])
    office = PersonalOffice(
        tmp_path / "os.db", engine=engine, hermes_model="hermes3:8b"
    )
    try:
        detail = office.run_mission("Use @claude for today's priorities")
        assistant = next(
            item
            for item in detail["deliverables"]
            if item["specialist_id"] == "executive_assistant"
        )
        assert assistant["model_id"] == "hermes3:8b"
        assert "claude" not in assistant["model_id"]
    finally:
        office.close()


def test_cloud_call_is_added_to_the_roi_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from openjarvis.personal.office import PersonalOffice

    engine = _Engine(["hermes3:8b"])
    office = PersonalOffice(
        tmp_path / "os.db",
        engine=engine,
        specialist_models={"marketing_content": "claude-sonnet-4-6"},
    )
    try:
        detail = office.run_mission("Draft a launch post")
        marketing = next(
            item
            for item in detail["deliverables"]
            if item["specialist_id"] == "marketing_content"
        )
        assert marketing["model_id"] == "claude-sonnet-4-6"
        task = next(
            row
            for row in detail["tasks"]
            if row["specialist_id"] == "marketing_content"
        )
        assert task["model_id"] == "claude-sonnet-4-6"
        spend = office.store.spend_rows(office.roi.report()["month"])
        assert spend
        assert spend[0]["model"] == "claude-sonnet-4-6"
        assert spend[0]["amount"] > 0
    finally:
        office.close()


def test_provider_status_never_includes_the_key(monkeypatch):
    secret = "sk-super-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    rows = {row["id"]: row for row in provider_status()}
    assert rows["openai"]["connected"] is True
    assert rows["anthropic"]["connected"] is False
    assert rows["xai"]["connected"] is False
    assert secret not in str(rows)


def test_provider_probe_redacts_the_key(monkeypatch):
    secret = "sk-super-secret-value"
    monkeypatch.setenv("XAI_API_KEY", secret)

    def boom(*args, **kwargs):
        del args, kwargs
        raise RuntimeError(f"rejected {secret}")

    monkeypatch.setattr("openjarvis.personal.providers.httpx.post", boom)
    result = probe_provider("xai")
    assert result["ok"] is False
    assert secret not in result["detail"]
    assert "[redacted]" in result["detail"]


def test_personal_os_disables_nim_unless_config_says_otherwise(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_PERSONAL_OS", "1")
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
    cfg = load_config()
    assert "nim" in cfg.engine.disabled

    written = tmp_path / "enabled.toml"
    written.write_text("[engine]\ndisabled = []\n", encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(written))
    load_config.cache_clear()
    opted = load_config()
    assert opted.engine.disabled == []


def test_discovery_skips_a_disabled_engine():
    from openjarvis.core.config import JarvisConfig
    from openjarvis.engine._discovery import discover_engines

    cfg = JarvisConfig()
    cfg.engine.disabled = ["nim"]
    names = [name for name, _engine in discover_engines(cfg)]
    assert "nim" not in names


def test_routing_section_loads_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENJARVIS_PERSONAL_OS", raising=False)
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "home"))
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "[routing]",
                'default = "qwen3.5:4b"',
                "private_local_only = false",
                "",
                "[[routing.rules]]",
                'agent = "chief_of_staff"',
                'model = "grok-3"',
                'fallback = "hermes3:8b"',
                "",
                "[personal.models]",
                'marketing_content = "gpt-4o"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(path))
    cfg = load_config()
    assert cfg.routing.default == "qwen3.5:4b"
    assert cfg.routing.private_local_only is False
    assert cfg.routing.rules[0].model == "grok-3"
    assert cfg.personal.models["marketing_content"] == "gpt-4o"


def test_chat_mention_helper_leaves_an_explicit_model_without_a_mention():
    assert apply_mention("hermes3:8b", "hello") == "hermes3:8b"

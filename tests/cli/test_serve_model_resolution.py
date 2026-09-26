"""Tests for API server model selection."""

from __future__ import annotations

from openjarvis.cli.serve import _resolve_server_model
from openjarvis.core.config import JarvisConfig


class _FakeEngine:
    def __init__(self, models: list[str]) -> None:
        self._models = models

    def list_models(self) -> list[str]:
        return self._models


def test_server_model_falls_back_to_reachable_ollama_model() -> None:
    cfg = JarvisConfig()
    cfg.server.model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    cfg.intelligence.default_model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    cfg.intelligence.fallback_model = "qwen3.5:9b"

    model = _resolve_server_model(
        None,
        config=cfg,
        engine_name="multi",
        engine=_FakeEngine(["qwen3.5:9b"]),
        all_models={"multi": ["qwen3.5:9b"]},
    )

    assert model == "qwen3.5:9b"


def test_server_model_prefers_reachable_configured_model() -> None:
    cfg = JarvisConfig()
    cfg.server.model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    cfg.intelligence.default_model = "qwen3.5:9b"
    cfg.intelligence.fallback_model = "qwen3.5:9b"

    model = _resolve_server_model(
        None,
        config=cfg,
        engine_name="multi",
        engine=_FakeEngine(["mlx-community/Qwen2.5-7B-Instruct-4bit", "qwen3.5:9b"]),
        all_models={"multi": ["mlx-community/Qwen2.5-7B-Instruct-4bit"]},
    )

    assert model == "mlx-community/Qwen2.5-7B-Instruct-4bit"


def test_server_model_matches_tagged_ollama_family() -> None:
    cfg = JarvisConfig()
    cfg.server.model = "hermes3"
    cfg.intelligence.default_model = ""
    cfg.intelligence.fallback_model = ""

    tagged = _resolve_server_model(
        None,
        config=cfg,
        engine_name="ollama",
        engine=_FakeEngine(["hermes3:8b"]),
        all_models={"ollama": ["hermes3:8b"]},
    )
    hyphen = _resolve_server_model(
        None,
        config=cfg,
        engine_name="ollama",
        engine=_FakeEngine(["hermes3-8b"]),
        all_models={},
    )

    assert tagged == "hermes3:8b"
    assert hyphen == "hermes3-8b"


def test_server_model_does_not_merge_dotted_or_registry_ids() -> None:
    cfg = JarvisConfig()
    cfg.server.model = "qwen3"
    cfg.intelligence.default_model = ""
    cfg.intelligence.fallback_model = "qwen3.5:4b"

    dotted = _resolve_server_model(
        None,
        config=cfg,
        engine_name="ollama",
        engine=_FakeEngine(["qwen3.5:4b", "qwen3:8b"]),
        all_models={},
    )
    assert dotted == "qwen3:8b"

    cfg.server.model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    cfg.intelligence.default_model = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    cfg.intelligence.fallback_model = "qwen3.5:9b"
    other_quant = _resolve_server_model(
        None,
        config=cfg,
        engine_name="multi",
        engine=_FakeEngine(
            ["mlx-community/Qwen2.5-7B-Instruct-8bit", "qwen3.5:9b"]
        ),
        all_models={},
    )
    assert other_quant == "qwen3.5:9b"


def test_server_model_keeps_explicit_cli_model() -> None:
    cfg = JarvisConfig()
    cfg.server.model = "configured-model"
    cfg.intelligence.fallback_model = "fallback-model"

    model = _resolve_server_model(
        "explicit-model",
        config=cfg,
        engine_name="multi",
        engine=_FakeEngine(["fallback-model"]),
        all_models={"multi": ["fallback-model"]},
    )

    assert model == "explicit-model"

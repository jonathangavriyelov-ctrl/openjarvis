"""Resolve a Nous Research Hermes model on an existing OpenJarvis engine.

Hermes 3 and the older Nous-Hermes family are ordinary chat models. OpenJarvis
already runs them anywhere it runs Ollama or an OpenAI-compatible server
(Ollama's ``/v1`` endpoint, llama.cpp, vLLM). This module only chooses which
model id the Executive Assistant should call.

The default on a laptop is Ollama's ``hermes3:8b``. If that tag is not
installed, the resolver uses another listed Hermes model, then a local
fallback such as ``qwen3.5:4b``, then whatever else the engine lists.

A configured Hermes 4 id is rewritten to Hermes 3, because Hermes 4 is not
used for tool-calling loops. When no model is reachable, the Executive
Assistant uses its offline structured producer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# A trailing size tag such as ``8b``. Dots stay in the family name, so
# ``qwen3`` does not match ``qwen3.5``.
_SIZE_TAG = re.compile(r"^\d+(?:\.\d+)?b$")

# Sized for a 16 GB Apple Silicon Mac running Ollama.
DEFAULT_HERMES_MODEL = "hermes3:8b"
DEFAULT_LOCAL_MODEL = "qwen3.5:4b"


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """Which model a specialist should call, and why."""

    model_id: str
    source: str  # "hermes", "fallback", "offline", or "omniroute"
    detail: str
    route: str = "engine"  # "engine", "omniroute", or "offline"

    def to_dict(self) -> dict:
        route = self.route
        if self.source == "offline":
            route = "offline"
        return {
            "model_id": self.model_id,
            "source": self.source,
            "detail": self.detail,
            "route": route,
        }


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _is_hermes4(name: str) -> bool:
    compact = _norm(name).replace("_", "").replace("-", "")
    return "hermes4" in compact


def _is_hermes3(name: str) -> bool:
    compact = _norm(name).replace("_", "").replace("-", "")
    return "hermes3" in compact


def _family_key(name: str) -> str:
    """Model family, ignoring an Ollama tag or a short ``-8b`` suffix.

    Registry paths stay intact, so two different Hugging Face ids do not
    collapse into one family. ``hermes3``, ``hermes3:8b``, and ``hermes3-8b``
    share a key. ``qwen3`` and ``qwen3.5:4b`` do not.
    """
    text = _norm(name)
    if not text:
        return ""
    if "/" in text:
        return text.split(":", 1)[0]
    text = text.split(":", 1)[0]
    if "-" in text:
        base, suffix = text.rsplit("-", 1)
        if base and _SIZE_TAG.fullmatch(suffix):
            return base
    return text


def listed_variant(wanted: str, names: Sequence[str]) -> str | None:
    """Return the listed id for *wanted*, including a tagged family variant.

    Exact ids win. Otherwise the first listed name in the same family is
    used, so a config value of ``hermes3`` selects Ollama's ``hermes3:8b``.
    """
    target = _norm(wanted)
    if not target:
        return None
    cleaned = [name for name in names if name and str(name).strip()]
    for name in cleaned:
        if _norm(name) == target:
            return name
    key = _family_key(wanted)
    if not key:
        return None
    for name in cleaned:
        if _family_key(name) == key:
            return name
    return None


def _matches(name: str, wanted: str) -> bool:
    """True when *name* is the wanted id or a tagged variant of that family."""
    if not _norm(name) or not _norm(wanted):
        return False
    if _norm(name) == _norm(wanted):
        return True
    key = _family_key(wanted)
    return bool(key) and _family_key(name) == key


def resolve_executive_model(
    configured_hermes: str,
    fallback: str,
    available: Sequence[str] | None,
    engine_ok: bool,
) -> ModelChoice:
    """Pick the Executive Assistant model.

    Parameters
    ----------
    configured_hermes:
        Preferred Hermes model id (default ``hermes3:8b``).
    fallback:
        Model id to use when no Hermes weights are on the engine. Empty means
        prefer ``qwen3.5:4b``, then any other listed model.
    available:
        Model ids reported by ``engine.list_models()``. ``None`` means the
        engine could not be asked.
    engine_ok:
        False when there is no engine or its health check failed.
    """
    if not engine_ok:
        return ModelChoice(
            "",
            "offline",
            "No inference engine is reachable. The Executive Assistant is "
            "using its local structured producer until a model is available.",
        )

    names = [name for name in (available or []) if name]
    wanted = (configured_hermes or "").strip()
    refused_hermes4 = _is_hermes4(wanted)
    if refused_hermes4:
        wanted = "hermes3"

    if wanted:
        for name in names:
            if (
                _matches(name, wanted)
                and "hermes" in _norm(name)
                and not _is_hermes4(name)
            ):
                detail = f"Using the configured Hermes model {name}."
                if refused_hermes4:
                    detail = (
                        f"Using Hermes 3 ({name}). "
                        "Hermes 4 is not used for tool-calling loops."
                    )
                return ModelChoice(name, "hermes", detail)
        for name in names:
            if _matches(name, wanted) and not _is_hermes4(name):
                return ModelChoice(
                    name,
                    "hermes",
                    f"Using the configured Hermes model {name}.",
                )

    hermes_named = [
        name for name in names if "hermes" in _norm(name) and not _is_hermes4(name)
    ]
    hermes3 = [name for name in hermes_named if _is_hermes3(name)]
    pool = hermes3 or hermes_named
    if pool:
        chosen = pool[0]
        detail = f"Using Hermes model {chosen} reported by the engine."
        if _is_hermes3(chosen):
            detail = (
                f"Using Hermes 3 ({chosen}). "
                "Hermes 4 is not used for tool-calling loops."
            )
        elif wanted and not any(_matches(name, wanted) for name in names):
            detail = (
                f"{wanted} is not installed. Using Hermes model {chosen} "
                "already available on the engine."
            )
        return ModelChoice(chosen, "hermes", detail)

    fallback_id = (fallback or "").strip() or DEFAULT_LOCAL_MODEL
    if fallback_id:
        for name in names:
            if _matches(name, fallback_id) and not _is_hermes4(name):
                return ModelChoice(
                    name,
                    "fallback",
                    "Hermes is not installed on this engine. Using the "
                    f"local model {name}.",
                )
        if not names:
            return ModelChoice(
                fallback_id,
                "fallback",
                "The engine did not list models. Trying the local "
                f"model {fallback_id}.",
            )
    for name in names:
        if not _is_hermes4(name):
            return ModelChoice(
                name,
                "fallback",
                "Hermes is not installed. Using the local model "
                f"{name} already on the engine.",
            )

    if names:
        return ModelChoice(
            names[0],
            "fallback",
            "Hermes is not installed. Using the first model the engine "
            f"reported ({names[0]}).",
        )

    if fallback_id:
        return ModelChoice(
            fallback_id,
            "fallback",
            f"Using the configured model {fallback_id}.",
        )

    return ModelChoice(
        "",
        "offline",
        "The engine has no models loaded. The Executive Assistant is using "
        "its local structured producer.",
    )


def resolve_configured_model(
    configured: str,
    available: Sequence[str] | None,
    engine_ok: bool,
) -> ModelChoice:
    """Pick a non-Hermes specialist model from the server configuration."""
    if not engine_ok:
        return ModelChoice(
            "",
            "offline",
            "No inference engine is reachable. This specialist is using its "
            "local structured producer.",
        )
    names = [name for name in (available or []) if name]
    wanted = (configured or "").strip()
    if wanted:
        for name in names:
            if _matches(name, wanted):
                return ModelChoice(
                    name,
                    "fallback",
                    f"Using the configured model {name}.",
                )
        if not names:
            return ModelChoice(
                wanted,
                "fallback",
                f"Trying the configured model {wanted}.",
            )
    if names:
        return ModelChoice(
            names[0],
            "fallback",
            f"Using model {names[0]} reported by the engine.",
        )
    return ModelChoice(
        "",
        "offline",
        "No model is configured. This specialist is using its local "
        "structured producer.",
    )

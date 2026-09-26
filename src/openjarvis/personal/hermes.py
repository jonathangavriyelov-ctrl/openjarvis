"""Resolve a Nous Research Hermes model on an existing OpenJarvis engine.

Hermes 3 and the older Nous-Hermes family are ordinary chat models. OpenJarvis
already runs them anywhere it runs Ollama or an OpenAI-compatible server
(Ollama's ``/v1`` endpoint, llama.cpp, vLLM). This module only chooses which
model id the Executive Assistant should call.

Common ids that those engines accept when the weights are installed:

* ``hermes3``, ``hermes3:8b``, ``hermes3:70b`` (Ollama library, Hermes 3)
* ``nous-hermes2`` and other tags whose name contains ``hermes``

The configured Hermes id wins when the engine actually lists it. A configured
Hermes 4 id is rewritten to Hermes 3, because Hermes 4 is not used for
tool-calling loops. Otherwise the resolver picks another listed Hermes model,
then the configured fallback model, then the offline structured producer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


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


def _matches(name: str, wanted: str) -> bool:
    """True when *name* is the wanted id, tag, or a tagged variant of it."""
    left = _norm(name)
    right = _norm(wanted)
    if not left or not right:
        return False
    if left == right:
        return True
    return left.split(":", 1)[0] == right or right.split(":", 1)[0] == left


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
        Preferred Hermes model id (default ``hermes3``).
    fallback:
        Model id to use when no Hermes weights are on the engine. Empty means
        "whatever the server was started with", passed in by the caller.
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

    fallback_id = (fallback or "").strip()
    if fallback_id:
        for name in names:
            if _matches(name, fallback_id):
                return ModelChoice(
                    name,
                    "fallback",
                    "Hermes is not installed on this engine. Using the "
                    f"configured model {name}.",
                )
        if not names:
            return ModelChoice(
                fallback_id,
                "fallback",
                "The engine did not list models. Trying the configured "
                f"model {fallback_id}.",
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

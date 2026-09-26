"""Pick a model from routing rules, @mentions, and which keys exist.

API keys are read from the environment only. This module never logs them
and never writes them to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from openjarvis.core.config import RoutingConfig, RoutingRule

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}

_MENTIONS = (
    ("@claude", "claude-sonnet-4-6"),
    ("@grok", "grok-3"),
    ("@gpt", "gpt-4o"),
    ("@local", "hermes3:8b"),
)

_PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "xai": "XAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """The model to call, and why."""

    model: str
    source: str
    provider: str
    private: bool = False


def concrete_model(model: str) -> str:
    """Turn a family such as ``grok-*`` into one callable model id."""
    text = (model or "").strip()
    if text in {"grok-*", "grok"}:
        return "grok-3"
    return text


def provider_of(model: str) -> str:
    """Return the cloud provider, or ``local`` for an on-device model."""
    from openjarvis.server.cloud_router import get_provider

    name = concrete_model(model)
    if not name:
        return "local"
    provider = get_provider(name)
    return provider or "local"


def provider_ready(provider: str) -> bool:
    """True when that provider can be called. Local is always ready."""
    if provider in {"", "local"}:
        return True
    env_name = _PROVIDER_KEYS.get(provider, "")
    if not env_name:
        return False
    return bool(os.environ.get(env_name))


def host_is_remote(host: str) -> bool:
    """True when an OpenAI-compatible host is not this machine."""
    text = (host or "").strip()
    if not text:
        return False
    parsed = urlparse(text if "://" in text else f"http://{text}")
    name = (parsed.hostname or "").lower().rstrip(".")
    return name not in _LOCAL_HOSTS


def engine_is_cloud(engine: Any) -> bool:
    """Cloud engines, and OpenAI-compatible engines aimed at a remote host."""
    if engine is None:
        return False
    if bool(getattr(engine, "is_cloud", False)):
        return True
    host = getattr(engine, "_host", None) or getattr(engine, "host", None) or ""
    return host_is_remote(str(host))


def mention_model(text: str) -> str:
    """The model named by @claude, @grok, @gpt, or @local, if present."""
    lowered = (text or "").lower()
    for token, model in _MENTIONS:
        if token in lowered:
            return model
    return ""


def _rule_tags(rule: RoutingRule) -> set[str]:
    tags = {tag.strip().lower() for tag in rule.tags if tag and tag.strip()}
    if rule.tag.strip():
        tags.add(rule.tag.strip().lower())
    return tags


def rule_matches(
    rule: RoutingRule,
    *,
    agent: str,
    tags: set[str],
    text: str,
) -> bool:
    """True when every constraint the rule sets is satisfied."""
    if not rule.model.strip():
        return False
    constrained = False
    if rule.agent.strip():
        constrained = True
        if rule.agent.strip() != agent:
            return False
    wanted = _rule_tags(rule)
    if wanted:
        constrained = True
        if not wanted & tags:
            return False
    words = [word.strip().lower() for word in rule.keywords if word.strip()]
    if words:
        constrained = True
        haystack = text.lower()
        if not any(word in haystack for word in words):
            return False
    return constrained


def _usable(model: str) -> str:
    """Return the model when its provider key exists, else an empty string."""
    chosen = concrete_model(model)
    provider = provider_of(chosen)
    if provider != "local" and not provider_ready(provider):
        return ""
    return chosen


def select_model(
    routing: RoutingConfig | None,
    *,
    agent: str = "",
    tags: list[str] | None = None,
    text: str = "",
    explicit_model: str = "",
    pinned_model: str = "",
    local_model: str = "",
    private: bool = False,
) -> RouteDecision:
    """Resolve one model.

    A private task stays on a local model when ``private_local_only`` is set.
    Otherwise an @mention wins, then an explicit model, then a pinned
    specialist or world model, then the first matching rule.
    """
    policy = routing or RoutingConfig()
    tag_set = {tag.strip().lower() for tag in (tags or []) if tag and tag.strip()}
    local = concrete_model(local_model or policy.default or "hermes3:8b")
    locked = bool(policy.private_local_only and private)
    if locked:
        return RouteDecision(local, "private", "local", private=True)

    mentioned = mention_model(text)
    if mentioned:
        chosen = _usable(mentioned)
        if chosen:
            return RouteDecision(chosen, "mention", provider_of(chosen))
        return RouteDecision(local, "local", "local")

    if explicit_model.strip():
        chosen = _usable(explicit_model)
        if chosen:
            return RouteDecision(chosen, "explicit", provider_of(chosen))
        return RouteDecision(local, "local", "local")

    if pinned_model.strip():
        chosen = _usable(pinned_model)
        if chosen:
            return RouteDecision(chosen, "pinned", provider_of(chosen))
        return RouteDecision(local, "local", "local")

    for rule in policy.rules:
        if not rule_matches(rule, agent=agent, tags=tag_set, text=text):
            continue
        chosen = _usable(rule.model)
        if chosen:
            return RouteDecision(chosen, "rule", provider_of(chosen))
        fallback = concrete_model(rule.fallback) or local
        if provider_of(fallback) == "local":
            return RouteDecision(fallback, "local", "local")
        return RouteDecision(local, "local", "local")

    chosen = _usable(policy.default or local)
    if chosen:
        return RouteDecision(chosen, "default", provider_of(chosen))
    return RouteDecision("hermes3:8b", "local", "local")


def message_has_keyword(routing: RoutingConfig | None, text: str) -> bool:
    """True when the message contains a keyword from a routing rule."""
    haystack = (text or "").lower()
    if not haystack:
        return False
    policy = routing or RoutingConfig()
    for rule in policy.rules:
        for word in rule.keywords:
            token = word.strip().lower()
            if token and token in haystack:
                return True
    return False


def apply_mention(model: str, text: str) -> str:
    """Let an @mention replace the requested model when that provider is ready."""
    mentioned = mention_model(text)
    if not mentioned:
        return model
    chosen = _usable(mentioned)
    return chosen or model

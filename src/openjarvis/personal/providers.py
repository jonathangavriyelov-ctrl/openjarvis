"""Which cloud providers have a key, and a one-line connectivity test.

The key value is never returned, logged, or written. Presence is the only
signal the settings page is allowed to see.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_PROVIDERS = (
    {
        "id": "anthropic",
        "name": "Anthropic",
        "env": "ANTHROPIC_API_KEY",
        "kind": "anthropic",
        "model": "claude-haiku-4-5",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "env": "OPENAI_API_KEY",
        "kind": "openai",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    {
        "id": "xai",
        "name": "xAI",
        "env": "XAI_API_KEY",
        "kind": "openai",
        "model": "grok-3",
        "base_url": "https://api.x.ai/v1",
    },
)

_PROMPT = "Reply with ok"


def _redact(text: str) -> str:
    cleaned = text
    for spec in _PROVIDERS:
        secret = os.environ.get(spec["env"]) or ""
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def provider_status() -> list[dict[str, Any]]:
    """Connected or not, from environment presence only."""
    rows = []
    for spec in _PROVIDERS:
        rows.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "connected": bool(os.environ.get(spec["env"])),
            }
        )
    return rows


def _spec(provider_id: str) -> dict[str, str] | None:
    for spec in _PROVIDERS:
        if spec["id"] == provider_id:
            return spec
    return None


def probe_provider(provider_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Send a tiny prompt. The response never includes the key."""
    spec = _spec(provider_id)
    if spec is None:
        return {"ok": False, "detail": "Unknown provider.", "model": ""}
    key = os.environ.get(spec["env"]) or ""
    if not key:
        return {"ok": False, "detail": "Not connected.", "model": spec["model"]}
    try:
        if spec["kind"] == "anthropic":
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": spec["model"],
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": _PROMPT}],
                },
                timeout=timeout,
            )
        else:
            response = httpx.post(
                f"{spec['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "content-type": "application/json",
                },
                json={
                    "model": spec["model"],
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": _PROMPT}],
                },
                timeout=timeout,
            )
        if response.status_code >= 400:
            return {
                "ok": False,
                "detail": _redact(f"The provider returned {response.status_code}."),
                "model": spec["model"],
            }
        return {"ok": True, "detail": "Connected.", "model": spec["model"]}
    except Exception as exc:
        return {
            "ok": False,
            "detail": _redact(str(exc) or "The provider did not answer."),
            "model": spec["model"],
        }

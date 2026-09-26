"""Optional OmniRoute gateway for the personal agent team.

OmniRoute (github.com/diegosouzapw/OmniRoute) is a local OpenAI-compatible
gateway. One base URL fronts many providers, ``auto`` picks a provider, and
the gateway fails over when a provider is out of quota. This client speaks
that API: ``GET /v1/models`` and ``POST /v1/chat/completions``.

The desk uses it only when a base URL or key is configured. If the process
is not running, or the key is refused, callers keep the existing engine.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from openjarvis.personal.hermes import ModelChoice

logger = logging.getLogger(__name__)

DEFAULT_BASE = "http://127.0.0.1:20128/v1"
DEFAULT_MODEL = "auto"


def resolve_omniroute(
    *,
    enabled: bool = False,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
) -> tuple[str, str, str]:
    """Return ``(base_url, api_key, model)``. Environment wins over config.

    An empty base URL means OmniRoute is off. A key or ``enabled`` with no
    URL uses the local default, ``http://127.0.0.1:20128/v1``.
    """
    base = os.environ.get("OMNIROUTE_BASE_URL", "").strip() or (base_url or "").strip()
    key = os.environ.get("OMNIROUTE_API_KEY", "").strip() or (api_key or "").strip()
    chosen = os.environ.get("OMNIROUTE_MODEL", "").strip() or (model or "").strip()
    if not base and (enabled or key):
        base = DEFAULT_BASE
    return base.rstrip("/"), key, chosen or DEFAULT_MODEL


class OmniRouteClient:
    """Probe an OmniRoute gateway and send chat completions through it."""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        *,
        default_model: str = DEFAULT_MODEL,
        agent_models: dict[str, str] | None = None,
        http: Callable[..., tuple[int, dict[str, Any]]] | None = None,
        cache_seconds: float = 15.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.default_model = default_model or DEFAULT_MODEL
        self.agent_models = {
            str(key): str(value)
            for key, value in (agent_models or {}).items()
            if key and value
        }
        self._http = http
        self.cache_seconds = cache_seconds
        self._checked_at = 0.0
        self._reachable = False
        self._models: list[str] = []
        self._detail = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def api_root(self) -> str:
        if self.base_url.endswith("/v1"):
            return self.base_url
        return f"{self.base_url}/v1"

    def public_status(self) -> dict[str, Any]:
        """Status safe for the dashboard. The API key is not included."""
        if self.configured:
            self._ensure_probed()
        return {
            "configured": self.configured,
            "reachable": self._reachable,
            "base_url": _public_url(self.api_root) if self.configured else "",
            "default_model": self.default_model,
            "models": list(self._models[:12]),
            "detail": self._detail,
        }

    def choice_for(
        self,
        specialist_id: str,
        *,
        hermes_model: str = "",
        prefers_hermes: bool = False,
        model: str = "",
    ) -> ModelChoice:
        """Pick the OmniRoute model id for one agent."""
        self._ensure_probed()
        override = (model or self.agent_models.get(specialist_id, "")).strip()
        if prefers_hermes or specialist_id == "executive_assistant":
            return self._hermes_choice(override or hermes_model)
        model = override or self.default_model
        if model != DEFAULT_MODEL and self._models and not _listed(model, self._models):
            return ModelChoice(
                self.default_model,
                "omniroute",
                (
                    f"{model} is not in the OmniRoute catalog. "
                    f"Using {self.default_model}, which lets OmniRoute choose "
                    "a provider and fall back."
                ),
                route="omniroute",
            )
        return ModelChoice(
            model,
            "omniroute",
            f"Through OmniRoute at {_public_url(self.api_root)} as {model}.",
            route="omniroute",
        )

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
    ) -> tuple[str, str] | None:
        """Return ``(text, model_id)`` or None when the gateway cannot answer."""
        if not self.configured:
            return None
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 900,
        }
        try:
            status, body = self._request(
                "POST",
                f"{self.api_root}/chat/completions",
                payload,
            )
        except Exception:
            logger.debug("OmniRoute chat failed", exc_info=True)
            self._reachable = False
            self._detail = "OmniRoute could not be reached."
            self._checked_at = time.monotonic()
            return None
        if status >= 400:
            self._detail = f"OmniRoute returned {status}."
            return None
        text = _message_text(body)
        if not text:
            return None
        actual = str(body.get("model") or model or self.default_model)
        return text, actual

    def _hermes_choice(self, wanted: str) -> ModelChoice:
        name = (wanted or "").strip()
        listed = _find(name, self._models) if name else ""
        if listed:
            return ModelChoice(
                listed,
                "omniroute",
                f"Executive Assistant calls Hermes model {listed} through OmniRoute.",
                route="omniroute",
            )
        hermes_named = [item for item in self._models if "hermes" in item.lower()]
        if hermes_named:
            return ModelChoice(
                hermes_named[0],
                "omniroute",
                (
                    f"OmniRoute lists Hermes model {hermes_named[0]}. "
                    "The Executive Assistant is using that."
                ),
                route="omniroute",
            )
        fallback = self.default_model or DEFAULT_MODEL
        missing = name or "hermes3"
        return ModelChoice(
            fallback,
            "omniroute",
            (
                f"OmniRoute is up, and {missing} is not in its catalog. "
                f"Using {fallback} so OmniRoute can pick a provider and fall back."
            ),
            route="omniroute",
        )

    def _ensure_probed(self) -> None:
        if not self.configured:
            self._reachable = False
            self._detail = "OmniRoute is not configured."
            return
        age = time.monotonic() - self._checked_at
        if self._checked_at and age < self.cache_seconds:
            return
        self._probe()

    def _probe(self) -> None:
        self._checked_at = time.monotonic()
        try:
            status, body = self._request("GET", f"{self.api_root}/models", None)
        except Exception:
            logger.debug("OmniRoute probe failed", exc_info=True)
            self._reachable = False
            self._models = []
            self._detail = (
                "OmniRoute is not running. Agents are using the local engine."
            )
            return
        if status >= 400:
            self._reachable = False
            self._models = []
            self._detail = (
                f"OmniRoute returned {status}. Agents are using the local engine."
            )
            return
        self._reachable = True
        self._models = _model_ids(body)
        self._detail = f"OmniRoute is routing at {_public_url(self.api_root)}."

    def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        header = f"Bearer {self.api_key}" if self.api_key else ""
        if self._http is not None:
            return self._http(method, url, payload, header)
        import httpx

        headers = {"Content-Type": "application/json"}
        if header:
            headers["Authorization"] = header
        with httpx.Client(timeout=8) as client:
            response = client.request(method, url, json=payload, headers=headers)
        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return response.status_code, body


def _public_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _model_ids(body: dict[str, Any]) -> list[str]:
    raw = body.get("data")
    if not isinstance(raw, list):
        raw = body.get("models") if isinstance(body.get("models"), list) else []
    found: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            found.append(item)
        elif isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or "")
            if name:
                found.append(name)
    return found


def _listed(wanted: str, names: list[str]) -> bool:
    return bool(_find(wanted, names))


def _find(wanted: str, names: list[str]) -> str:
    target = wanted.strip().lower()
    if not target:
        return ""
    stem = target.split(":", 1)[0]
    for name in names:
        lowered = name.lower()
        if lowered == target or lowered.split(":", 1)[0] == stem:
            return name
    return ""


def _message_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content") or ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts).strip()
    return ""

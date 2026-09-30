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
import threading
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
        self._usage = threading.local()
        self.strong_model = ""
        self.cheap_model = ""

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
        if specialist_id == "chief_of_staff" and not override:
            return self._tier_choice("strong", self.strong_model)
        if specialist_id == "second_brain" and not override:
            return self._tier_choice("cheap", self.cheap_model)
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
            status, body, headers = self._request(
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
        self._usage.last = _usage_from(body, headers, payload, text)
        return text, actual

    def take_usage(self) -> dict[str, Any]:
        usage = getattr(self._usage, "last", None) or {}
        self._usage.last = {}
        return dict(usage)

    def usage_summary(self) -> dict[str, Any] | None:
        """Monthly cost from OmniRoute's usage API, when that route exists."""
        if not self.configured:
            return None
        if self.api_root.endswith("/v1"):
            origin = self.api_root[: -len("/v1")]
        else:
            origin = self.base_url
        try:
            status, body, _headers = self._request(
                "GET",
                f"{origin}/api/usage/analytics?range=30d",
                None,
            )
        except Exception:
            logger.debug("OmniRoute usage lookup failed", exc_info=True)
            return None
        if status >= 400 or not isinstance(body, dict):
            return None
        cost = _analytics_cost(body)
        if cost is None:
            return None
        return {"cost": round(float(cost), 4), "range": "30d"}

    def _tier_choice(self, tier: str, configured: str) -> ModelChoice:
        wanted = (configured or "").strip()
        if wanted:
            listed = _find(wanted, self._models) or wanted
            return ModelChoice(
                listed,
                "omniroute",
                f"Through OmniRoute as {listed}.",
                route="omniroute",
            )
        if tier == "strong":
            picked = _pick(
                self._models, _STRONG_HINTS, avoid=("mini", "flash", "haiku")
            )
            detail = "Chief of Staff planning uses the strongest OmniRoute model."
        else:
            picked = _pick(self._models, _CHEAP_HINTS)
            detail = "Routine notes use a cheap, fast OmniRoute model."
        if not picked:
            picked = self.default_model or DEFAULT_MODEL
            detail = f"{detail} Using {picked}."
        else:
            detail = f"{detail} Using {picked}."
        return ModelChoice(picked, "omniroute", detail, route="omniroute")

    def _hermes_choice(self, wanted: str) -> ModelChoice:
        name = (wanted or "").strip()
        if _is_hermes4(name):
            name = "hermes3"
        listed = _find(name, self._models) if name and not _is_hermes4(name) else ""
        if listed and _is_hermes3(listed):
            return ModelChoice(
                listed,
                "omniroute",
                (
                    f"Executive Assistant calls Hermes 3 ({listed}) through OmniRoute. "
                    "Hermes 4 is not used for tool-calling loops."
                ),
                route="omniroute",
            )
        hermes3 = [item for item in self._models if _is_hermes3(item)]
        if hermes3:
            return ModelChoice(
                hermes3[0],
                "omniroute",
                (
                    f"Executive Assistant calls Hermes 3 ({hermes3[0]}) "
                    "through OmniRoute. "
                    "Hermes 4 is not used for tool-calling loops."
                ),
                route="omniroute",
            )
        older = [
            item
            for item in self._models
            if "hermes" in item.lower() and not _is_hermes4(item)
        ]
        if older:
            return ModelChoice(
                older[0],
                "omniroute",
                (
                    f"Executive Assistant calls Hermes model {older[0]} "
                    "through OmniRoute. "
                    "Hermes 4 is not used for tool-calling loops."
                ),
                route="omniroute",
            )
        fallback = self.default_model or DEFAULT_MODEL
        missing = name or "hermes3"
        return ModelChoice(
            fallback,
            "omniroute",
            (
                f"Hermes 3 ({missing}) is not in the OmniRoute catalog. "
                "Hermes 4 is not used for tool-calling loops. "
                f"Using {fallback}."
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
            status, body, _headers = self._request(
                "GET", f"{self.api_root}/models", None
            )
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
            result = self._http(method, url, payload, header)
            if len(result) == 2:
                return result[0], result[1], {}
            return result[0], result[1], result[2]
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
        response_headers = {
            key.lower(): value for key, value in response.headers.items()
        }
        return response.status_code, body, response_headers


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


_STRONG_HINTS = ("gpt-4o", "gpt-4.1", "claude-opus", "claude-sonnet", "o3", "o1")
_CHEAP_HINTS = ("gpt-4o-mini", "gpt-4.1-mini", "haiku", "flash", "mini")


def _is_hermes4(name: str) -> bool:
    compact = (name or "").lower().replace("_", "").replace("-", "")
    return "hermes4" in compact


def _is_hermes3(name: str) -> bool:
    compact = (name or "").lower().replace("_", "").replace("-", "")
    return "hermes3" in compact


def _pick(
    names: list[str], hints: tuple[str, ...], *, avoid: tuple[str, ...] = ()
) -> str:
    for hint in hints:
        for name in names:
            lowered = name.lower()
            if hint in lowered and not any(word in lowered for word in avoid):
                return name
    return ""


def _usage_from(
    body: dict[str, Any],
    headers: dict[str, Any],
    payload: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    raw_in = usage.get("prompt_tokens", headers.get("x-omniroute-tokens-in"))
    raw_out = usage.get("completion_tokens", headers.get("x-omniroute-tokens-out"))
    try:
        reported = float(headers["x-omniroute-response-cost"])
    except (KeyError, TypeError, ValueError):
        reported = None
    prompt = " ".join(
        str(item.get("content") or "")
        for item in (payload.get("messages") or [])
        if isinstance(item, dict)
    )
    input_tokens = int(raw_in) if raw_in not in (None, "") else max(1, len(prompt) // 4)
    if raw_out not in (None, ""):
        output_tokens = int(raw_out)
    else:
        output_tokens = max(1, len(text) // 4)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reported_cost": reported,
    }


def _analytics_cost(body: dict[str, Any]) -> float | None:
    summary = body.get("summary") if isinstance(body.get("summary"), dict) else {}
    for source in (summary, body):
        for key in ("totalCost", "cost", "costUsd", "total_cost"):
            if source.get(key) is not None:
                try:
                    return float(source[key])
                except (TypeError, ValueError):
                    continue
    return None


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

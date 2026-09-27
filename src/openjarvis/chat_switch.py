"""Per-conversation provider choice and the Grok → Claude → Local fallback.

OpenAI is offered in the switcher. It is not part of the automatic
fallback chain. API keys are read from the environment and never returned.
"""

from __future__ import annotations

import os
from typing import Any, Callable

_LOCAL_MODEL = "hermes3:8b"
_LOCAL_FALLBACK = "qwen3.5:4b"

PROVIDERS: dict[str, dict[str, Any]] = {
    "grok": {
        "id": "grok",
        "label": "Grok",
        "hint": "Fast, knows what's happening now",
        "eli5": "Quick, and it knows what is new",
        "model": "grok-4.7",
        "env": "XAI_API_KEY",
        "cloud_id": "xai",
    },
    "claude": {
        "id": "claude",
        "label": "Claude",
        "hint": "Deeper thinking and analysis",
        "eli5": "Thinks harder",
        "model": "claude-opus-5-5",
        "env": "ANTHROPIC_API_KEY",
        "cloud_id": "anthropic",
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "hint": "Backup / second opinion",
        "eli5": "A second opinion",
        "model": "gpt-6-sol",
        "env": "OPENAI_API_KEY",
        "cloud_id": "openai",
    },
    "local": {
        "id": "local",
        "label": "Local",
        "hint": "Free and private, works offline",
        "eli5": "Free, private, and works without the internet",
        "model": _LOCAL_MODEL,
        "env": "",
        "cloud_id": "local",
    },
}

_ALIASES = {
    "xai": "grok",
    "anthropic": "claude",
    "gpt": "openai",
    "hermes": "local",
}

_CHAIN = ("grok", "claude", "local")
_needs_credits: set[str] = set()

Caller = Callable[[str, str], str | None]


class AttemptFailed(Exception):
    """One provider could not answer. The message never includes a key."""

    def __init__(self, detail: str, *, needs_credits: bool = False) -> None:
        super().__init__(detail)
        self.needs_credits = needs_credits


def normalize_choice(value: str | None) -> str:
    """Map a switcher id onto grok, claude, openai, or local."""
    text = (value or "").strip().lower()
    text = _ALIASES.get(text, text)
    if text in PROVIDERS:
        return text
    return "grok"


def model_for(provider: str) -> str:
    return str(PROVIDERS[normalize_choice(provider)]["model"])


def label_for(provider: str, *, eli5: bool = False) -> str:
    spec = PROVIDERS[normalize_choice(provider)]
    if eli5 and provider == "local":
        return "On this Mac"
    return str(spec["label"])


def hint_for(provider: str, *, eli5: bool = False) -> str:
    spec = PROVIDERS[normalize_choice(provider)]
    return str(spec["eli5"] if eli5 else spec["hint"])


def catalog(*, eli5: bool = False) -> list[dict[str, str]]:
    rows = []
    for key in ("grok", "claude", "openai", "local"):
        rows.append(
            {
                "id": key,
                "label": label_for(key, eli5=eli5),
                "hint": hint_for(key, eli5=eli5),
                "model": model_for(key),
            }
        )
    return rows


def credits_error(text: str) -> bool:
    """True when a provider says the account has no credits."""
    lowered = (text or "").lower()
    return "insufficient_quota" in lowered or "credit_balance_exhausted" in lowered


def mark_needs_credits(provider: str) -> None:
    choice = normalize_choice(provider)
    _needs_credits.add(choice)
    cloud = str(PROVIDERS[choice].get("cloud_id") or "")
    if cloud:
        _needs_credits.add(cloud)


def provider_needs_credits(provider: str) -> bool:
    known = provider in _ALIASES or provider in PROVIDERS
    choice = normalize_choice(provider) if known else provider
    if choice in _needs_credits or provider in _needs_credits:
        return True
    cloud = str(PROVIDERS.get(choice, {}).get("cloud_id") or "")
    return bool(cloud and cloud in _needs_credits)


def clear_needs_credits() -> None:
    """Test helper. Production calls only add to the set."""
    _needs_credits.clear()


def key_ready(provider: str) -> bool:
    """Local is always ready. A demo stub pretends the cloud keys exist."""
    if provider == "local":
        return True
    if os.environ.get("OPENJARVIS_CHAT_STUB") == "1":
        return True
    spec = PROVIDERS.get(normalize_choice(provider))
    if spec is None:
        return False
    env_name = str(spec.get("env") or "")
    if not env_name:
        return True
    return bool(os.environ.get(env_name))


def attempt_order(
    choice: str,
    *,
    private: bool = False,
    unavailable: set[str] | None = None,
) -> list[str]:
    """Chosen provider, then Grok, Claude, and Local.

    OpenAI is included only when it is the choice. A provider already
    marked as needing credits is skipped in the automatic chain. The
    explicit choice is still tried once. A private task stays local.
    """
    if private:
        return ["local"]
    requested = normalize_choice(choice)
    blocked = set(unavailable or ())
    chain = [requested]
    for item in _CHAIN:
        if item not in chain:
            chain.append(item)
    ready: list[str] = []
    for index, item in enumerate(chain):
        if item != "local" and not key_ready(item):
            continue
        if item in blocked and index != 0:
            continue
        if provider_needs_credits(item) and index != 0:
            continue
        ready.append(item)
    if "local" not in ready:
        ready.append("local")
    return ready


def fallback_note(
    requested: str,
    answered: str,
    *,
    needs_credits: bool = False,
    eli5: bool = False,
) -> str:
    """Plain sentence naming who was asked and who answered."""
    asked = normalize_choice(requested)
    used = normalize_choice(answered) if answered else ""
    if not used or asked == used:
        return ""
    if used == "local":
        who = "the helper on this Mac" if eli5 else "Hermes on your Mac"
    else:
        who = label_for(used, eli5=eli5)
    if needs_credits and asked == "openai":
        return f"OpenAI needs credits, so {who} answered."
    asked_label = label_for(asked, eli5=eli5)
    return f"{asked_label} was not available, so {who} answered."


def run_attempts(
    choice: str,
    caller: Caller,
    *,
    private: bool = False,
    eli5: bool = False,
    unavailable: set[str] | None = None,
) -> dict[str, Any]:
    """Try providers until one returns text. Never raise to the caller."""
    requested = "local" if private else normalize_choice(choice)
    saw_credits = provider_needs_credits("openai") and requested == "openai"
    answered = ""
    used = ""
    used_model = ""
    for provider in attempt_order(requested, private=private, unavailable=unavailable):
        model = model_for(provider)
        if provider == "local":
            model = _LOCAL_MODEL
        try:
            text = caller(provider, model)
        except AttemptFailed as exc:
            if exc.needs_credits or credits_error(str(exc)):
                saw_credits = True
                mark_needs_credits(provider)
            continue
        except Exception as exc:
            if credits_error(str(exc)):
                saw_credits = True
                mark_needs_credits(provider)
            continue
        cleaned = str(text or "").strip()
        if not cleaned:
            continue
        answered = cleaned
        used = provider
        used_model = model
        break
    note = fallback_note(
        requested,
        used,
        needs_credits=saw_credits,
        eli5=eli5,
    )
    if not answered:
        answered = "Nobody could answer just now."
        if not note:
            note = answered
    return {
        "ok": bool(used),
        "content": answered,
        "provider": used,
        "requested": requested,
        "model": used_model,
        "label": label_for(used, eli5=eli5) if used else "",
        "note": note,
        "needs_credits": saw_credits,
    }


def _stub_call(provider: str, model: str) -> str:
    del model
    if provider == "openai":
        raise AttemptFailed("insufficient_quota", needs_credits=True)
    failed = {
        item.strip()
        for item in os.environ.get("OPENJARVIS_CHAT_STUB_FAIL", "").split(",")
        if item.strip()
    }
    if provider in failed:
        raise AttemptFailed("The provider did not answer.")
    return f"{label_for(provider)} answered."


def _cloud_call(provider: str, model: str, messages: list[dict[str, str]]) -> str:
    import httpx

    spec = PROVIDERS[provider]
    key = os.environ.get(str(spec["env"])) or ""
    if not key:
        raise AttemptFailed("Not connected.")
    try:
        if provider == "claude":
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 900,
                    "messages": [
                        item for item in messages if item.get("role") != "system"
                    ],
                },
                timeout=45.0,
            )
        else:
            payload: dict[str, Any] = {
                "model": model,
                "max_tokens": 900,
                "messages": messages,
            }
            if model.startswith("gpt-6"):
                payload["reasoning_effort"] = "none"
            base = (
                "https://api.x.ai/v1"
                if provider == "grok"
                else "https://api.openai.com/v1"
            )
            response = httpx.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=45.0,
            )
    except AttemptFailed:
        raise
    except Exception:
        raise AttemptFailed("The provider did not answer.") from None
    body = ""
    try:
        body = response.text or ""
    except Exception:
        body = ""
    if response.status_code >= 400:
        needs = credits_error(body)
        raise AttemptFailed(
            "Needs credits." if needs else "The provider did not answer.",
            needs_credits=needs,
        )
    try:
        data = response.json()
    except Exception:
        raise AttemptFailed("The provider did not answer.") from None
    if provider == "claude":
        blocks = data.get("content") if isinstance(data, dict) else None
        if isinstance(blocks, list):
            parts = [
                str(block.get("text") or "")
                for block in blocks
                if isinstance(block, dict)
            ]
            text = "\n".join(part for part in parts if part).strip()
            if text:
                return text
        raise AttemptFailed("The provider did not answer.")
    choices = data.get("choices") if isinstance(data, dict) else None
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        text = str((message or {}).get("content") or "").strip()
        if text:
            return text
    raise AttemptFailed("The provider did not answer.")


def _local_call(engine: Any, messages: list[dict[str, str]], model: str) -> str:
    if engine is None:
        raise AttemptFailed("The model on this Mac is not running.")
    from openjarvis.core.types import Message, Role

    payload = []
    for item in messages:
        role_name = str(item.get("role") or "user")
        if role_name == "assistant":
            role = Role.ASSISTANT
        elif role_name == "system":
            role = Role.SYSTEM
        else:
            role = Role.USER
        payload.append(Message(role=role, content=str(item.get("content") or "")))
    models = [model]
    if _LOCAL_FALLBACK not in models:
        models.append(_LOCAL_FALLBACK)
    last = "The model on this Mac is not running."
    for candidate in models:
        try:
            result = engine.generate(
                payload,
                model=candidate,
                temperature=0.4,
                max_tokens=900,
            )
        except Exception:
            last = "The model on this Mac did not answer."
            continue
        if isinstance(result, dict):
            text = str(result.get("content") or "").strip()
        else:
            text = str(result or "").strip()
        if text:
            return text
    raise AttemptFailed(last)


def answer_chat(
    messages: list[dict[str, str]],
    provider: str,
    *,
    private: bool = False,
    eli5: bool = False,
    engine: Any = None,
    caller: Caller | None = None,
) -> dict[str, Any]:
    """Answer with the chosen provider, then the fallback chain."""

    def default_caller(pid: str, model: str) -> str:
        if os.environ.get("OPENJARVIS_CHAT_STUB") == "1":
            return _stub_call(pid, model)
        if pid == "local":
            return _local_call(engine, messages, model)
        return _cloud_call(pid, model, messages)

    return run_attempts(
        provider,
        caller or default_caller,
        private=private,
        eli5=eli5,
    )

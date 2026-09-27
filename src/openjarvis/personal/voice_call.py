"""Live voice calls for the personal desk.

Grok uses xAI speech-to-speech when the key and the monthly budget allow
one paid minute. Claude, Local, a private chat, a missing key, or a tight
budget stay on this Mac: speech-to-text, the selected text model, then the
Mac voice. The long-lived API key never leaves the server.
"""

from __future__ import annotations

import base64
import io
import math
import os
import struct
import wave
from typing import Any, Callable

import httpx

from openjarvis.chat_switch import (
    answer_chat,
    label_for,
    model_for,
    normalize_choice,
    provider_needs_credits,
)

# Public guides quote about $0.05 a minute for Grok voice. The official
# page we checked did not list a price, so this stays an estimate.
GROK_USD_PER_MIN = 0.05
# OpenAI realtime audio is about $0.06 in plus $0.24 out per minute.
OPENAI_USD_PER_MIN = 0.30
XAI_VOICE_MODEL = "grok-voice-latest"
OPENAI_VOICE_MODEL = "gpt-realtime"
XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
XAI_SECRET_URL = "https://api.x.ai/v1/realtime/client_secrets"
OPENAI_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
_MAX_BILLED_SECONDS = 30 * 60
_SAMPLE_RATE = 24000

BUDGET_NOTE = (
    "The monthly budget is too close for a paid voice call, "
    "so this call stays on this Mac."
)
CLAUDE_NOTE = "Listening on this Mac. Claude writes the answer."
LOCAL_NOTE = "Listening on this Mac."
JARVIS_INSTRUCTIONS = (
    "You are Jarvis, Jonathan's assistant. Answer out loud in short, "
    "clear sentences. Wait to be interrupted."
)

Mint = Callable[[str], dict[str, Any]]
Transcriber = Callable[[bytes], str]


def voice_cost(mode: str, provider: str, seconds: float) -> float:
    """USD for a connected realtime call. Local speech is free."""
    if mode != "realtime":
        return 0.0
    rate = _rate(provider)
    if rate <= 0 or seconds <= 0:
        return 0.0
    billed = min(float(seconds), _MAX_BILLED_SECONDS)
    return round(rate * billed / 60.0, 6)


def _rate(provider: str) -> float:
    choice = normalize_choice(provider)
    if choice == "grok":
        return GROK_USD_PER_MIN
    if choice == "openai":
        return OPENAI_USD_PER_MIN
    return 0.0


def _live_key(provider: str) -> str:
    names = {
        "grok": "XAI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }
    return os.environ.get(names.get(provider, ""), "").strip()


def _room_for(amount: float, **budget: float) -> bool:
    """True when one paid minute fits under every cap that is set."""
    if amount <= 0:
        return True
    rooms: list[float] = []
    overall_cap = float(budget.get("overall_cap") or 0)
    world_cap = float(budget.get("world_cap") or 0)
    if overall_cap > 0:
        rooms.append(overall_cap - float(budget.get("spent_overall") or 0))
    if world_cap > 0:
        rooms.append(world_cap - float(budget.get("spent_world") or 0))
    if not rooms:
        return True
    return min(rooms) >= amount


def choose_path(
    provider: str,
    *,
    private: bool = False,
    budget_ok: bool = True,
) -> str:
    """``realtime_xai``, ``realtime_openai``, or ``bridge``."""
    choice = "local" if private else normalize_choice(provider)
    if private or choice in {"local", "claude"} or not budget_ok:
        return "bridge"
    openai_ready = bool(_live_key("openai")) and not provider_needs_credits(
        "openai"
    )
    if choice == "openai" and openai_ready:
        return "realtime_openai"
    if choice == "openai" and _live_key("grok"):
        return "realtime_xai"
    if choice == "grok" and _live_key("grok"):
        return "realtime_xai"
    return "bridge"


def _scrub(payload: dict[str, Any]) -> dict[str, Any]:
    import json

    secrets = [
        _live_key("grok"),
        _live_key("openai"),
        _live_key("claude"),
    ]
    text = json.dumps(payload)
    for secret in secrets:
        if secret and len(secret) > 6:
            text = text.replace(secret, "")
    return json.loads(text)


def _session_update(model: str) -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "model": model,
            "voice": "eve",
            "instructions": JARVIS_INSTRUCTIONS,
            "turn_detection": {"type": "server_vad"},
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                    "transcription": {"model": "grok-transcribe"},
                },
                "output": {"format": {"type": "audio/pcm", "rate": _SAMPLE_RATE}},
            },
        },
    }


def _local_plan(
    provider: str,
    *,
    note: str,
    needs_credits: bool = False,
) -> dict[str, Any]:
    choice = normalize_choice(provider)
    return {
        "mode": "local",
        "provider": choice,
        "brain": choice,
        "model": model_for(choice),
        "url": "",
        "protocol": "",
        "token": "",
        "expires_at": 0,
        "usd_per_minute": 0.0,
        "note": note,
        "needs_credits": needs_credits,
        "sample_rate": _SAMPLE_RATE,
        "session_update": {},
    }


def _note_for(
    requested: str,
    path: str,
    *,
    budget_blocked: bool,
    needs_credits: bool,
) -> str:
    if budget_blocked:
        if requested == "claude":
            return f"{BUDGET_NOTE} {CLAUDE_NOTE}"
        return BUDGET_NOTE
    if path == "realtime_xai" and needs_credits:
        return "OpenAI needs credits, so this call uses Grok."
    if path == "bridge" and needs_credits:
        return "OpenAI needs credits, so this call stays on this Mac."
    if path == "bridge" and requested == "claude":
        return CLAUDE_NOTE
    if path == "bridge":
        return LOCAL_NOTE
    return ""


def plan_session(
    provider: str,
    *,
    private: bool = False,
    spent_overall: float = 0.0,
    spent_world: float = 0.0,
    overall_cap: float = 0.0,
    world_cap: float = 0.0,
    mint: Mint | None = None,
) -> dict[str, Any]:
    """Describe how the browser should place this call."""
    requested = "local" if private else normalize_choice(provider)
    if os.environ.get("OPENJARVIS_VOICE_STUB") == "1":
        return _scrub(
            _local_plan(requested, note=LOCAL_NOTE, needs_credits=False)
        )
    optimistic = choose_path(requested, private=private, budget_ok=True)
    paid = optimistic.startswith("realtime_")
    voice_provider = "openai" if optimistic == "realtime_openai" else "grok"
    rate = _rate(voice_provider) if paid else 0.0
    budget_ok = _room_for(
        rate,
        spent_overall=spent_overall,
        spent_world=spent_world,
        overall_cap=overall_cap,
        world_cap=world_cap,
    )
    path = optimistic if budget_ok else "bridge"
    needs_credits = provider_needs_credits("openai") and requested == "openai"
    note = _note_for(
        requested,
        path,
        budget_blocked=paid and not budget_ok,
        needs_credits=needs_credits and path != "realtime_openai",
    )
    if path == "bridge":
        return _scrub(
            _local_plan(requested, note=note, needs_credits=needs_credits)
        )
    model = OPENAI_VOICE_MODEL if path == "realtime_openai" else XAI_VOICE_MODEL
    url = OPENAI_REALTIME_URL if path == "realtime_openai" else XAI_REALTIME_URL
    prefix = (
        "openai-insecure-api-key."
        if path == "realtime_openai"
        else "xai-client-secret."
    )
    try:
        minted = (mint or mint_client_secret)(voice_provider)
    except Exception:
        fail = "The live voice line did not connect, so this call stays on this Mac."
        return _scrub(_local_plan(requested, note=fail, needs_credits=needs_credits))
    token = str(minted.get("value") or "").strip()
    long_lived = _live_key(voice_provider)
    if not token or (long_lived and long_lived in token):
        fail = "The live voice line did not connect, so this call stays on this Mac."
        return _scrub(_local_plan(requested, note=fail, needs_credits=needs_credits))
    plan = {
        "mode": "realtime",
        "provider": voice_provider,
        "brain": requested,
        "model": model,
        "url": f"{url}?model={model}",
        "protocol": f"{prefix}{token}",
        "token": token,
        "expires_at": int(minted.get("expires_at") or 0),
        "usd_per_minute": rate,
        "note": note,
        "needs_credits": needs_credits,
        "sample_rate": _SAMPLE_RATE,
        "session_update": _session_update(model),
    }
    return _scrub(plan)


def mint_client_secret(provider: str) -> dict[str, Any]:
    """Ask the vendor for a short-lived token. The API key stays here."""
    choice = normalize_choice(provider)
    if choice == "openai":
        url = OPENAI_SECRET_URL
        key = _live_key("openai")
        body: dict[str, Any] = {
            "expires_after": {"seconds": 600},
            "session": {"type": "realtime", "model": OPENAI_VOICE_MODEL},
        }
    else:
        url = XAI_SECRET_URL
        key = _live_key("grok")
        body = {
            "expires_after": {"seconds": 600},
            "session": _session_update(XAI_VOICE_MODEL)["session"],
        }
    if not key:
        raise RuntimeError("No voice key is set.")
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json=body,
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    value = data.get("value") or ""
    nested = data.get("client_secret")
    if not value and isinstance(nested, dict):
        value = nested.get("value") or ""
    return {"value": str(value), "expires_at": int(data.get("expires_at") or 0)}


def tone_wav_b64(seconds: float = 1.2, frequency: float = 440.0) -> str:
    """A tiny valid WAV so the browser can play something without a voice."""
    rate = _SAMPLE_RATE
    count = max(1, int(rate * seconds))
    frames = bytearray()
    for index in range(count):
        sample = int(0.2 * 32767 * math.sin(2 * math.pi * frequency * index / rate))
        frames += struct.pack("<h", sample)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def transcribe_locally(audio: bytes) -> str:
    """Use faster-whisper when it is installed. Otherwise return nothing."""
    if not audio:
        return ""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return ""
    import tempfile

    path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(audio)
            path = handle.name
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(path)
        return " ".join(segment.text.strip() for segment in segments).strip()
    except Exception:
        return ""
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def run_local_turn(
    *,
    audio: bytes = b"",
    transcript: str = "",
    practice: bool = False,
    provider: str = "grok",
    private: bool = False,
    eli5: bool = False,
    messages: list[dict[str, Any]] | None = None,
    engine: Any = None,
    caller: Any = None,
    transcriber: Transcriber | None = None,
) -> dict[str, Any]:
    """Hear one utterance, ask the selected brain, and return speech."""
    choice = "local" if private else normalize_choice(provider)
    if os.environ.get("OPENJARVIS_VOICE_STUB") == "1":
        heard = "Hello Jarvis."
        reply = {
            "content": f"{label_for(choice, eli5=eli5)} answered.",
            "provider": choice,
            "model": model_for(choice),
            "label": label_for(choice, eli5=eli5),
            "note": "",
            "needs_credits": False,
        }
        return _scrub(_turn_payload(heard, reply))

    heard = transcript.strip()
    if practice and not heard:
        heard = "Hello Jarvis."
    if not heard and audio:
        heard = (transcriber or transcribe_locally)(audio).strip()
    if not heard:
        empty = {
            "content": "I could not hear that.",
            "provider": choice,
            "model": model_for(choice),
            "label": label_for(choice, eli5=eli5),
            "note": "",
            "needs_credits": False,
        }
        return _scrub(_turn_payload("", empty, audio_b64=""))
    history = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            history.append(
                {"role": str(item.get("role") or "user"), "content": content}
            )
    history.append({"role": "user", "content": heard})
    reply = answer_chat(
        history[-12:],
        choice,
        private=private,
        eli5=eli5,
        engine=engine,
        caller=caller,
    )
    return _scrub(_turn_payload(heard, reply))


def _turn_payload(
    heard: str,
    reply: dict[str, Any],
    *,
    audio_b64: str | None = None,
) -> dict[str, Any]:
    spoken = audio_b64 if audio_b64 is not None else tone_wav_b64()
    return {
        "transcript": heard,
        "content": str(reply.get("content") or ""),
        "provider": str(reply.get("provider") or ""),
        "model": str(reply.get("model") or ""),
        "label": str(reply.get("label") or ""),
        "note": str(reply.get("note") or ""),
        "needs_credits": bool(reply.get("needs_credits")),
        "audio_base64": spoken,
        "audio_kind": "tone" if spoken else "none",
        "sample_rate": _SAMPLE_RATE,
        "usd": 0.0,
    }

"""Live voice calls for the personal desk.

Grok uses xAI speech-to-speech when the key and the monthly budget allow
one paid minute. Claude, Local, a private chat, a missing key, or a tight
budget stay on this Mac: speech-to-text, the selected text model, then the
Mac voice. The long-lived API key never leaves the server.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

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
VOICE_PERSONA = (
    "You are Jarvis, talking with Jonathan out loud. "
    "Sound conversational. Use contractions. "
    "Answer in one or two sentences. "
    "No lists, no markdown, no stage directions. "
    "He may interrupt you. Stop as soon as he starts talking."
)
_INSTRUCTION_CAP = 3000
_IDLE_SECONDS = 300
_SAY_PREFERENCE = ("Samantha", "Ava", "Allison", "Zoe", "Daniel", "Karen")
_BASE_KEYTERMS = (
    "Jarvis",
    "Jonathan",
    "Gavriyelov",
    "Claude",
    "Grok",
    "Anthropic",
    "xAI",
    "OpenJarvis",
    "Quick Funders",
    "Gavco",
    "Glatt Express",
)
logger = logging.getLogger(__name__)


class _ModelCache:
    """One warm speech model. Dropped after five idle minutes."""

    def __init__(self) -> None:
        self.whisper: Any = None
        self.whisper_used = 0.0
        self.kokoro: Any = None
        self.kokoro_used = 0.0
        self.kokoro_unavailable = False
        self.say_voice: str | None = None


_cache = _ModelCache()

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


def _without_secrets(text: str) -> str:
    cleaned = text
    for secret in (_live_key("grok"), _live_key("openai"), _live_key("claude")):
        if secret and len(secret) > 6:
            cleaned = cleaned.replace(secret, "")
    return cleaned


def _note_files() -> list[Path]:
    from openjarvis.core.paths import get_config_dir

    home = get_config_dir()
    return [home / name for name in ("USER.md", "SOUL.md", "MEMORY.md")]


def names_from_notes(text: str) -> list[str]:
    """Headings and ``Name:`` lines from a personal note."""
    found: list[str] = []
    pattern = re.compile(r"(?m)^#+\s+(.+)$|^(?:Name|name):\s*(.+)$")
    for match in pattern.finditer(text or ""):
        value = (match.group(1) or match.group(2) or "").strip()
        value = _without_secrets(value)[:50].strip()
        if value and value not in found:
            found.append(value)
    return found


def keyterms() -> list[str]:
    """Names the transcriber should not mis-hear."""
    terms = list(_BASE_KEYTERMS)
    for path in _note_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in names_from_notes(text):
            if name not in terms:
                terms.append(name)
    return terms[:100]


def voice_instructions() -> str:
    """Short spoken persona plus a trimmed excerpt of the desk notes."""
    parts = [VOICE_PERSONA, ""]
    for path in _note_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            parts.append(f"{path.name}:\n{_without_secrets(text)}")
    body = "\n".join(parts).strip()
    if len(body) <= _INSTRUCTION_CAP:
        return body
    trimmed = body[:_INSTRUCTION_CAP].rsplit(" ", 1)[0].strip()
    return trimmed or body[:_INSTRUCTION_CAP]


def xai_voice_name() -> str:
    """Built-in Grok voice. ``eve`` is the documented natural default."""
    return os.environ.get("OPENJARVIS_XAI_VOICE", "eve").strip() or "eve"


def _session_update(model: str) -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "model": model,
            "voice": xai_voice_name(),
            "instructions": voice_instructions(),
            "reasoning": {"effort": "none"},
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": 450,
                "prefix_padding_ms": 300,
            },
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                    "transport": "binary",
                    "transcription": {
                        "model": "grok-transcribe",
                        "language_hint": "en",
                        "keyterms": keyterms(),
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                    "transport": "binary",
                },
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
        "audio_transport": "json",
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
        "audio_transport": "binary",
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


def release_idle_models(now: float | None = None) -> None:
    """Drop speech models that have sat unused for five minutes."""
    moment = time.monotonic() if now is None else now
    if _cache.whisper is not None and moment - _cache.whisper_used >= _IDLE_SECONDS:
        _cache.whisper = None
    if _cache.kokoro is not None and moment - _cache.kokoro_used >= _IDLE_SECONDS:
        closer = getattr(_cache.kokoro, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
        _cache.kokoro = None


def _temp_audio(audio: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(audio)
        return handle.name


def _drop(path: str) -> None:
    if path and os.path.exists(path):
        os.unlink(path)


def _prompt_terms() -> str:
    return ", ".join(keyterms())


def transcribe_locally(audio: bytes) -> str:
    """Hear a wav with mlx-whisper when installed, else a warm faster-whisper."""
    if not audio:
        return ""
    heard = _transcribe_mlx(audio)
    if heard:
        return heard
    return _transcribe_faster(audio)


def _transcribe_mlx(audio: bytes) -> str:
    try:
        import mlx_whisper
    except ImportError:
        return ""
    path = _temp_audio(audio)
    repo = os.environ.get(
        "OPENJARVIS_MLX_WHISPER", "mlx-community/whisper-small-mlx"
    )
    prompt = _prompt_terms()
    try:
        try:
            result = mlx_whisper.transcribe(
                path,
                path_or_hf_repo=repo,
                language="en",
                initial_prompt=prompt,
            )
        except TypeError:
            result = mlx_whisper.transcribe(path, path_or_hf_repo=repo)
        if isinstance(result, dict):
            return str(result.get("text") or "").strip()
        return str(result or "").strip()
    except Exception:
        return ""
    finally:
        _drop(path)


def _load_whisper() -> Any:
    release_idle_models()
    if _cache.whisper is not None:
        _cache.whisper_used = time.monotonic()
        return _cache.whisper
    from faster_whisper import WhisperModel

    size = os.environ.get("OPENJARVIS_WHISPER_SIZE", "small")
    _cache.whisper = WhisperModel(
        size,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
    )
    _cache.whisper_used = time.monotonic()
    return _cache.whisper


def _read_segments(model: Any, path: str) -> str:
    prompt = _prompt_terms()
    kwargs = {
        "beam_size": 1,
        "language": "en",
        "condition_on_previous_text": False,
        "initial_prompt": prompt,
        "hotwords": prompt,
    }
    try:
        segments, _info = model.transcribe(path, **kwargs)
    except TypeError:
        kwargs.pop("hotwords", None)
        segments, _info = model.transcribe(path, **kwargs)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _transcribe_faster(audio: bytes) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return ""
    del WhisperModel
    path = _temp_audio(audio)
    try:
        model = _load_whisper()
        _cache.whisper_used = time.monotonic()
        return _read_segments(model, path)
    except Exception:
        logger.debug("faster-whisper did not hear the utterance", exc_info=True)
        return ""
    finally:
        _drop(path)


def take_sentences(text: str, *, final: bool = False) -> tuple[list[str], str]:
    """Split spoken text on sentence ends. Leave decimals such as 3.14 whole."""
    ready: list[str] = []
    start = 0
    pattern = re.compile(r"(?<!\d)[.!?][\"']?(?=\s|$)")
    for match in pattern.finditer(text or ""):
        piece = text[start : match.end()].strip()
        if piece:
            ready.append(piece)
        start = match.end()
    rest = text[start:]
    if final and rest.strip():
        ready.append(rest.strip())
        rest = ""
    return ready, rest


def choose_say_voice(listing: str) -> str:
    """Pick the most natural installed macOS voice from ``say -v '?'``."""
    names: list[str] = []
    for line in (listing or "").splitlines():
        bits = line.split()
        if bits:
            names.append(bits[0])
    for preferred in _SAY_PREFERENCE:
        for name in names:
            if name == preferred or name.startswith(preferred):
                return name
    return names[0] if names else ""


def _chosen_say_voice() -> str:
    """List installed macOS voices once. Repeating that costs about half a second."""
    if _cache.say_voice is not None:
        return _cache.say_voice
    listing = ""
    try:
        listed = subprocess.run(
            ["say", "-v", "?"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        listing = listed.stdout or ""
    except Exception:
        listing = ""
    _cache.say_voice = choose_say_voice(listing)
    return _cache.say_voice


def _say_wav(text: str) -> bytes:
    if not text.strip() or shutil.which("say") is None:
        return b""
    voice = _chosen_say_voice()
    path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        command = ["say"]
        if voice:
            command.extend(["-v", voice])
        command.extend(["-o", path, "--data-format=LEI16@24000", text])
        subprocess.run(command, check=False, capture_output=True, timeout=20)
        data = Path(path).read_bytes() if os.path.exists(path) else b""
        return data if data.startswith(b"RIFF") else b""
    except Exception:
        return b""
    finally:
        _drop(path)


def _kokoro_wav(text: str) -> bytes:
    release_idle_models()
    if _cache.kokoro_unavailable:
        return b""
    if _cache.kokoro is None:
        try:
            from openjarvis.speech.kokoro_tts import KokoroTTSBackend
        except ImportError:
            _cache.kokoro_unavailable = True
            return b""
        backend = KokoroTTSBackend()
        try:
            if not backend.health():
                _cache.kokoro_unavailable = True
                return b""
        except Exception:
            _cache.kokoro_unavailable = True
            return b""
        _cache.kokoro = backend
    _cache.kokoro_used = time.monotonic()
    voice = os.environ.get("OPENJARVIS_KOKORO_VOICE", "af_heart").strip() or "af_heart"
    try:
        result = _cache.kokoro.synthesize(text, voice_id=voice)
    except Exception:
        logger.debug("Kokoro did not speak", exc_info=True)
        return b""
    return getattr(result, "audio", b"") or b""


def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Kokoro when the extra is installed, then macOS ``say``, else nothing."""
    spoken = text.strip()
    if not spoken:
        return b"", "none"
    wav = _kokoro_wav(spoken)
    if wav:
        return wav, "speech"
    wav = _say_wav(spoken)
    if wav:
        return wav, "say"
    return b"", "none"


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
        return _scrub(_turn_payload(heard, reply, audio=b"", kind="none"))

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
        return _scrub(_turn_payload("", empty, audio=b"", kind="none"))
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
    audio, kind = synthesize_speech(str(reply.get("content") or ""))
    return _scrub(_turn_payload(heard, reply, audio=audio, kind=kind))


def _turn_payload(
    heard: str,
    reply: dict[str, Any],
    *,
    audio: bytes = b"",
    kind: str = "none",
) -> dict[str, Any]:
    encoded = base64.b64encode(audio).decode("ascii") if audio else ""
    return {
        "transcript": heard,
        "content": str(reply.get("content") or ""),
        "provider": str(reply.get("provider") or ""),
        "model": str(reply.get("model") or ""),
        "label": str(reply.get("label") or ""),
        "note": str(reply.get("note") or ""),
        "needs_credits": bool(reply.get("needs_credits")),
        "audio_base64": encoded,
        "audio_kind": kind if encoded else "none",
        "sample_rate": _SAMPLE_RATE,
        "usd": 0.0,
    }


def _token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(value)


def _remember_usage(
    usage: dict[str, Any],
    payload: dict[str, Any],
    *,
    input_key: str,
    output_key: str,
) -> None:
    incoming = _token_count(payload.get(input_key))
    outgoing = _token_count(payload.get(output_key))
    if incoming is not None:
        usage["input_tokens"] = incoming
    if outgoing is not None:
        usage["output_tokens"] = outgoing


def _iter_cloud_deltas(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    usage: dict[str, Any],
) -> Iterator[str]:
    """Stream one provider. Raise AttemptFailed so the caller can fall back."""
    from openjarvis.chat_switch import PROVIDERS, AttemptFailed

    spec = PROVIDERS[provider]
    key = os.environ.get(str(spec["env"])) or ""
    if not key:
        raise AttemptFailed("Not connected.")
    if provider == "claude":
        stream_cm = httpx.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 220,
                "stream": True,
                "messages": [
                    item for item in messages if item.get("role") != "system"
                ],
            },
            timeout=45.0,
        )
    else:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 220,
            "stream": True,
            "messages": messages,
        }
        if model.startswith("gpt-6"):
            payload["reasoning_effort"] = "none"
        payload["stream_options"] = {"include_usage": True}
        base = (
            "https://api.x.ai/v1"
            if provider == "grok"
            else "https://api.openai.com/v1"
        )
        stream_cm = httpx.stream(
            "POST",
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json=payload,
            timeout=45.0,
        )
    with stream_cm as stream:
        stream.raise_for_status()
        usage["streamed"] = True
        for line in stream.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if provider == "claude":
                if event.get("type") == "message_start":
                    _remember_usage(
                        usage,
                        (event.get("message") or {}).get("usage") or {},
                        input_key="input_tokens",
                        output_key="output_tokens",
                    )
                elif event.get("type") == "message_delta":
                    _remember_usage(
                        usage,
                        event.get("usage") or {},
                        input_key="input_tokens",
                        output_key="output_tokens",
                    )
                if event.get("type") != "content_block_delta":
                    continue
                delta = (event.get("delta") or {}).get("text") or ""
            else:
                _remember_usage(
                    usage,
                    event.get("usage") or {},
                    input_key="prompt_tokens",
                    output_key="completion_tokens",
                )
                choices = event.get("choices") or []
                delta = ""
                if choices:
                    delta = ((choices[0] or {}).get("delta") or {}).get("content") or ""
            if delta:
                yield str(delta)


def iter_answer_deltas(
    messages: list[dict[str, str]],
    provider: str,
    *,
    private: bool = False,
    eli5: bool = False,
    engine: Any = None,
    caller: Any = None,
    usage: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Iterator[str]]:
    """Reply metadata plus text deltas. A stub never calls a live provider."""
    box = usage if usage is not None else {}
    choice = "local" if private else normalize_choice(provider)
    if os.environ.get("OPENJARVIS_VOICE_STUB") == "1":
        reply = {
            "content": f"{label_for(choice, eli5=eli5)} answered.",
            "provider": choice,
            "model": model_for(choice),
            "label": label_for(choice, eli5=eli5),
            "note": "",
            "needs_credits": False,
        }

        def _canned() -> Iterator[str]:
            yield str(reply["content"])

        return reply, _canned()
    if caller is not None or os.environ.get("OPENJARVIS_CHAT_STUB") == "1":
        reply = answer_chat(
            messages,
            choice,
            private=private,
            eli5=eli5,
            engine=engine,
            caller=caller,
        )

        def _whole() -> Iterator[str]:
            text = str(reply.get("content") or "")
            if text:
                yield text

        return reply, _whole()
    from openjarvis.chat_switch import attempt_order

    order = attempt_order(choice, private=private)
    first = order[0] if order else "local"

    def _deltas() -> Iterator[str]:
        if first != "local":
            try:
                yield from _iter_cloud_deltas(
                    first, model_for(first), messages, box
                )
                return
            except Exception:
                box.clear()
                logger.debug("voice stream fell back", exc_info=True)
        reply_now = answer_chat(
            messages,
            choice,
            private=private,
            eli5=eli5,
            engine=engine,
        )
        text = str(reply_now.get("content") or "")
        if text:
            yield text

    meta = {
        "content": "",
        "provider": first,
        "model": model_for(first),
        "label": label_for(first, eli5=eli5),
        "note": "",
        "needs_credits": False,
    }
    return meta, _deltas()


def iter_voice_events(
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
    budget_blocks: Callable[[str], bool] | None = None,
    ledger: Callable[[str, str, str, str, dict[str, Any]], None] | None = None,
) -> Iterator[str]:
    """SSE events: transcript, one sentence at a time, then done."""
    choice = "local" if private else normalize_choice(provider)
    stub = os.environ.get("OPENJARVIS_VOICE_STUB") == "1"
    if stub or (practice and not transcript.strip()):
        heard = "Hello Jarvis."
    else:
        heard = transcript.strip()
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
        yield _sse("done", _turn_payload("", empty, audio=b"", kind="none"))
        return
    history = []
    for item in messages or []:
        if isinstance(item, dict) and str(item.get("content") or "").strip():
            history.append(
                {
                    "role": str(item.get("role") or "user"),
                    "content": str(item.get("content")).strip(),
                }
            )
    history.append({"role": "user", "content": heard})
    if budget_blocks is not None and not private and not stub:
        if budget_blocks(heard):
            private = True
            choice = "local"
    usage: dict[str, Any] = {}
    reply, deltas = iter_answer_deltas(
        history[-12:],
        choice,
        private=private,
        eli5=eli5,
        engine=engine,
        caller=caller,
        usage=usage,
    )
    yield _sse("transcript", {"text": heard})
    buffer = ""
    spoken: list[str] = []
    for delta in deltas:
        buffer += delta
        ready, buffer = take_sentences(buffer)
        for sentence in ready:
            spoken.append(sentence)
            yield _sse("sentence", _sentence_event(sentence, stub=stub))
    if buffer.strip():
        spoken.append(buffer.strip())
        yield _sse("sentence", _sentence_event(buffer.strip(), stub=stub))
    reply = dict(reply)
    reply["content"] = " ".join(spoken)
    if ledger is not None and usage.get("streamed"):
        ledger(
            str(reply.get("provider") or ""),
            str(reply.get("model") or ""),
            heard,
            str(reply.get("content") or ""),
            usage,
        )
    yield _sse(
        "done",
        {
            "transcript": heard,
            "content": reply["content"],
            "provider": reply.get("provider") or "",
            "model": reply.get("model") or "",
            "label": reply.get("label") or "",
            "note": reply.get("note") or "",
            "needs_credits": bool(reply.get("needs_credits")),
        },
    )


def _sentence_event(sentence: str, *, stub: bool) -> dict[str, Any]:
    if stub:
        audio, kind = b"", "none"
    else:
        audio, kind = synthesize_speech(sentence)
    encoded = base64.b64encode(audio).decode("ascii") if audio else ""
    return {
        "text": sentence,
        "audio_base64": encoded,
        "audio_kind": kind if encoded else "none",
        "sample_rate": _SAMPLE_RATE,
    }


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(_scrub(payload))}\n\n"

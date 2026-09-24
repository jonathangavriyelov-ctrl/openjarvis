"""ElevenLabs text-to-speech backend.

Uses the ElevenLabs REST API for expressive, natural-sounding voices.
Requires ELEVENLABS_API_KEY environment variable or config.
"""

from __future__ import annotations

import os
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io"

# "George" — a premade warm British male narrator voice, the closest stock
# ElevenLabs voice to the movie Jarvis.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL = "eleven_multilingual_v2"

# Container -> ElevenLabs ``output_format`` query value.
_OUTPUT_FORMATS = {
    "mp3": "mp3_44100_128",
    "pcm": "pcm_24000",
    "wav": "pcm_24000",
}


def _elevenlabs_synthesize(
    api_key: str,
    text: str,
    voice_id: str,
    model: str = DEFAULT_MODEL,
    output_format: str = "mp3",
    speed: float = 1.0,
    language: str = "",
) -> bytes:
    """Call the ElevenLabs TTS API and return raw audio bytes."""
    body: dict = {"text": text, "model_id": model}
    if speed != 1.0:
        body["voice_settings"] = {"speed": speed}
    if language:
        body["language_code"] = language
    resp = httpx.post(
        f"{_ELEVENLABS_API_BASE}/v1/text-to-speech/{voice_id}",
        params={"output_format": _OUTPUT_FORMATS.get(output_format, "mp3_44100_128")},
        headers={"xi-api-key": api_key, "Accept": "audio/*"},
        json=body,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend — expressive, human-like synthesis."""

    backend_id = "elevenlabs"

    def __init__(
        self, *, api_key: str = "", model: str = "", language: str = ""
    ) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._model = model or os.environ.get("ELEVENLABS_MODEL", DEFAULT_MODEL)
        self._language = language or os.environ.get("ELEVENLABS_LANGUAGE", "")

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
        language: str = "",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        voice_id = voice_id or DEFAULT_VOICE_ID
        # pcm_* responses are raw samples; label them as such so callers do not
        # try to play them as a WAV container.
        fmt = "pcm" if output_format in ("pcm", "wav") else "mp3"

        audio = _elevenlabs_synthesize(
            self._api_key,
            text,
            voice_id=voice_id,
            model=self._model,
            output_format=fmt,
            speed=speed,
            language=language or self._language,
        )

        return TTSResult(
            audio=audio,
            format=fmt,
            voice_id=voice_id,
            sample_rate=24000 if fmt == "pcm" else 44100,
            metadata={"backend": "elevenlabs", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        if not self._api_key:
            return []
        resp = httpx.get(
            f"{_ELEVENLABS_API_BASE}/v1/voices",
            headers={"xi-api-key": self._api_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        return [v["voice_id"] for v in resp.json().get("voices", [])]

    def health(self) -> bool:
        return bool(self._api_key)

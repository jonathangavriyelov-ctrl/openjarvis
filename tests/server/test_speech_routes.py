"""Tests for speech API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.speech._stubs import TranscriptionResult  # noqa: E402


@pytest.fixture
def mock_speech_backend():
    backend = MagicMock()
    backend.backend_id = "mock"
    backend.health.return_value = True
    backend.transcribe.return_value = TranscriptionResult(
        text="Hello world",
        language="en",
        confidence=0.95,
        duration_seconds=1.5,
        segments=[],
    )
    return backend


@pytest.fixture
def app_with_speech(mock_speech_backend):
    from fastapi import FastAPI

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.state.speech_backend = mock_speech_backend
    app.include_router(speech_router)
    return app


@pytest.fixture
def client(app_with_speech):
    return TestClient(app_with_speech)


def test_transcribe_endpoint(client, mock_speech_backend):
    response = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.wav", b"fake audio data", "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "Hello world"
    assert data["language"] == "en"
    assert data["confidence"] == 0.95
    assert data["duration_seconds"] == 1.5


def test_transcribe_endpoint_offloads_backend_work(client, mock_speech_backend):
    expected = TranscriptionResult(
        text="Offloaded",
        language="en",
        confidence=0.9,
        duration_seconds=1.0,
        segments=[],
    )

    with patch(
        "openjarvis.server.api_routes.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = expected
        response = client.post(
            "/v1/speech/transcribe",
            files={"file": ("test.wav", b"fake audio data", "audio/wav")},
        )

    assert response.status_code == 200
    mock_to_thread.assert_awaited_once()
    args, kwargs = mock_to_thread.await_args
    assert args == (mock_speech_backend.transcribe, b"fake audio data")
    assert kwargs == {"format": "wav", "language": None}
    assert response.json()["text"] == "Offloaded"


def test_transcribe_endpoint_surfaces_backend_error(client, mock_speech_backend):
    mock_speech_backend.transcribe.side_effect = RuntimeError("missing cublas64_12.dll")

    response = client.post(
        "/v1/speech/transcribe",
        files={"file": ("test.wav", b"fake audio data", "audio/wav")},
    )

    assert response.status_code == 500
    assert "missing cublas64_12.dll" in response.json()["detail"]


def test_transcribe_no_file(client):
    response = client.post("/v1/speech/transcribe")
    assert response.status_code == 400 or response.status_code == 422


def test_health_endpoint(client):
    response = client.get("/v1/speech/health")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["backend"] == "mock"


def test_health_endpoint_includes_unavailable_reason(client, mock_speech_backend):
    mock_speech_backend.health.return_value = False
    mock_speech_backend.last_error.return_value = (
        "Install with: uv sync --extra desktop"
    )

    response = client.get("/v1/speech/health")

    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    assert data["reason"] == "Install with: uv sync --extra desktop"


def test_health_no_backend():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.state.speech_backend = None
    app.include_router(speech_router)
    client = TestClient(app)

    response = client.get("/v1/speech/health")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False


# ---------------------------------------------------------------------------
# /v1/speech/synthesize
# ---------------------------------------------------------------------------


def _tts_app(tts_backend=None, speech_cfg=None):
    from types import SimpleNamespace

    from fastapi import FastAPI

    from openjarvis.server.api_routes import speech_router

    app = FastAPI()
    app.state.config = SimpleNamespace(speech=speech_cfg)
    if tts_backend is not None:
        app.state.tts_backend = tts_backend
    app.include_router(speech_router)
    return TestClient(app)


def _mock_tts(backend_id="elevenlabs"):
    from openjarvis.speech.tts import TTSResult

    backend = MagicMock()
    backend.backend_id = backend_id
    backend.synthesize.return_value = TTSResult(
        audio=b"mp3-bytes", format="mp3", voice_id="george"
    )
    return backend


def test_synthesize_uses_configured_voice():
    from types import SimpleNamespace

    backend = _mock_tts()
    cfg = SimpleNamespace(tts_backend="elevenlabs", voice_id="george", voice_speed=1.0)
    client = _tts_app(backend, cfg)

    resp = client.post("/v1/speech/synthesize", json={"text": "At your service."})

    assert resp.status_code == 200
    assert resp.content == b"mp3-bytes"
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers["x-tts-backend"] == "elevenlabs"
    backend.synthesize.assert_called_once_with(
        "At your service.", voice_id="george", speed=1.0
    )


def test_synthesize_rejects_empty_text():
    client = _tts_app(_mock_tts())
    resp = client.post("/v1/speech/synthesize", json={"text": "   "})
    assert resp.status_code == 400


def test_synthesize_unknown_backend_is_501():
    client = _tts_app(_mock_tts())
    resp = client.post(
        "/v1/speech/synthesize", json={"text": "Hi", "backend": "does-not-exist"}
    )
    assert resp.status_code == 501


def test_synthesize_other_backend_does_not_get_configured_voice():
    from types import SimpleNamespace

    from openjarvis.core.registry import TTSRegistry

    other = _mock_tts("cartesia")
    TTSRegistry.register_value("cartesia", MagicMock(return_value=other))
    cfg = SimpleNamespace(tts_backend="elevenlabs", voice_id="george", voice_speed=1.0)
    client = _tts_app(_mock_tts(), cfg)

    resp = client.post(
        "/v1/speech/synthesize", json={"text": "Hi", "backend": "cartesia"}
    )

    assert resp.status_code == 200
    other.synthesize.assert_called_once_with("Hi", speed=1.0)

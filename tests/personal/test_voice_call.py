"""Live voice: realtime when it is paid for, local when it is not."""

from __future__ import annotations

import sys

import pytest

from openjarvis.chat_switch import clear_needs_credits, mark_needs_credits
from openjarvis.personal.voice_call import (
    _IDLE_SECONDS,
    _cache,
    choose_say_voice,
    iter_voice_events,
    plan_session,
    release_idle_models,
    run_local_turn,
    take_sentences,
    transcribe_locally,
    voice_cost,
)


@pytest.fixture(autouse=True)
def _quiet_voice(monkeypatch):
    monkeypatch.delenv("OPENJARVIS_VOICE_STUB", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _cache.whisper = None
    _cache.whisper_used = 0.0
    _cache.kokoro = None
    _cache.kokoro_used = 0.0
    _cache.kokoro_unavailable = False
    clear_needs_credits()
    yield
    _cache.whisper = None
    _cache.kokoro = None
    _cache.kokoro_unavailable = False
    clear_needs_credits()


def _mint(provider):
    return {"value": f"eph-{provider}", "expires_at": 99}


def test_grok_with_a_key_mints_a_short_token_and_hides_the_key(monkeypatch):
    secret = "xai-live-secret-value"
    monkeypatch.setenv("XAI_API_KEY", secret)
    plan = plan_session("grok", overall_cap=80, mint=_mint)
    assert plan["mode"] == "realtime"
    assert plan["provider"] == "grok"
    assert plan["model"] == "grok-voice-latest"
    assert plan["protocol"] == "xai-client-secret.eph-grok"
    assert plan["usd_per_minute"] == 0.05
    assert "server_vad" in str(plan["session_update"])
    assert secret not in str(plan)


def test_mint_posts_the_key_as_a_header_and_returns_only_the_token(monkeypatch):
    secret = "xai-header-secret-value"
    monkeypatch.setenv("XAI_API_KEY", secret)
    seen = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"value": "short-lived", "expires_at": 10}

    def post(url, headers=None, json=None, timeout=None):
        del timeout
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        seen["body"] = json
        return _Response()

    monkeypatch.setattr("openjarvis.personal.voice_call.httpx.post", post)
    plan = plan_session("grok", overall_cap=80)
    assert seen["url"].endswith("/realtime/client_secrets")
    assert seen["auth"] == f"Bearer {secret}"
    assert plan["token"] == "short-lived"
    assert secret not in str(plan)
    assert secret not in str(seen["body"])


def test_missing_key_stays_on_this_mac():
    plan = plan_session("grok", overall_cap=80, mint=_mint)
    assert plan["mode"] == "local"
    assert plan["token"] == ""
    assert "Mac" in plan["note"]


def test_claude_writes_the_answer_on_this_mac():
    plan = plan_session("claude", overall_cap=80, mint=_mint)
    assert plan["mode"] == "local"
    assert plan["brain"] == "claude"
    assert "Claude writes the answer" in plan["note"]


def test_private_call_never_mints(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-private-secret")
    called = []
    plan = plan_session(
        "grok",
        private=True,
        overall_cap=80,
        mint=lambda provider: called.append(provider) or _mint(provider),
    )
    assert plan["mode"] == "local"
    assert called == []


def test_tight_budget_stays_local_without_minting(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-budget-secret")
    called = []
    plan = plan_session(
        "grok",
        overall_cap=0.01,
        spent_overall=0,
        mint=lambda provider: called.append(provider) or _mint(provider),
    )
    assert plan["mode"] == "local"
    assert called == []
    assert "budget" in plan["note"].lower()
    assert "xai-budget-secret" not in str(plan)


def test_openai_without_credits_uses_grok_when_that_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret")
    monkeypatch.setenv("XAI_API_KEY", "xai-fallback-secret")
    mark_needs_credits("openai")
    plan = plan_session("openai", overall_cap=80, mint=_mint)
    assert plan["mode"] == "realtime"
    assert plan["provider"] == "grok"
    assert plan["needs_credits"] is True
    assert "needs credits" in plan["note"]
    assert "sk-openai-secret" not in str(plan)


def test_openai_with_credits_uses_its_own_realtime_line(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret")
    plan = plan_session("openai", overall_cap=80, mint=_mint)
    assert plan["mode"] == "realtime"
    assert plan["provider"] == "openai"
    assert plan["usd_per_minute"] == 0.30
    assert plan["protocol"].startswith("openai-insecure-api-key.")


def test_stub_returns_the_local_path_even_with_a_key(monkeypatch):
    monkeypatch.setenv("OPENJARVIS_VOICE_STUB", "1")
    monkeypatch.setenv("XAI_API_KEY", "xai-stub-secret")
    plan = plan_session("grok", overall_cap=80, mint=_mint)
    assert plan["mode"] == "local"
    assert plan["token"] == ""
    assert "xai-stub-secret" not in str(plan)


def test_local_turn_uses_the_transcriber_and_the_selected_brain(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    result = run_local_turn(
        audio=b"not-real-audio",
        provider="claude",
        transcriber=lambda audio: "What time is it?",
        caller=lambda provider, model: f"{provider}:{model} says noon",
    )
    assert result["transcript"] == "What time is it?"
    assert "claude" in result["content"]
    assert result["usd"] == 0
    assert result["audio_kind"] == "none"
    assert result["audio_base64"] == ""


def test_stub_turn_is_canned_and_does_not_call_the_brain(monkeypatch):
    monkeypatch.setenv("OPENJARVIS_VOICE_STUB", "1")
    called = []
    result = run_local_turn(
        practice=True,
        provider="grok",
        caller=lambda provider, model: called.append(provider),
    )
    assert called == []
    assert result["transcript"] == "Hello Jarvis."
    assert result["content"] == "Grok answered."
    assert result["audio_base64"] == ""
    assert result["audio_kind"] == "none"


def test_practice_without_the_stub_asks_the_brain():
    result = run_local_turn(
        practice=True,
        provider="local",
        caller=lambda provider, model: f"{provider} heard you",
    )
    assert result["transcript"] == "Hello Jarvis."
    assert result["content"] == "local heard you"


def test_local_hearing_is_quiet_when_no_transcriber_is_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert transcribe_locally(b"RIFFnot-a-real-wav") == ""


def test_voice_cost_bills_realtime_minutes_only():
    assert voice_cost("realtime", "grok", 60) == pytest.approx(0.05)
    assert voice_cost("realtime", "openai", 60) == pytest.approx(0.30)
    assert voice_cost("local", "grok", 60) == 0
    assert voice_cost("realtime", "grok", 0) == 0


def test_voice_routes_stay_behind_the_password(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.personal.gate import OsGateMiddleware
    from openjarvis.personal.office import PersonalOffice
    from openjarvis.personal.routes import mount_personal

    monkeypatch.setenv("OPENJARVIS_VOICE_STUB", "1")
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj-home"))
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    office = PersonalOffice(tmp_path / "os.db")
    app = FastAPI()
    app.state.personal_office = office
    app.state.engine = None
    app.add_middleware(OsGateMiddleware)
    mount_personal(app)
    client = TestClient(app)
    try:
        denied = client.post(
            "/v1/personal/voice/session", json={"provider": "grok"}
        )
        assert denied.status_code == 401
        denied_stream = client.post(
            "/v1/personal/voice/turn/stream",
            json={"practice": True, "provider": "grok"},
        )
        assert denied_stream.status_code == 401
        denied_metric = client.post(
            "/v1/personal/voice/metrics",
            json={"name": "ttfa_ms", "value": 12},
        )
        assert denied_metric.status_code == 401
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200, setup.text
        allowed = client.post(
            "/v1/personal/voice/session", json={"provider": "grok"}
        )
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        assert body["mode"] == "local"
        assert body["token"] == ""
        early = client.post(
            "/v1/personal/voice/usage",
            json={
                "mode": "realtime",
                "provider": "grok",
                "seconds": 60,
                "connected": False,
            },
        )
        assert early.status_code == 200
        assert early.json()["recorded"] is False
        turn = client.post(
            "/v1/personal/voice/turn",
            json={"practice": True, "provider": "grok"},
        )
        assert turn.status_code == 200, turn.text
        assert turn.json()["transcript"] == "Hello Jarvis."
        assert "Grok answered." in turn.json()["content"]
        stream = client.post(
            "/v1/personal/voice/turn/stream",
            json={"practice": True, "provider": "grok"},
        )
        assert stream.status_code == 200, stream.text
        assert "event: sentence" in stream.text
        assert "Grok answered." in stream.text
        metric = client.post(
            "/v1/personal/voice/metrics",
            json={"name": "ttfa_ms", "value": 12},
        )
        assert metric.status_code == 200
        assert metric.json()["ok"] is True
    finally:
        office.close()


def test_usage_lands_in_the_cost_report(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.personal.gate import OsGateMiddleware
    from openjarvis.personal.office import PersonalOffice
    from openjarvis.personal.routes import mount_personal

    monkeypatch.setenv("XAI_API_KEY", "xai-usage-secret")
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "oj-home"))
    monkeypatch.delenv("OPENJARVIS_API_KEY", raising=False)
    office = PersonalOffice(tmp_path / "os.db")
    world_id = office.store.list_worlds()[0]["id"]
    app = FastAPI()
    app.state.personal_office = office
    app.state.voice_minter = _mint
    app.add_middleware(OsGateMiddleware)
    mount_personal(app)
    client = TestClient(app)
    try:
        setup = client.post(
            "/v1/personal/auth/setup",
            json={"password": "correct-horse"},
        )
        assert setup.status_code == 200, setup.text
        session = client.post(
            "/v1/personal/voice/session",
            json={"provider": "grok", "world_id": world_id},
        )
        assert session.status_code == 200, session.text
        plan = session.json()
        assert plan["mode"] == "realtime"
        assert "xai-usage-secret" not in str(plan)
        usage = client.post(
            "/v1/personal/voice/usage",
            json={
                "mode": "realtime",
                "provider": "grok",
                "seconds": 60,
                "connected": True,
                "world_id": world_id,
                "model": "grok-voice-latest",
            },
        )
        assert usage.status_code == 200, usage.text
        assert usage.json()["amount"] == pytest.approx(0.05)
        report = office.roi.report()
        assert report["overall"]["voice"] == pytest.approx(0.05)
        assert report["overall"]["cost"] >= 0.05
        worlds = {row["id"]: row for row in report["worlds"]}
        assert worlds[world_id]["voice"] == pytest.approx(0.05)
    finally:
        office.close()


def test_session_payload_is_fast_natural_and_private(tmp_path, monkeypatch):
    home = tmp_path / "notes"
    home.mkdir()
    (home / "USER.md").write_text(
        "# Ada Lovelace\nName: Jonathan\nxai-live-secret-value\n"
    )
    (home / "SOUL.md").write_text("Be brief and kind.")
    (home / "MEMORY.md").write_text("detail " * 2000)
    monkeypatch.setenv("OPENJARVIS_HOME", str(home))
    monkeypatch.setenv("XAI_API_KEY", "xai-live-secret-value")
    monkeypatch.setenv("OPENJARVIS_XAI_VOICE", "eve")
    plan = plan_session("grok", overall_cap=80, mint=_mint)
    session = plan["session_update"]["session"]
    assert plan["sample_rate"] == 24000
    assert plan["audio_transport"] == "binary"
    assert session["voice"] == "eve"
    assert session["reasoning"] == {"effort": "none"}
    assert session["turn_detection"]["type"] == "server_vad"
    assert session["turn_detection"]["silence_duration_ms"] == 450
    assert session["turn_detection"]["prefix_padding_ms"] == 300
    audio = session["audio"]
    assert audio["input"]["format"]["rate"] == 24000
    assert audio["input"]["transport"] == "binary"
    assert audio["output"]["transport"] == "binary"
    transcription = audio["input"]["transcription"]
    assert transcription["language_hint"] == "en"
    assert transcription["model"] == "grok-transcribe"
    assert "Jarvis" in transcription["keyterms"]
    assert "Claude" in transcription["keyterms"]
    assert "Ada Lovelace" in transcription["keyterms"]
    instructions = session["instructions"]
    assert "contractions" in instructions
    assert "Ada Lovelace" in instructions
    assert "Be brief and kind." in instructions
    assert len(instructions) <= 3000
    assert "xai-live-secret-value" not in instructions
    assert "xai-live-secret-value" not in str(plan)


def test_take_sentences_keeps_decimals_whole():
    ready, rest = take_sentences("The rate is 3.14 today. Next bit")
    assert ready == ["The rate is 3.14 today."]
    assert rest.strip() == "Next bit"
    ready, rest = take_sentences("Still talking", final=True)
    assert ready == ["Still talking"]
    assert rest == ""


def test_say_voice_prefers_a_natural_installed_voice():
    listing = "Fred en_US\nSamantha en_US\n"
    assert choose_say_voice(listing) == "Samantha"
    assert choose_say_voice("") == ""


def test_stream_emits_sentences_before_the_reply_is_finished():
    events = list(
        iter_voice_events(
            transcript="Hi",
            provider="local",
            caller=lambda provider, model: "First sentence. Second one.",
        )
    )
    body = "".join(events)
    assert "event: transcript" in body
    assert body.index("event: sentence") < body.index("event: done")
    assert "First sentence." in body
    assert "Second one." in body


def test_whisper_stays_warm_with_greedy_english_settings(monkeypatch):
    created: list[dict] = []
    seen: list[dict] = []

    class _Segment:
        def __init__(self, text: str) -> None:
            self.text = text

    class WhisperModel:
        def __init__(self, size, device="cpu", compute_type="int8", cpu_threads=4):
            created.append(
                {
                    "size": size,
                    "device": device,
                    "compute_type": compute_type,
                    "cpu_threads": cpu_threads,
                }
            )

        def transcribe(self, path, **kwargs):
            del path
            seen.append(kwargs)
            return [_Segment("Claude")], None

    module = type(sys)("faster_whisper")
    module.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    assert transcribe_locally(b"RIFFwav") == "Claude"
    assert transcribe_locally(b"RIFFwav") == "Claude"
    assert len(created) == 1
    assert created[0] == {
        "size": "small",
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 4,
    }
    assert seen[0]["beam_size"] == 1
    assert seen[0]["language"] == "en"
    assert seen[0]["condition_on_previous_text"] is False
    assert "Claude" in seen[0]["hotwords"]
    release_idle_models(now=_cache.whisper_used + 10)
    assert _cache.whisper is not None
    release_idle_models(now=_cache.whisper_used + _IDLE_SECONDS)
    assert _cache.whisper is None


def test_kokoro_unloads_after_it_sits_idle():
    closed: list[bool] = []

    class _Backend:
        def close(self) -> None:
            closed.append(True)

    _cache.kokoro = _Backend()
    _cache.kokoro_used = 0
    release_idle_models(now=_IDLE_SECONDS)
    assert _cache.kokoro is None
    assert closed == [True]

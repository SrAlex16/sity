"""Tests for ElevenLabs TTS synthesizer, tts_dispatcher, MIME detection,
and tts_engine setting in VoiceSettings."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session():
    from sqlmodel import SQLModel, Session, create_engine
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


# ---------------------------------------------------------------------------
# elevenlabs_synthesizer
# ---------------------------------------------------------------------------

from app.audio.elevenlabs_synthesizer import synthesize_elevenlabs


def test_synthesize_elevenlabs_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY is not set"):
        synthesize_elevenlabs("hola", "voice123")


def test_synthesize_elevenlabs_http_error_raises(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    import httpx
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    with patch("app.audio.elevenlabs_synthesizer.httpx.post") as mock_post:
        mock_post.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )
        with pytest.raises(RuntimeError, match="ElevenLabs API error 401"):
            synthesize_elevenlabs("hola", "voice123")


def test_synthesize_elevenlabs_empty_response_raises(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    mock_resp = MagicMock()
    mock_resp.content = b""
    mock_resp.raise_for_status = MagicMock()
    with patch("app.audio.elevenlabs_synthesizer.httpx.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="ElevenLabs returned empty audio"):
            synthesize_elevenlabs("hola", "voice123")


def test_synthesize_elevenlabs_success(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    fake_mp3 = b"\xff\xfb" + b"\x00" * 100
    mock_resp = MagicMock()
    mock_resp.content = fake_mp3
    mock_resp.raise_for_status = MagicMock()
    with patch("app.audio.elevenlabs_synthesizer.httpx.post", return_value=mock_resp):
        result = synthesize_elevenlabs("hola mundo", "voice123")
    assert result == fake_mp3


# ---------------------------------------------------------------------------
# tts_dispatcher — routing logic
# ---------------------------------------------------------------------------

from app.audio.tts_dispatcher import (
    _check_and_update_char_limit,
    get_current_char_count,
    synthesize_fragment,
)


def test_dispatcher_guest_always_uses_piper(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    fake_wav = b"RIFF" + b"\x00" * 40

    with _make_session() as session:
        with patch("app.audio.tts_dispatcher._tmp_dir", return_value=tmp_path):
            with patch("app.audio.synthesizer.Path.exists", return_value=True):
                with patch("app.audio.tts_dispatcher._piper_synthesize", return_value=(fake_wav, "wav")) as mock_piper:
                    url, filename = synthesize_fragment(
                        "hola",
                        session=session,
                        session_id="guest:abc123",
                        tts_engine="elevenlabs",
                        persist=False,
                        trace_id="tr001",
                        voice_id="voice123",
                        daily_limit=10000,
                    )
    mock_piper.assert_called_once()
    assert url.startswith("/audio/tts/")
    assert url.endswith(".wav")
    assert filename is None


def test_dispatcher_no_key_falls_back_to_piper(monkeypatch, tmp_path):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    fake_wav = b"RIFF" + b"\x00" * 40

    with _make_session() as session:
        with patch("app.audio.tts_dispatcher._tmp_dir", return_value=tmp_path):
            with patch("app.audio.tts_dispatcher._piper_synthesize", return_value=(fake_wav, "wav")) as mock_piper:
                url, _ = synthesize_fragment(
                    "hola",
                    session=session,
                    session_id="user:123",
                    tts_engine="elevenlabs",
                    persist=False,
                    trace_id="tr002",
                    voice_id="voice123",
                    daily_limit=10000,
                )
    mock_piper.assert_called_once()
    assert url.endswith(".wav")


def test_dispatcher_piper_engine_skips_elevenlabs(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    fake_wav = b"RIFF" + b"\x00" * 40

    with _make_session() as session:
        with patch("app.audio.tts_dispatcher._tmp_dir", return_value=tmp_path):
            with patch("app.audio.tts_dispatcher._piper_synthesize", return_value=(fake_wav, "wav")) as mock_piper:
                with patch("app.audio.elevenlabs_synthesizer.synthesize_elevenlabs") as mock_el:
                    url, _ = synthesize_fragment(
                        "hola",
                        session=session,
                        session_id="user:123",
                        tts_engine="piper",
                        persist=False,
                        trace_id="tr003",
                        voice_id="voice123",
                        daily_limit=10000,
                    )
    mock_el.assert_not_called()
    mock_piper.assert_called_once()


def test_dispatcher_elevenlabs_success_returns_mp3(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    fake_mp3 = b"\xff\xfb" + b"\x00" * 100

    with _make_session() as session:
        with patch("app.audio.tts_dispatcher._tmp_dir", return_value=tmp_path):
            with patch("app.audio.elevenlabs_synthesizer.synthesize_elevenlabs", return_value=fake_mp3):
                url, filename = synthesize_fragment(
                    "hola",
                    session=session,
                    session_id="user:123",
                    tts_engine="elevenlabs",
                    persist=False,
                    trace_id="tr004",
                    voice_id="voice123",
                    daily_limit=10000,
                )
    assert url.startswith("/audio/tts/")
    assert url.endswith(".mp3")
    assert filename is None


def test_dispatcher_char_limit_reached_falls_back_to_piper(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    fake_wav = b"RIFF" + b"\x00" * 40
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from app.memory.models import DailyTtsUsage
    with _make_session() as session:
        # Pre-fill limit exactly at cap
        row = DailyTtsUsage(session_id="user:123", char_count=10000, count_date=today)
        session.add(row)
        session.commit()

        with patch("app.audio.tts_dispatcher._tmp_dir", return_value=tmp_path):
            with patch("app.audio.tts_dispatcher._piper_synthesize", return_value=(fake_wav, "wav")) as mock_piper:
                with patch("app.audio.elevenlabs_synthesizer.synthesize_elevenlabs") as mock_el:
                    url, _ = synthesize_fragment(
                        "hola",
                        session=session,
                        session_id="user:123",
                        tts_engine="elevenlabs",
                        persist=False,
                        trace_id="tr005",
                        voice_id="voice123",
                        daily_limit=10000,
                    )
    mock_el.assert_not_called()
    mock_piper.assert_called_once()
    assert url.endswith(".wav")


def test_dispatcher_char_count_accumulates(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    fake_mp3 = b"\xff\xfb" + b"\x00" * 100

    with _make_session() as session:
        with patch("app.audio.tts_dispatcher._tmp_dir", return_value=tmp_path):
            with patch("app.audio.elevenlabs_synthesizer.synthesize_elevenlabs", return_value=fake_mp3):
                synthesize_fragment(
                    "hola mundo",   # 10 chars
                    session=session,
                    session_id="user:456",
                    tts_engine="elevenlabs",
                    persist=False,
                    trace_id="tr006",
                    voice_id="voice123",
                    daily_limit=10000,
                )
                count = get_current_char_count(session, "user:456")
    assert count == len("hola mundo")


def test_dispatcher_char_count_resets_on_new_day():
    from app.memory.models import DailyTtsUsage
    with _make_session() as session:
        row = DailyTtsUsage(session_id="user:789", char_count=9999, count_date="2000-01-01")
        session.add(row)
        session.commit()
        count = get_current_char_count(session, "user:789")
    assert count == 0  # stale date → treated as 0


def test_check_and_update_accepts_when_under_limit():
    with _make_session() as session:
        ok = _check_and_update_char_limit(session, "user:A", 100, 10000)
    assert ok is True


def test_check_and_update_rejects_when_over_limit():
    from app.memory.models import DailyTtsUsage
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _make_session() as session:
        row = DailyTtsUsage(session_id="user:B", char_count=9950, count_date=today)
        session.add(row)
        session.commit()
        ok = _check_and_update_char_limit(session, "user:B", 100, 10000)
    assert ok is False


def test_check_and_update_zero_limit_means_unlimited():
    with _make_session() as session:
        ok = _check_and_update_char_limit(session, "user:C", 99999, 0)
    assert ok is True


# ---------------------------------------------------------------------------
# tts_engine in VoiceSettings
# ---------------------------------------------------------------------------

from app.settings.schemas import VoiceSettings


def test_tts_engine_default_is_piper():
    s = VoiceSettings()
    assert s.tts_engine == "piper"


def test_tts_engine_elevenlabs_accepted():
    s = VoiceSettings(tts_engine="elevenlabs")
    assert s.tts_engine == "elevenlabs"


def test_tts_engine_per_session_isolated():
    from app.settings.settings_service import SettingsService
    with _make_session() as session:
        svc = SettingsService(session)
        svc.set_voice_settings(VoiceSettings(tts_engine="elevenlabs"), session_id="sess:A")
        svc.set_voice_settings(VoiceSettings(tts_engine="piper"),      session_id="sess:B")
        a = svc.get_voice_settings(session_id="sess:A")
        b = svc.get_voice_settings(session_id="sess:B")
    assert a.tts_engine == "elevenlabs"
    assert b.tts_engine == "piper"


def test_elevenlabs_daily_limit_in_voice_settings():
    from app.settings.settings_service import SettingsService
    with _make_session() as session:
        with patch("app.settings.settings_service.load_default_config",
                   return_value={"audio": {"elevenlabs_daily_char_limit": 5000}}):
            svc = SettingsService(session)
            s = svc.get_voice_settings(session_id="sess:X")
    assert s.elevenlabs_daily_limit == 5000


def test_elevenlabs_chars_used_in_voice_settings():
    from app.settings.settings_service import SettingsService
    from app.memory.models import DailyTtsUsage
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _make_session() as session:
        row = DailyTtsUsage(session_id="sess:Y", char_count=1234, count_date=today)
        session.add(row)
        session.commit()
        with patch("app.settings.settings_service.load_default_config",
                   return_value={"audio": {"elevenlabs_daily_char_limit": 10000}}):
            svc = SettingsService(session)
            s = svc.get_voice_settings(session_id="sess:Y")
    assert s.elevenlabs_chars_used == 1234


# ---------------------------------------------------------------------------
# MIME detection
# ---------------------------------------------------------------------------

from app.api.routes_audio import _detect_mime


def test_detect_mime_wav():
    assert _detect_mime("response.wav") == "audio/wav"


def test_detect_mime_mp3():
    assert _detect_mime("response.mp3") == "audio/mpeg"


def test_detect_mime_unknown_defaults_to_wav():
    assert _detect_mime("response.ogg") == "audio/wav"


def test_detect_mime_case_insensitive():
    assert _detect_mime("RESPONSE.MP3") == "audio/mpeg"
    assert _detect_mime("RESPONSE.WAV") == "audio/wav"

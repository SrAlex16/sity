"""Tests for ElevenLabs voice_id resolution by language.

Covers:
- _resolve_elevenlabs_voice_id: mapping logic for each supported/unsupported language
- synthesize_fragment: falls back to Piper (with log) when language has no ElevenLabs voice
- maybe_attach_tts: passes language_override through correctly
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _resolve_elevenlabs_voice_id
# ---------------------------------------------------------------------------

from app.audio.tts_service import _resolve_elevenlabs_voice_id

_VOICE_IDS = {"en": "voice-en-id", "ja": "voice-ja-id"}


@pytest.mark.parametrize("lang_override,expected", [
    ("en-US", "voice-en-id"),
    ("en-GB", "voice-en-id"),
    ("ja",    "voice-ja-id"),
])
def test_resolve_voice_id_supported_languages(lang_override, expected):
    assert _resolve_elevenlabs_voice_id(_VOICE_IDS, lang_override) == expected


@pytest.mark.parametrize("lang_override", [
    "auto", "es-ES", "es-419", "fr-FR", "de-DE", "pt-BR", "it-IT", "",
])
def test_resolve_voice_id_unsupported_returns_none(lang_override):
    assert _resolve_elevenlabs_voice_id(_VOICE_IDS, lang_override) is None


def test_resolve_voice_id_empty_map_always_returns_none():
    assert _resolve_elevenlabs_voice_id({}, "en-US") is None
    assert _resolve_elevenlabs_voice_id({}, "ja") is None


# ---------------------------------------------------------------------------
# synthesize_fragment: ElevenLabs + unsupported language → Piper fallback + log
# ---------------------------------------------------------------------------

from app.audio.tts_dispatcher import synthesize_fragment


def _make_db_session():
    from sqlmodel import SQLModel, Session, create_engine
    from app.memory.models import DailyTtsUsage
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _piper_result():
    return b"RIFF" + b"\x00" * 4, "wav"


_FAKE_AUDIO_CFG = {
    "audio": {
        "elevenlabs_voice_ids": {"en": "voice-en-id", "ja": "voice-ja-id"},
        "elevenlabs_daily_char_limit": 10000,
        "persist_tts": False,
    }
}


def _run_attach(language_override: str, tts_engine: str = "elevenlabs"):
    """Run _attach_tts_artifacts with mocked dependencies. Returns synthesize_fragment mock."""
    from app.audio.tts_service import _attach_tts_artifacts
    from app.audio.synthesizer import TtsConfig

    fake_cfg = TtsConfig(
        piper_bin="piper", model_path="/fake/model.onnx",
        speaker_id=1, long_response_chars=500,
    )
    voice_settings = MagicMock(
        tts_engine=tts_engine,
        voice_long_response_action="split",
    )
    result_carrier = MagicMock(artifacts=[])

    with _make_db_session() as session:
        with patch("app.audio.synthesizer.load_tts_config", return_value=fake_cfg):
            with patch("app.settings.config_loader.load_default_config", return_value=_FAKE_AUDIO_CFG):
                with patch("app.audio.tts_splitter.split_by_sentences", return_value=["Texto."]):
                    with patch("app.audio.tts_dispatcher.synthesize_fragment",
                               return_value=("/audio/tts/t.wav", None)) as mock_synth:
                        with patch("app.audio.tts_service.write_log") as mock_log:
                            _attach_tts_artifacts(
                                result=result_carrier,
                                text="Texto.",
                                voice_settings=voice_settings,
                                trace_id="test-trace",
                                session=session,
                                session_id="user:1",
                                language_override=language_override,
                            )
                            return mock_synth, mock_log


def test_elevenlabs_unsupported_language_falls_back_to_piper():
    """ElevenLabs engine with es-ES (no voice) must use Piper and log the fallback."""
    mock_synth, mock_log = _run_attach("es-ES")

    call_kwargs = mock_synth.call_args[1]
    assert call_kwargs["tts_engine"] == "piper", (
        f"Expected piper fallback, got tts_engine={call_kwargs['tts_engine']!r}"
    )
    assert any(
        "language_fallback" in str(c) for c in mock_log.call_args_list
    ), "Expected elevenlabs_language_fallback log event"


def test_elevenlabs_supported_language_uses_elevenlabs():
    """ElevenLabs engine with en-US (has voice) must pass tts_engine=elevenlabs and correct voice_id."""
    mock_synth, _ = _run_attach("en-US")

    call_kwargs = mock_synth.call_args[1]
    assert call_kwargs["tts_engine"] == "elevenlabs"
    assert call_kwargs["voice_id"] == "voice-en-id"


def test_elevenlabs_japanese_uses_correct_voice_id():
    """Japanese language must receive the ja voice_id, not the en one."""
    mock_synth, _ = _run_attach("ja")

    call_kwargs = mock_synth.call_args[1]
    assert call_kwargs["tts_engine"] == "elevenlabs"
    assert call_kwargs["voice_id"] == "voice-ja-id"


def test_elevenlabs_auto_language_falls_back_to_piper():
    """language_override='auto' must fall back to Piper (no voice configured for auto)."""
    mock_synth, _ = _run_attach("auto")

    call_kwargs = mock_synth.call_args[1]
    assert call_kwargs["tts_engine"] == "piper"


# ---------------------------------------------------------------------------
# maybe_attach_tts: language_override is forwarded
# ---------------------------------------------------------------------------

def test_maybe_attach_tts_passes_language_override():
    """language_override must reach _attach_tts_artifacts unchanged."""
    from app.audio.tts_service import maybe_attach_tts

    voice_settings = MagicMock(voice_response_mode="always")

    with patch("app.audio.tts_service._attach_tts_artifacts", return_value=(1, None)) as mock_attach:
        with _make_db_session() as session:
            maybe_attach_tts(
                text="Hello.",
                session=session,
                session_id="user:1",
                trace_id="t",
                voice_settings=voice_settings,
                language_override="ja",
            )

    call_kwargs = mock_attach.call_args[1]
    assert call_kwargs["language_override"] == "ja"


def test_maybe_attach_tts_default_language_is_auto():
    """Default language_override must be 'auto' (no language, no ElevenLabs)."""
    from app.audio.tts_service import maybe_attach_tts

    voice_settings = MagicMock(voice_response_mode="always")

    with patch("app.audio.tts_service._attach_tts_artifacts", return_value=(1, None)) as mock_attach:
        with _make_db_session() as session:
            maybe_attach_tts(
                text="Hola.",
                session=session,
                session_id="user:1",
                trace_id="t",
                voice_settings=voice_settings,
            )

    call_kwargs = mock_attach.call_args[1]
    assert call_kwargs["language_override"] == "auto"

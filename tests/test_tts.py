"""Tests for TTS pipeline: synthesizer, text splitter, voice settings, chat integration, Telegram."""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.audio.tts_splitter import split_by_sentences


# ---------------------------------------------------------------------------
# split_by_sentences
# ---------------------------------------------------------------------------

def test_split_short_text_returns_single_fragment():
    result = split_by_sentences("Hola.", 500)
    assert result == ["Hola."]


def test_split_empty_text_returns_empty():
    assert split_by_sentences("", 100) == []
    assert split_by_sentences("   ", 100) == []


def test_split_text_under_limit_returns_single():
    text = "Primera frase. Segunda frase."
    assert split_by_sentences(text, 500) == [text]


def test_split_respects_sentence_boundary():
    text = "Primera frase. Segunda frase. Tercera frase."
    # max_chars forces split after first sentence (14 chars)
    fragments = split_by_sentences(text, 20)
    assert len(fragments) >= 2
    # No fragment should exceed max_chars unless a single sentence is longer
    for f in fragments:
        assert len(f) <= max(20, max(len(s) for s in text.split(". ")))


def test_split_groups_short_sentences():
    # Two short sentences that fit together under the limit
    text = "Sí. No."
    fragments = split_by_sentences(text, 10)
    # "Sí. No." is 7 chars — fits in one fragment
    assert fragments == ["Sí. No."]


def test_split_long_sentence_kept_intact():
    long_sentence = "Esta es una frase extremadamente larga que supera el límite establecido sin duda alguna."
    result = split_by_sentences(long_sentence, 20)
    assert result == [long_sentence]


def test_split_multiple_fragments():
    text = "Frase uno. Frase dos bastante larga. Frase tres."
    fragments = split_by_sentences(text, 15)
    # Should produce at least 2 fragments
    assert len(fragments) >= 2
    joined = " ".join(fragments)
    # All content preserved
    for part in ["Frase uno", "Frase dos", "Frase tres"]:
        assert part in joined


def test_split_exclamation_and_question():
    text = "¿Entiendes? Bien. ¡Perfecto!"
    result = split_by_sentences(text, 500)
    assert result == [text]


# ---------------------------------------------------------------------------
# _should_synthesize (routes_chat helper)
# ---------------------------------------------------------------------------

from app.api.routes_chat import _should_synthesize


@pytest.mark.parametrize("mode,input_mode,expected", [
    ("always",    "text",  True),
    ("always",    "voice", True),
    ("never",     "text",  False),
    ("never",     "voice", False),
    ("symmetric", "voice", True),
    ("symmetric", "text",  False),
])
def test_should_synthesize(mode, input_mode, expected):
    assert _should_synthesize(mode, input_mode) == expected


# ---------------------------------------------------------------------------
# VoiceSettings CRUD via SettingsService (in-memory DB)
# ---------------------------------------------------------------------------

from app.settings.schemas import VoiceSettings


def _make_session():
    from sqlmodel import SQLModel, Session, create_engine
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.memory.models import Setting
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_voice_settings_defaults():
    from app.settings.settings_service import SettingsService
    with _make_session() as session:
        svc = SettingsService(session)
        s = svc.get_voice_settings()
    assert s.voice_response_mode == "symmetric"
    assert s.voice_include_text is True
    assert s.voice_long_response_action == "text_only"


def test_voice_settings_persist_and_reload():
    from app.settings.settings_service import SettingsService
    with _make_session() as session:
        svc = SettingsService(session)
        svc.set_voice_settings(VoiceSettings(
            voice_response_mode="always",
            voice_include_text=False,
            voice_long_response_action="split",
        ))
        result = svc.get_voice_settings()
    assert result.voice_response_mode == "always"
    assert result.voice_include_text is False
    assert result.voice_long_response_action == "split"


# ---------------------------------------------------------------------------
# synthesize_text — mocked piper binary
# ---------------------------------------------------------------------------

from app.audio.synthesizer import TtsConfig, load_tts_config, synthesize_text


# ---------------------------------------------------------------------------
# load_tts_config — default piper_bin resolution
# ---------------------------------------------------------------------------

def test_load_tts_config_default_piper_bin_is_venv_relative():
    """Without tts_piper_bin in config, piper_bin must be Path(sys.executable).parent / 'piper'."""
    expected = str(Path(sys.executable).parent / "piper")
    with patch("app.audio.synthesizer.load_default_config", return_value={"audio": {}}):
        cfg = load_tts_config()
    assert cfg.piper_bin == expected


def test_load_tts_config_explicit_piper_bin_overrides_default():
    """tts_piper_bin in config takes priority over the venv-relative default."""
    with patch("app.audio.synthesizer.load_default_config", return_value={
        "audio": {"tts_piper_bin": "/usr/local/bin/piper"}
    }):
        cfg = load_tts_config()
    assert cfg.piper_bin == "/usr/local/bin/piper"


def _dummy_cfg() -> TtsConfig:
    return TtsConfig(
        piper_bin="piper",
        model_path="/fake/model.onnx",
        speaker_id=1,
        long_response_chars=500,
    )


def test_synthesize_raises_if_model_missing():
    cfg = _dummy_cfg()
    with pytest.raises(RuntimeError, match="TTS model not found"):
        synthesize_text("hola", cfg)


def test_synthesize_raises_on_piper_nonzero_exit():
    cfg = _dummy_cfg()
    import subprocess
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=b"", stderr=b"error msg"
    )
    with patch("app.audio.synthesizer.Path.exists", return_value=True):
        with patch("app.audio.synthesizer.subprocess.run", return_value=completed):
            with pytest.raises(RuntimeError, match="piper exited with code 1"):
                synthesize_text("hola", cfg)


def test_synthesize_returns_wav_bytes():
    cfg = _dummy_cfg()
    fake_wav = b"RIFF" + b"\x00" * 40
    import subprocess, tempfile
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    def mock_run(cmd, input, capture_output, timeout):
        wav_path = cmd[cmd.index("--output_file") + 1]
        import pathlib
        pathlib.Path(wav_path).write_bytes(fake_wav)
        return completed

    with patch("app.audio.synthesizer.Path.exists", return_value=True):
        with patch("app.audio.synthesizer.subprocess.run", side_effect=mock_run):
            result = synthesize_text("hola", cfg)
    assert result == fake_wav


# ---------------------------------------------------------------------------
# Telegram: handle_chat_message sends audio artifacts
# ---------------------------------------------------------------------------

pytest.importorskip("telegram", reason="python-telegram-bot not installed")

from app.messaging.models import TelegramConfig
from app.messaging.gateway import SityGateway
from app.messaging.telegram_adapter import handle_chat_message


def _cfg(allowed: list[int] | None = None) -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        allowed_chat_ids=allowed if allowed is not None else [1],
        rate_limit_per_minute=10,
        log_incoming=False,
        log_outgoing=False,
    )


def run(coro):
    return asyncio.run(coro)


def test_handle_chat_message_sends_audio_artifact():
    reply = AsyncMock()
    reply_audio = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(return_value={
        "text": "Aquí tienes.",
        "ok": True,
        "trace_id": "t1",
        "usage": {"total_tokens": 10},
        "artifacts": [{"type": "audio", "url": "/audio/tts/abc.wav", "filename": "r.wav"}],
    })
    gw.get_voice_settings = AsyncMock(return_value={"voice_include_text": True})
    gw.get_tts_artifact = AsyncMock(return_value=b"RIFF" + b"\x00" * 4)

    run(handle_chat_message(
        cfg=_cfg([1]), gateway=gw, rate_buckets=defaultdict(deque),
        chat_id=1, chat_type="private", text="hola", username="u",
        reply=reply, reply_audio=reply_audio,
    ))

    reply.assert_called_once_with("Aquí tienes.")
    reply_audio.assert_called_once()
    assert reply_audio.call_args[0][0] == b"RIFF" + b"\x00" * 4


def test_handle_chat_message_no_reply_audio_callable_skips_artifacts():
    reply = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(return_value={
        "text": "Texto.",
        "ok": True,
        "usage": {},
        "artifacts": [{"type": "audio", "url": "/audio/tts/x.wav", "filename": "x.wav"}],
    })

    run(handle_chat_message(
        cfg=_cfg([1]), gateway=gw, rate_buckets=defaultdict(deque),
        chat_id=1, chat_type="private", text="hola", username="u",
        reply=reply,
        # reply_audio not passed → defaults to None
    ))

    reply.assert_called_once_with("Texto.")


def test_handle_chat_message_no_audio_artifacts_skips_reply_audio():
    reply = AsyncMock()
    reply_audio = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(return_value={
        "text": "Sin audio.",
        "ok": True,
        "usage": {},
        "artifacts": [],
    })

    run(handle_chat_message(
        cfg=_cfg([1]), gateway=gw, rate_buckets=defaultdict(deque),
        chat_id=1, chat_type="private", text="hola", username="u",
        reply=reply, reply_audio=reply_audio,
    ))

    reply.assert_called_once_with("Sin audio.")
    reply_audio.assert_not_called()


def test_handle_chat_message_artifact_download_error_does_not_crash():
    reply = AsyncMock()
    reply_audio = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(return_value={
        "text": "Texto.",
        "ok": True,
        "usage": {},
        "artifacts": [{"type": "audio", "url": "/audio/tts/x.wav", "filename": "x.wav"}],
    })
    gw.get_voice_settings = AsyncMock(return_value={"voice_include_text": True})
    gw.get_tts_artifact = AsyncMock(side_effect=Exception("network error"))

    run(handle_chat_message(
        cfg=_cfg([1]), gateway=gw, rate_buckets=defaultdict(deque),
        chat_id=1, chat_type="private", text="hola", username="u",
        reply=reply, reply_audio=reply_audio,
    ))

    reply.assert_called_once_with("Texto.")
    reply_audio.assert_not_called()


# ---------------------------------------------------------------------------
# output_mode passed to PromptContextBuilder
# ---------------------------------------------------------------------------

from app.chat.prompt_context import PromptContextBuilder
from app.settings.schemas import VoiceSettings
from unittest.mock import patch, MagicMock


def _make_builder():
    def _get_msgs(session, limit):
        return []
    return PromptContextBuilder(get_recent_messages=_get_msgs)


def _make_dummy_session():
    return MagicMock()


@pytest.mark.parametrize("mode,input_mode,expected_output_mode", [
    ("always",    "text",  "voice"),
    ("always",    "voice", "voice"),
    ("never",     "text",  "text"),
    ("never",     "voice", "text"),
    ("symmetric", "voice", "voice"),
    ("symmetric", "text",  "text"),
])
def test_output_mode_injected_in_prompt_context(mode, input_mode, expected_output_mode):
    """output_mode: voice must appear in user_message_with_history exactly when should_synth is True."""
    from app.api.routes_chat import _should_synthesize
    should_synth = _should_synthesize(mode, input_mode)
    assert should_synth == (expected_output_mode == "voice")

    builder = _make_builder()
    with patch("app.chat.prompt_context._count_total_messages", return_value=0):
        ctx = builder.build(
            session=_make_dummy_session(),
            message="hola",
            history_limit=4,
            input_mode=input_mode,
            output_mode=expected_output_mode,
        )

    if expected_output_mode == "voice":
        assert "[output_mode: voice]" in ctx.user_message_with_history, (
            f"Expected [output_mode: voice] in context for mode={mode!r} input_mode={input_mode!r}"
        )
    else:
        assert "[output_mode: voice]" not in ctx.user_message_with_history, (
            f"[output_mode: voice] must NOT appear for mode={mode!r} input_mode={input_mode!r}"
        )


def test_output_mode_text_does_not_inject_tag():
    builder = _make_builder()
    with patch("app.chat.prompt_context._count_total_messages", return_value=0):
        ctx = builder.build(
            session=_make_dummy_session(),
            message="hola",
            history_limit=4,
            output_mode="text",
        )
    assert "[output_mode: voice]" not in ctx.user_message_with_history


def test_both_input_and_output_voice_both_injected():
    builder = _make_builder()
    with patch("app.chat.prompt_context._count_total_messages", return_value=0):
        ctx = builder.build(
            session=_make_dummy_session(),
            message="hola",
            history_limit=4,
            input_mode="voice",
            output_mode="voice",
        )
    assert "[input_mode: voice]" in ctx.user_message_with_history
    assert "[output_mode: voice]" in ctx.user_message_with_history


# ---------------------------------------------------------------------------
# synthesize_to_tmp — unique filenames per call
# ---------------------------------------------------------------------------

from app.api.routes_audio import synthesize_to_tmp


def test_synthesize_to_tmp_unique_filenames():
    """Two calls in the same turn must produce distinct URL paths."""
    fake_wav = b"RIFF" + b"\x00" * 40
    with patch("app.api.routes_audio.load_tts_config") as mock_cfg:
        mock_cfg.return_value = _dummy_cfg()
        with patch("app.api.routes_audio.synthesize_text", return_value=fake_wav):
            with patch("app.api.routes_audio._TTS_TMP_DIR") as mock_dir:
                mock_path = MagicMock()
                mock_dir.__truediv__ = lambda self, name: mock_path
                mock_dir.mkdir = MagicMock()
                url1 = synthesize_to_tmp("primera frase")
                url2 = synthesize_to_tmp("segunda frase")

    assert url1.startswith("/audio/tts/tts_")
    assert url2.startswith("/audio/tts/tts_")
    assert url1 != url2, "Each call must generate a unique filename"


# ---------------------------------------------------------------------------
# voice_include_text: True/False in handle_chat_message
# ---------------------------------------------------------------------------


def _response_with_audio() -> dict:
    return {
        "text": "Respuesta.",
        "ok": True,
        "usage": {"total_tokens": 5},
        "artifacts": [{"type": "audio", "url": "/audio/tts/abc.wav", "filename": "abc.wav"}],
    }


def test_voice_include_text_true_sends_text_and_audio():
    """voice_include_text=True → both reply (text) and reply_audio are called."""
    reply = AsyncMock()
    reply_audio = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(return_value=_response_with_audio())
    gw.get_voice_settings = AsyncMock(return_value={"voice_include_text": True})
    gw.get_tts_artifact = AsyncMock(return_value=b"RIFF" + b"\x00" * 4)

    run(handle_chat_message(
        cfg=_cfg([1]), gateway=gw, rate_buckets=defaultdict(deque),
        chat_id=1, chat_type="private", text="hola", username="u",
        reply=reply, reply_audio=reply_audio,
    ))

    reply.assert_called_once_with("Respuesta.")
    reply_audio.assert_called_once()


def test_voice_include_text_false_sends_audio_only():
    """voice_include_text=False → reply_audio called, reply (text) NOT called."""
    reply = AsyncMock()
    reply_audio = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(return_value=_response_with_audio())
    gw.get_voice_settings = AsyncMock(return_value={"voice_include_text": False})
    gw.get_tts_artifact = AsyncMock(return_value=b"RIFF" + b"\x00" * 4)

    run(handle_chat_message(
        cfg=_cfg([1]), gateway=gw, rate_buckets=defaultdict(deque),
        chat_id=1, chat_type="private", text="hola", username="u",
        reply=reply, reply_audio=reply_audio,
    ))

    reply.assert_not_called()
    reply_audio.assert_called_once()

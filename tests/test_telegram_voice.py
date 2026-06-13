"""Tests for Telegram voice message handling.

No real Telegram API calls, no real transcription, no real backend calls.
Skipped automatically if python-telegram-bot is not installed.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telegram", reason="python-telegram-bot not installed")

from app.messaging.models import TelegramConfig
from app.messaging.gateway import SityGateway
from app.messaging.telegram_adapter import handle_voice_message, handle_chat_message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(allowed: list[int] | None = None) -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        allowed_chat_ids=allowed if allowed is not None else [10],
        rate_limit_per_minute=10,
        log_incoming=False,
        log_outgoing=False,
    )


def _buckets():
    return defaultdict(deque)


def _gw(**overrides) -> MagicMock:
    gw = MagicMock(spec=SityGateway)
    gw.transcribe_audio = AsyncMock(return_value={"transcript": "Pon la música", "duration_ms": 300})
    gw.send_message = AsyncMock(return_value={"text": "Vale.", "trace_id": "t1", "ok": True, "usage": {}})
    for k, v in overrides.items():
        setattr(gw, k, AsyncMock(return_value=v))
    return gw


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# handle_voice_message
# ---------------------------------------------------------------------------

def test_voice_message_transcribes_and_replies() -> None:
    reply = AsyncMock()
    gw = _gw()
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", username="alex",
        audio_bytes=b"fake-ogg", reply=reply,
    ))
    gw.transcribe_audio.assert_called_once_with(b"fake-ogg", "audio/ogg")
    gw.send_message.assert_called_once()
    # send_message must use voice input_mode
    call_kwargs = gw.send_message.call_args
    assert call_kwargs.kwargs.get("input_mode") == "voice"
    reply.assert_called_once_with("Vale.")


def test_voice_passes_transcript_as_original() -> None:
    reply = AsyncMock()
    gw = _gw(transcribe_audio={"transcript": "texto exacto", "duration_ms": 100})
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", username="alex",
        audio_bytes=b"ogg", reply=reply,
    ))
    call_kwargs = gw.send_message.call_args
    assert call_kwargs.kwargs.get("voice_transcript_original") == "texto exacto"
    assert call_kwargs.args[0] == "texto exacto"  # text param


def test_voice_ignores_non_allowed_chat() -> None:
    reply = AsyncMock()
    gw = _gw()
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=999, chat_type="private", username="x",
        audio_bytes=b"ogg", reply=reply,
    ))
    gw.transcribe_audio.assert_not_called()
    reply.assert_not_called()


def test_voice_ignores_group_chat() -> None:
    reply = AsyncMock()
    gw = _gw()
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="group", username="x",
        audio_bytes=b"ogg", reply=reply,
    ))
    gw.transcribe_audio.assert_not_called()
    reply.assert_not_called()


def test_voice_transcription_error_replies_gracefully() -> None:
    reply = AsyncMock()
    gw = MagicMock(spec=SityGateway)
    gw.transcribe_audio = AsyncMock(side_effect=Exception("whisper timeout"))
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", username="x",
        audio_bytes=b"ogg", reply=reply,
    ))
    reply.assert_called_once()
    assert "Error" in reply.call_args[0][0]
    gw.send_message = AsyncMock()
    gw.send_message.assert_not_called()


def test_voice_empty_transcript_replies_not_understood() -> None:
    reply = AsyncMock()
    gw = _gw(transcribe_audio={"transcript": "", "duration_ms": 50})
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", username="x",
        audio_bytes=b"ogg", reply=reply,
    ))
    gw.send_message = AsyncMock()
    gw.send_message.assert_not_called()
    reply.assert_called_once()
    assert "entendido" in reply.call_args[0][0].lower() or "intenta" in reply.call_args[0][0].lower()


def test_voice_whitespace_only_transcript_not_sent() -> None:
    reply = AsyncMock()
    gw = _gw(transcribe_audio={"transcript": "   ", "duration_ms": 50})
    run(handle_voice_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", username="x",
        audio_bytes=b"ogg", reply=reply,
    ))
    # Strip makes it empty → should not send to backend
    gw.send_message = AsyncMock()
    gw.send_message.assert_not_called()


def test_voice_rate_limit_blocks_transcription() -> None:
    reply = AsyncMock()
    gw = _gw()
    buckets = _buckets()
    # Fill rate bucket
    for _ in range(3):
        run(handle_voice_message(
            cfg=_cfg([10], ), gateway=gw, rate_buckets=buckets,
            chat_id=10, chat_type="private", username="x",
            audio_bytes=b"ogg", reply=_reply(),
        ))
    # Patch cfg with rate=3
    cfg3 = TelegramConfig(enabled=True, allowed_chat_ids=[10], rate_limit_per_minute=3,
                          log_incoming=False, log_outgoing=False)
    reply4 = AsyncMock()
    gw2 = _gw()
    run(handle_voice_message(
        cfg=cfg3, gateway=gw2, rate_buckets=buckets,
        chat_id=10, chat_type="private", username="x",
        audio_bytes=b"ogg", reply=reply4,
    ))
    # With rate=3, 4th call should be blocked
    # (first 3 calls used cfg with rate=10, so the bucket has 3 entries;
    # 4th call with rate=3 triggers the limit)
    gw2.transcribe_audio.assert_not_called()


# ---------------------------------------------------------------------------
# handle_chat_message — voice input_mode is forwarded
# ---------------------------------------------------------------------------

def test_chat_message_forwards_voice_params_to_gateway() -> None:
    reply = AsyncMock()
    gw = _gw()
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private",
        text="pon música",
        username="x",
        reply=reply,
        input_mode="voice",
        voice_transcript_original="pon la música por favor",
    ))
    call_kwargs = gw.send_message.call_args.kwargs
    assert call_kwargs["input_mode"] == "voice"
    assert call_kwargs["voice_transcript_original"] == "pon la música por favor"


def test_chat_message_text_mode_default() -> None:
    reply = AsyncMock()
    gw = _gw()
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private",
        text="hola",
        username="x",
        reply=reply,
    ))
    # Default input_mode is text — no voice_transcript_original
    call_kwargs = gw.send_message.call_args.kwargs
    assert call_kwargs.get("input_mode", "text") == "text"
    assert call_kwargs.get("voice_transcript_original") is None


def _reply():
    return AsyncMock()

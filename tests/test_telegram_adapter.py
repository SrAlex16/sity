"""Tests for Telegram adapter handler logic.

Tests call the pure async handler functions directly (no Telegram types needed).
Skipped automatically if python-telegram-bot is not installed.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("telegram", reason="python-telegram-bot not installed")

from app.messaging.models import TelegramConfig
from app.messaging.gateway import SityGateway
from app.messaging.telegram_adapter import (
    handle_chat_message,
    handle_defaults,
    handle_help,
    handle_preset,
    handle_start,
    handle_status,
    _HELP_TEXT,
    _RATE_LIMIT_MSG,
    _VALID_PRESETS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(allowed: list[int] | None = None, rate: int = 10) -> TelegramConfig:
    return TelegramConfig(
        enabled=True,
        allowed_chat_ids=allowed if allowed is not None else [100],
        rate_limit_per_minute=rate,
        log_incoming=False,
        log_outgoing=False,
    )


def _mock_gateway(**method_returns) -> MagicMock:
    gw = MagicMock(spec=SityGateway)
    for name, value in method_returns.items():
        setattr(gw, name, AsyncMock(return_value=value))
    return gw


def _reply() -> AsyncMock:
    return AsyncMock()


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# handle_start
# ---------------------------------------------------------------------------

def test_start_sends_greeting_to_allowed_chat() -> None:
    reply = _reply()
    run(handle_start(cfg=_cfg([100]), chat_id=100, chat_type="private", reply=reply))
    reply.assert_called_once()
    assert "Sity" in reply.call_args[0][0]


def test_start_ignores_non_allowed_chat_id() -> None:
    reply = _reply()
    run(handle_start(cfg=_cfg([100]), chat_id=999, chat_type="private", reply=reply))
    reply.assert_not_called()


def test_start_ignores_group_messages() -> None:
    reply = _reply()
    run(handle_start(cfg=_cfg([100]), chat_id=100, chat_type="group", reply=reply))
    reply.assert_not_called()


# ---------------------------------------------------------------------------
# handle_help
# ---------------------------------------------------------------------------

def test_help_returns_command_list() -> None:
    reply = _reply()
    run(handle_help(cfg=_cfg([42]), chat_id=42, chat_type="private", reply=reply))
    reply.assert_called_once()
    text = reply.call_args[0][0]
    for cmd in ("/start", "/help", "/preset", "/defaults", "/status"):
        assert cmd in text, f"{cmd} missing from /help output"


def test_help_ignores_unknown_chat() -> None:
    reply = _reply()
    run(handle_help(cfg=_cfg([42]), chat_id=999, chat_type="private", reply=reply))
    reply.assert_not_called()


# ---------------------------------------------------------------------------
# handle_preset
# ---------------------------------------------------------------------------

def test_preset_normal_use_calls_set_preset() -> None:
    reply = _reply()
    gw = _mock_gateway(set_preset={"ok": True, "dataset_source": "normal_use"})
    run(handle_preset(
        cfg=_cfg([7]), gateway=gw, chat_id=7, chat_type="private",
        args=["normal_use"], reply=reply,
    ))
    gw.set_preset.assert_called_once_with("normal_use")
    reply.assert_called_once()
    assert "normal_use" in reply.call_args[0][0]


def test_preset_demo_session_activates_demo() -> None:
    reply = _reply()
    gw = _mock_gateway(set_preset={"ok": True})
    run(handle_preset(
        cfg=_cfg([7]), gateway=gw, chat_id=7, chat_type="private",
        args=["demo_session"], reply=reply,
    ))
    gw.set_preset.assert_called_once_with("demo_session")


def test_preset_invalid_source_shows_usage() -> None:
    reply = _reply()
    gw = _mock_gateway()
    run(handle_preset(
        cfg=_cfg([7]), gateway=gw, chat_id=7, chat_type="private",
        args=["invalid_mode"], reply=reply,
    ))
    gw.set_preset.assert_not_called()
    reply.assert_called_once()
    text = reply.call_args[0][0]
    assert "Uso:" in text or "válidos" in text


def test_preset_no_args_shows_usage() -> None:
    reply = _reply()
    gw = _mock_gateway()
    run(handle_preset(
        cfg=_cfg([7]), gateway=gw, chat_id=7, chat_type="private",
        args=[], reply=reply,
    ))
    gw.set_preset.assert_not_called()
    reply.assert_called_once()


def test_preset_ignores_non_allowed_chat() -> None:
    reply = _reply()
    gw = _mock_gateway()
    run(handle_preset(
        cfg=_cfg([7]), gateway=gw, chat_id=999, chat_type="private",
        args=["normal_use"], reply=reply,
    ))
    gw.set_preset.assert_not_called()
    reply.assert_not_called()


def test_preset_backend_error_replies_gracefully() -> None:
    reply = _reply()
    gw = MagicMock(spec=SityGateway)
    gw.set_preset = AsyncMock(side_effect=Exception("connection refused"))
    run(handle_preset(
        cfg=_cfg([7]), gateway=gw, chat_id=7, chat_type="private",
        args=["debug_test"], reply=reply,
    ))
    reply.assert_called_once()
    assert "Error" in reply.call_args[0][0]


def test_valid_presets_set_is_complete() -> None:
    assert _VALID_PRESETS == {"normal_use", "demo_session", "debug_test"}


# ---------------------------------------------------------------------------
# handle_defaults
# ---------------------------------------------------------------------------

def test_defaults_calls_reset_personality() -> None:
    reply = _reply()
    gw = _mock_gateway(reset_personality={"sarcasm_level": 0.25})
    run(handle_defaults(cfg=_cfg([5]), gateway=gw, chat_id=5, chat_type="private", reply=reply))
    gw.reset_personality.assert_called_once()
    reply.assert_called_once()


def test_defaults_ignores_non_allowed_chat() -> None:
    reply = _reply()
    gw = _mock_gateway(reset_personality={})
    run(handle_defaults(cfg=_cfg([5]), gateway=gw, chat_id=999, chat_type="private", reply=reply))
    gw.reset_personality.assert_not_called()
    reply.assert_not_called()


def test_defaults_backend_error_replies_gracefully() -> None:
    reply = _reply()
    gw = MagicMock(spec=SityGateway)
    gw.reset_personality = AsyncMock(side_effect=Exception("timeout"))
    run(handle_defaults(cfg=_cfg([5]), gateway=gw, chat_id=5, chat_type="private", reply=reply))
    reply.assert_called_once()
    assert "Error" in reply.call_args[0][0]


# ---------------------------------------------------------------------------
# handle_status
# ---------------------------------------------------------------------------

def test_status_shows_preset_and_tokens() -> None:
    reply = _reply()
    gw = _mock_gateway(
        get_capture_status={"enabled": True, "dataset_source": "normal_use"},
        get_daily_tokens=3210,
    )
    run(handle_status(cfg=_cfg([3]), gateway=gw, chat_id=3, chat_type="private", reply=reply))
    reply.assert_called_once()
    text = reply.call_args[0][0]
    assert "normal_use" in text
    assert "3" in text  # token count present


def test_status_inactive_preset() -> None:
    reply = _reply()
    gw = _mock_gateway(
        get_capture_status={"enabled": False, "dataset_source": "demo_session"},
        get_daily_tokens=0,
    )
    run(handle_status(cfg=_cfg([3]), gateway=gw, chat_id=3, chat_type="private", reply=reply))
    text = reply.call_args[0][0]
    assert "inactivo" in text


def test_status_ignores_non_allowed_chat() -> None:
    reply = _reply()
    gw = _mock_gateway(get_capture_status={}, get_daily_tokens=0)
    run(handle_status(cfg=_cfg([3]), gateway=gw, chat_id=999, chat_type="private", reply=reply))
    reply.assert_not_called()


# ---------------------------------------------------------------------------
# handle_chat_message
# ---------------------------------------------------------------------------

def _buckets() -> dict[int, deque[float]]:
    return defaultdict(deque)


def test_chat_message_calls_gateway_and_replies() -> None:
    reply = _reply()
    gw = _mock_gateway(send_message={
        "text": "Respuesta de prueba.", "trace_id": "trc_x", "ok": True,
        "usage": {"total_tokens": 20},
    })
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", text="hola", username="user1", reply=reply,
    ))
    gw.send_message.assert_called_once_with("hola", input_mode="text", voice_transcript_original=None)
    reply.assert_called_once_with("Respuesta de prueba.")


def test_chat_message_ignores_non_allowed_chat() -> None:
    reply = _reply()
    gw = _mock_gateway(send_message={"text": "…"})
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=999, chat_type="private", text="hola", username="x", reply=reply,
    ))
    gw.send_message.assert_not_called()
    reply.assert_not_called()


def test_chat_message_ignores_group_type() -> None:
    reply = _reply()
    gw = _mock_gateway(send_message={"text": "…"})
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="group", text="hola", username="x", reply=reply,
    ))
    gw.send_message.assert_not_called()
    reply.assert_not_called()


def test_chat_message_rate_limit_triggers() -> None:
    reply = _reply()
    gw = _mock_gateway(send_message={"text": "ok"})
    buckets = _buckets()
    # Send limit messages to exhaust the bucket
    for _ in range(3):
        run(handle_chat_message(
            cfg=_cfg([10], rate=3), gateway=gw, rate_buckets=buckets,
            chat_id=10, chat_type="private", text="msg", username="x", reply=_reply(),
        ))
    # Next one should be rate limited
    run(handle_chat_message(
        cfg=_cfg([10], rate=3), gateway=gw, rate_buckets=buckets,
        chat_id=10, chat_type="private", text="msg", username="x", reply=reply,
    ))
    reply.assert_called_once_with(_RATE_LIMIT_MSG)
    # 4th call (rate limited) must not reach the backend
    assert gw.send_message.call_count == 3


def test_chat_message_backend_error_replies_gracefully() -> None:
    reply = _reply()
    gw = MagicMock(spec=SityGateway)
    gw.send_message = AsyncMock(side_effect=Exception("backend down"))
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", text="hola", username="x", reply=reply,
    ))
    reply.assert_called_once()
    assert "Error" in reply.call_args[0][0]


def test_chat_message_empty_reply_sends_ellipsis() -> None:
    reply = _reply()
    gw = _mock_gateway(send_message={"text": "", "ok": True, "usage": {}})
    run(handle_chat_message(
        cfg=_cfg([10]), gateway=gw, rate_buckets=_buckets(),
        chat_id=10, chat_type="private", text="ping", username="x", reply=reply,
    ))
    reply.assert_called_once_with("…")

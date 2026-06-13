"""Tests for SityGateway and TelegramConfig helpers.

No real network calls, no real Telegram API.
"""
from __future__ import annotations

import asyncio
import textwrap
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.messaging.models import TelegramConfig, is_rate_limited, load_telegram_config
from app.messaging.gateway import SityGateway


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_response(json_data: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.json.return_value = json_data
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    return r


def _async_http_response(json_data: dict) -> AsyncMock:
    return AsyncMock(return_value=_make_http_response(json_data))


# ---------------------------------------------------------------------------
# load_telegram_config
# ---------------------------------------------------------------------------

def test_load_telegram_config_defaults(tmp_path: Path) -> None:
    cfg_file = tmp_path / "telegram.yaml"
    cfg_file.write_text("telegram:\n  enabled: false\n  allowed_chat_ids: []\n")
    cfg = load_telegram_config(cfg_file)
    assert cfg.enabled is False
    assert cfg.allowed_chat_ids == []
    assert cfg.rate_limit_per_minute == 10
    assert cfg.log_incoming is True
    assert cfg.log_outgoing is True


def test_load_telegram_config_full(tmp_path: Path) -> None:
    cfg_file = tmp_path / "telegram.yaml"
    cfg_file.write_text(textwrap.dedent("""\
        telegram:
          enabled: true
          allowed_chat_ids: [111222333, 444555666]
          rate_limit_per_minute: 5
          log_incoming: false
          log_outgoing: true
    """))
    cfg = load_telegram_config(cfg_file)
    assert cfg.enabled is True
    assert cfg.allowed_chat_ids == [111222333, 444555666]
    assert cfg.rate_limit_per_minute == 5
    assert cfg.log_incoming is False
    assert cfg.log_outgoing is True


def test_load_telegram_config_empty_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "telegram.yaml"
    cfg_file.write_text("")
    cfg = load_telegram_config(cfg_file)
    assert cfg.enabled is False
    assert cfg.allowed_chat_ids == []


# ---------------------------------------------------------------------------
# is_rate_limited
# ---------------------------------------------------------------------------

def test_rate_limit_allows_under_limit() -> None:
    buckets: dict[int, deque[float]] = defaultdict(deque)
    for _ in range(9):
        assert is_rate_limited(buckets, 42, limit=10) is False


def test_rate_limit_blocks_at_limit() -> None:
    buckets: dict[int, deque[float]] = defaultdict(deque)
    for _ in range(10):
        is_rate_limited(buckets, 42, limit=10)
    assert is_rate_limited(buckets, 42, limit=10) is True


def test_rate_limit_independent_per_chat_id() -> None:
    buckets: dict[int, deque[float]] = defaultdict(deque)
    for _ in range(10):
        is_rate_limited(buckets, 111, limit=10)
    # chat_id 222 has its own clean slate
    assert is_rate_limited(buckets, 222, limit=10) is False


def test_rate_limit_evicts_old_timestamps() -> None:
    buckets: dict[int, deque[float]] = defaultdict(deque)
    import time
    # Pre-fill with timestamps older than 60s
    old_ts = time.monotonic() - 61.0
    dq = buckets[99]
    for _ in range(10):
        dq.append(old_ts)
    # Old entries should be evicted and the new call should succeed
    assert is_rate_limited(buckets, 99, limit=10) is False


# ---------------------------------------------------------------------------
# SityGateway
# ---------------------------------------------------------------------------

def test_send_message_returns_response() -> None:
    gateway = SityGateway(base_url="http://localhost:8000")
    payload = {"text": "Hola desde Sity.", "trace_id": "trc_abc123", "ok": True,
               "usage": {"total_tokens": 50}}
    mock_post = _async_http_response(payload)

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = mock_post
            return await gateway.send_message("hola")

    result = asyncio.run(_run())
    assert result["text"] == "Hola desde Sity."
    assert result["trace_id"] == "trc_abc123"


def test_send_message_uses_correct_endpoint() -> None:
    gateway = SityGateway(base_url="http://localhost:8000")
    mock_post = _async_http_response({"text": "ok"})

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = mock_post
            await gateway.send_message("prueba")

    asyncio.run(_run())
    call_args = mock_post.call_args
    assert "/chat/message" in call_args[0][0]
    assert call_args[1]["json"]["message"] == "prueba"


def test_get_capture_status_returns_dict() -> None:
    gateway = SityGateway()
    payload = {"enabled": True, "dataset_source": "demo_session"}
    mock_get = _async_http_response(payload)

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = mock_get
            return await gateway.get_capture_status()

    result = asyncio.run(_run())
    assert result["enabled"] is True
    assert result["dataset_source"] == "demo_session"


def test_set_preset_sends_correct_body() -> None:
    gateway = SityGateway()
    mock_put = _async_http_response({"ok": True})

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.put = mock_put
            await gateway.set_preset("demo_session")

    asyncio.run(_run())
    body = mock_put.call_args[1]["json"]
    assert body["dataset_source"] == "demo_session"
    assert body["enabled"] is True
    assert body["speaker_source"] == "telegram"


def test_reset_personality_posts_to_correct_url() -> None:
    gateway = SityGateway()
    mock_post = _async_http_response({"sarcasm_level": 0.25})

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = mock_post
            return await gateway.reset_personality()

    result = asyncio.run(_run())
    assert "sarcasm_level" in result
    url = mock_post.call_args[0][0]
    assert "/settings/personality/reset" in url


def test_get_daily_tokens_parses_response() -> None:
    gateway = SityGateway()
    mock_get = _async_http_response({"daily_used": 12345, "daily_budget": 50000})

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = mock_get
            return await gateway.get_daily_tokens()

    result = asyncio.run(_run())
    assert result == 12345


def test_get_daily_tokens_defaults_to_zero_on_missing_key() -> None:
    gateway = SityGateway()
    mock_get = _async_http_response({})

    async def _run():
        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = mock_get
            return await gateway.get_daily_tokens()

    result = asyncio.run(_run())
    assert result == 0

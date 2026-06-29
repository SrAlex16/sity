"""Tests for web_search SQLite cache layer."""
from __future__ import annotations

import hashlib
import sqlite3
import time
from unittest.mock import MagicMock, patch

import app.tools.handlers  # noqa: F401 — registers all handlers
from app.tools.registry import ToolContext
from app.tools.handlers.web_search_tools import (
    CACHE_DB,
    TTL_LONG,
    TTL_SHORT,
    _cache_get,
    _cache_set,
    handle_web_search,
)


def _ctx(query: str, is_dynamic: bool = False) -> ToolContext:
    return ToolContext(
        tool_name="web_search",
        tool_input={"query": query, "is_dynamic": is_dynamic},
        trace_id="trc_cache_test",
        executor=MagicMock(),
    )


def _mock_client(html: str = "") -> MagicMock:
    mc = MagicMock()
    mc.__enter__ = MagicMock(return_value=mc)
    mc.__exit__ = MagicMock(return_value=False)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = html
    mc.post.return_value = mock_resp
    return mc


def _clear_cache_entry(query_hash: str) -> None:
    try:
        with sqlite3.connect(CACHE_DB) as conn:
            conn.execute("DELETE FROM search_cache WHERE query_hash = ?", (query_hash,))
    except Exception:
        pass


# ------------------------------------------------------------------
# Unit tests for cache primitives
# ------------------------------------------------------------------

def test_cache_miss_returns_none() -> None:
    assert _cache_get("hash_inexistente_xyz_000") is None


def test_cache_set_and_get() -> None:
    _cache_set("testhash001", "test query", "resultado de prueba", 3600)
    assert _cache_get("testhash001") == "resultado de prueba"


def test_cache_expiry() -> None:
    _cache_set("testhash002", "expiry test", "dato viejo", 1)
    time.sleep(1.1)
    assert _cache_get("testhash002") is None


# ------------------------------------------------------------------
# Integration tests with handler
# ------------------------------------------------------------------

def test_cache_hit_skips_network() -> None:
    """Segunda llamada con la misma query no debe tocar la red."""
    query = "test_cache_integration_xyz_unique_9999"
    query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
    _cache_set(query_hash, query, "resultado cacheado", 3600)

    with patch("app.tools.handlers.web_search_tools.httpx.Client") as mock_client:
        result = handle_web_search(_ctx(query=query, is_dynamic=False))
        mock_client.assert_not_called()

    assert result.raw_result["text"] == "resultado cacheado"
    assert result.ok is True


def test_is_dynamic_true_uses_short_ttl() -> None:
    """is_dynamic=True debe guardar en caché con TTL_SHORT."""
    query = "test_dynamic_ttl_xyz_unique_9999"
    query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
    _clear_cache_entry(query_hash)

    with patch("app.tools.handlers.web_search_tools.httpx.Client",
               return_value=_mock_client()):
        handle_web_search(_ctx(query=query, is_dynamic=True))

    with sqlite3.connect(CACHE_DB) as conn:
        row = conn.execute(
            "SELECT ttl FROM search_cache WHERE query_hash = ?", (query_hash,)
        ).fetchone()
    assert row is not None and row[0] == TTL_SHORT


def test_is_dynamic_false_uses_long_ttl() -> None:
    """is_dynamic=False debe guardar en caché con TTL_LONG."""
    query = "test_static_ttl_xyz_unique_9999"
    query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
    _clear_cache_entry(query_hash)

    with patch("app.tools.handlers.web_search_tools.httpx.Client",
               return_value=_mock_client()):
        handle_web_search(_ctx(query=query, is_dynamic=False))

    with sqlite3.connect(CACHE_DB) as conn:
        row = conn.execute(
            "SELECT ttl FROM search_cache WHERE query_hash = ?", (query_hash,)
        ).fetchone()
    assert row is not None and row[0] == TTL_LONG

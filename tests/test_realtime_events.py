"""Tests for session queue TTL/GC and overflow behaviour in realtime_events.py."""
from __future__ import annotations

import asyncio
import time

import pytest

import app.core.realtime_events as re_mod
from app.core.realtime_events import (
    _SESSION_QUEUE_MAX_SIZE,
    _SESSION_QUEUE_TTL_SECONDS,
    _SessionQueue,
    gc_once,
    publish_session_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sq(*, last_active_offset: float = 0.0, subscribers: int = 0) -> _SessionQueue:
    """Return a _SessionQueue with last_active set to now + offset."""
    sq = _SessionQueue()
    sq.last_active = time.monotonic() + last_active_offset
    sq.subscriber_count = subscribers
    return sq


def _inject(session_id: str, sq: _SessionQueue) -> None:
    re_mod._session_queues[session_id] = sq


def _remove(session_id: str) -> None:
    re_mod._session_queues.pop(session_id, None)


# ---------------------------------------------------------------------------
# GC / TTL tests (synchronous — gc_once() is sync)
# ---------------------------------------------------------------------------

def test_gc_evicts_old_idle_queue():
    sid = "test_gc_old"
    _inject(sid, _make_sq(last_active_offset=-(re_mod._SESSION_QUEUE_TTL_SECONDS + 1)))
    evicted = gc_once()
    assert sid in evicted
    assert sid not in re_mod._session_queues


def test_gc_keeps_recent_queue():
    sid = "test_gc_recent"
    _inject(sid, _make_sq(last_active_offset=0.0))  # just now
    evicted = gc_once()
    assert sid not in evicted
    assert sid in re_mod._session_queues
    _remove(sid)


def test_gc_keeps_queue_with_active_subscriber_even_when_old():
    sid = "test_gc_active_sub"
    sq = _make_sq(
        last_active_offset=-(re_mod._SESSION_QUEUE_TTL_SECONDS + 1),
        subscribers=1,
    )
    _inject(sid, sq)
    evicted = gc_once()
    assert sid not in evicted
    assert sid in re_mod._session_queues
    _remove(sid)


def test_gc_evicts_only_stale_not_fresh():
    stale = "test_gc_stale"
    fresh = "test_gc_fresh"
    _inject(stale, _make_sq(last_active_offset=-(re_mod._SESSION_QUEUE_TTL_SECONDS + 1)))
    _inject(fresh, _make_sq(last_active_offset=0.0))
    evicted = gc_once()
    assert stale in evicted
    assert fresh not in evicted
    assert fresh in re_mod._session_queues
    _remove(fresh)


# ---------------------------------------------------------------------------
# Overflow / max-size tests (async — publish_session_event is async)
# ---------------------------------------------------------------------------

def test_overflow_drops_oldest_event():
    """Queue at capacity: adding one more event drops the oldest."""
    sid = "test_overflow"
    sq = _SessionQueue()
    _inject(sid, sq)

    async def _run():
        for i in range(_SESSION_QUEUE_MAX_SIZE + 1):
            await publish_session_event(sid, {"n": i})
        assert sq.queue.qsize() == _SESSION_QUEUE_MAX_SIZE
        # Oldest (n=0) must have been dropped; first event now n=1
        first = sq.queue.get_nowait()
        assert first == {"n": 1}

    asyncio.run(_run())
    _remove(sid)


def test_overflow_size_never_exceeds_max():
    """Pumping 3× max events never grows the queue past MAX_SIZE."""
    sid = "test_overflow_max"
    sq = _SessionQueue()
    _inject(sid, sq)

    async def _run():
        for i in range(_SESSION_QUEUE_MAX_SIZE * 3):
            await publish_session_event(sid, {"n": i})
        assert sq.queue.qsize() == _SESSION_QUEUE_MAX_SIZE

    asyncio.run(_run())
    _remove(sid)


# ---------------------------------------------------------------------------
# Regression: events buffered while disconnected are delivered on reconnect
# ---------------------------------------------------------------------------

def test_events_buffered_while_no_subscriber():
    """publish_session_event enqueues even when no subscriber is connected.
    The next subscriber should receive the buffered event.
    """
    sid = "test_buffer_reconnect"

    async def _run():
        await publish_session_event(sid, {"type": "proactive_message", "text": "hola"})
        sq = re_mod._session_queues[sid]
        assert sq.queue.qsize() == 1
        event = sq.queue.get_nowait()
        assert event == {"type": "proactive_message", "text": "hola"}

    asyncio.run(_run())
    _remove(sid)


def test_queue_survives_disconnect_and_buffers_new_event():
    """Simulates: subscribe → disconnect → event published → reconnect.
    The event must be in the queue when the next subscriber connects.
    """
    sid = "test_survives_disconnect"
    sq = _SessionQueue()
    sq.subscriber_count = 1   # simulate one active subscriber
    _inject(sid, sq)

    # Simulate subscriber disconnect
    sq.subscriber_count -= 1
    sq.last_active = time.monotonic()

    # Event published while no subscriber
    async def _run():
        await publish_session_event(sid, {"type": "job_done"})
        # Reconnecting subscriber picks up the buffered event
        assert re_mod._session_queues[sid].queue.qsize() == 1

    asyncio.run(_run())
    _remove(sid)


# ---------------------------------------------------------------------------
# cancel endpoint — confirms publish_event_sync is imported (NameError guard)
# ---------------------------------------------------------------------------

def test_cancel_chat_endpoint_no_name_error() -> None:
    """POST /events/chat/{id}/cancel must not raise NameError for publish_event_sync.

    This was a real production risk: publish_event_sync was used in
    cancel_chat_operation() without being imported. mypy caught it; this test
    catches it at runtime so a future import regression fails immediately.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/events/chat/test-turn-id/cancel")
    # 200 OK: cancel_operation returns False for unknown turn, but no NameError
    assert resp.status_code == 200
    assert "ok" in resp.json()

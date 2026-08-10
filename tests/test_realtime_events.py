"""Tests for session queue fan-out, TTL/GC and overflow in realtime_events.py."""
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

def _make_sq(
    *,
    last_active_offset: float = 0.0,
    n_subscriber_queues: int = 0,
) -> _SessionQueue:
    """Return a _SessionQueue with last_active set to now + offset.

    Pass n_subscriber_queues > 0 to simulate active subscribers (each gets an
    individual asyncio.Queue in sq.queues, as subscribe_session() would create).
    """
    sq = _SessionQueue()
    sq.last_active = time.monotonic() + last_active_offset
    for _ in range(n_subscriber_queues):
        sq.queues.append(asyncio.Queue())
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
    _inject(sid, _make_sq(last_active_offset=0.0))
    evicted = gc_once()
    assert sid not in evicted
    assert sid in re_mod._session_queues
    _remove(sid)


def test_gc_keeps_queue_with_active_subscriber_even_when_old():
    """A session with an active subscriber queue is never GC'd, regardless of age."""
    sid = "test_gc_active_sub"
    sq = _make_sq(
        last_active_offset=-(re_mod._SESSION_QUEUE_TTL_SECONDS + 1),
        n_subscriber_queues=1,
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
# Fan-out delivery tests
# ---------------------------------------------------------------------------

def test_fanout_delivers_to_all_subscribers():
    """publish_session_event copies the event to ALL active subscriber queues."""
    sid = "test_fanout_all"
    sq = _SessionQueue()
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    sq.queues.extend([q1, q2])
    _inject(sid, sq)

    async def _run():
        await publish_session_event(sid, {"type": "proactive_message", "text": "hola"})
        assert q1.qsize() == 1
        assert q2.qsize() == 1
        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        assert e1 == {"type": "proactive_message", "text": "hola"}
        assert e1 == e2

    asyncio.run(_run())
    _remove(sid)


def test_fanout_zombie_and_live_subscriber_both_receive_event():
    """Reproduces the 4-connection zombie bug from production logs.

    Prior bug: asyncio.Queue.get() is FIFO — the oldest zombie subscriber would
    consume the event, and the live browser connection would receive nothing.

    After fix: fan-out gives every subscriber its own queue, so zombies consuming
    their copies does not prevent the live subscriber from receiving the event.
    """
    sid = "test_zombie_fanout"
    sq = _SessionQueue()
    zombie_q1: asyncio.Queue = asyncio.Queue()  # oldest (zombie, connected 08:51)
    zombie_q2: asyncio.Queue = asyncio.Queue()  # zombie (connected 08:53)
    zombie_q3: asyncio.Queue = asyncio.Queue()  # zombie (connected 08:57)
    live_q: asyncio.Queue = asyncio.Queue()     # live browser (connected 08:58)
    sq.queues.extend([zombie_q1, zombie_q2, zombie_q3, live_q])
    _inject(sid, sq)

    async def _run():
        await publish_session_event(sid, {"type": "proactive_message", "text": "found it"})
        # All 4 receive the event — zombies will fail when they try to write to
        # their dead sockets, but the live subscriber gets its own copy safely.
        for q in [zombie_q1, zombie_q2, zombie_q3, live_q]:
            assert q.qsize() == 1
        event = live_q.get_nowait()
        assert event == {"type": "proactive_message", "text": "found it"}

    asyncio.run(_run())
    _remove(sid)


def test_disconnect_removes_own_queue_only():
    """When a subscriber disconnects, only its queue is removed; others are unaffected."""
    sid = "test_disconnect_own"
    sq = _SessionQueue()
    q_stays: asyncio.Queue = asyncio.Queue()
    q_leaves: asyncio.Queue = asyncio.Queue()
    sq.queues.extend([q_stays, q_leaves])
    _inject(sid, sq)

    # Simulate the finally block of subscribe_session for q_leaves
    sq.queues.remove(q_leaves)

    async def _run():
        await publish_session_event(sid, {"type": "job_done"})
        assert q_stays.qsize() == 1       # still receives events
        assert q_leaves.qsize() == 0      # no longer receives anything

    asyncio.run(_run())
    _remove(sid)


def test_events_dropped_when_no_subscriber():
    """Fan-out model: events published with no active subscribers are dropped.

    Reconnecting clients call loadHistory() to catch up from DB instead of
    relying on an in-memory buffer (which was susceptible to zombie draining).
    """
    sid = "test_no_sub_drop"

    async def _run():
        await publish_session_event(sid, {"type": "proactive_message", "text": "hola"})
        # No session queue created (publish is a no-op when no subscribers exist)
        assert sid not in re_mod._session_queues

    asyncio.run(_run())
    _remove(sid)


def test_events_dropped_between_disconnect_and_reconnect():
    """Events published after disconnect are dropped; no in-memory buffering.

    This is intentional: the reconnecting client calls loadHistory() on es.onopen
    (via the _reconnecting flag) so it picks up missed events from the DB.
    """
    sid = "test_no_buffer_between"
    sq = _SessionQueue()
    sub_q: asyncio.Queue = asyncio.Queue()
    sq.queues.append(sub_q)
    _inject(sid, sq)

    # Simulate subscriber disconnect (finally block removes its queue)
    sq.queues.remove(sub_q)
    sq.last_active = time.monotonic()

    async def _run():
        await publish_session_event(sid, {"type": "job_done"})
        # No active queues: event is dropped
        assert sq.queues == []
        assert sub_q.qsize() == 0

    asyncio.run(_run())
    _remove(sid)


# ---------------------------------------------------------------------------
# Overflow / max-size tests (per-subscriber queue)
# ---------------------------------------------------------------------------

def test_overflow_drops_oldest_event():
    """Queue at capacity: adding one more event drops the oldest in that subscriber's queue."""
    sid = "test_overflow"
    sq = _SessionQueue()
    sub_q: asyncio.Queue = asyncio.Queue()
    sq.queues.append(sub_q)
    _inject(sid, sq)

    async def _run():
        for i in range(_SESSION_QUEUE_MAX_SIZE + 1):
            await publish_session_event(sid, {"n": i})
        assert sub_q.qsize() == _SESSION_QUEUE_MAX_SIZE
        # Oldest (n=0) must have been dropped; first event now n=1
        first = sub_q.get_nowait()
        assert first == {"n": 1}

    asyncio.run(_run())
    _remove(sid)


def test_overflow_size_never_exceeds_max():
    """Pumping 3× max events never grows any subscriber's queue past MAX_SIZE."""
    sid = "test_overflow_max"
    sq = _SessionQueue()
    sub_q: asyncio.Queue = asyncio.Queue()
    sq.queues.append(sub_q)
    _inject(sid, sq)

    async def _run():
        for i in range(_SESSION_QUEUE_MAX_SIZE * 3):
            await publish_session_event(sid, {"n": i})
        assert sub_q.qsize() == _SESSION_QUEUE_MAX_SIZE

    asyncio.run(_run())
    _remove(sid)


def test_overflow_independent_per_subscriber():
    """Overflow is managed independently for each subscriber queue."""
    sid = "test_overflow_per_sub"
    sq = _SessionQueue()
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    sq.queues.extend([q1, q2])
    _inject(sid, sq)

    async def _run():
        for i in range(_SESSION_QUEUE_MAX_SIZE + 1):
            await publish_session_event(sid, {"n": i})
        assert q1.qsize() == _SESSION_QUEUE_MAX_SIZE
        assert q2.qsize() == _SESSION_QUEUE_MAX_SIZE
        assert q1.get_nowait() == {"n": 1}
        assert q2.get_nowait() == {"n": 1}

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

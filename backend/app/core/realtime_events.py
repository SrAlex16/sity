from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from app.trace.logger import purge_old_logs, write_log

_HEARTBEAT_INTERVAL = 15.0          # seconds between SSE comment heartbeats
_SESSION_QUEUE_MAX_SIZE = 20        # oldest event dropped on overflow (per-subscriber queue)
_SESSION_QUEUE_TTL_SECONDS = 3600   # idle session entries evicted after 1 hour
_SESSION_QUEUE_GC_INTERVAL = 600    # GC runs every 10 minutes

_queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)
_loop: asyncio.AbstractEventLoop | None = None


@dataclass
class _SessionQueue:
    # Fan-out model: each call to subscribe_session() owns one asyncio.Queue.
    # publish_session_event copies every event to ALL active queues, so every
    # live subscriber receives every event regardless of how many other
    # connections (live or zombie) exist on the same session.
    #
    # This eliminates the "zombie consumer" bug where the oldest stale connection
    # would drain asyncio.Queue.get() waiters in FIFO order, consuming events
    # before the live browser connection had a chance to receive them.
    #
    # Trade-off: events published when no subscriber is active are DROPPED (not
    # buffered). Reconnecting subscribers call loadHistory() to catch up from DB.
    queues: list[asyncio.Queue] = field(default_factory=list)
    last_active: float = field(default_factory=time.monotonic)
    # True = tab in foreground. Default True so the dispatcher doesn't send push
    # notifications spuriously right after SSE connects (before the frontend
    # POSTs /events/visibility with the real state).
    is_visible: bool = True

    @property
    def subscriber_count(self) -> int:
        return len(self.queues)


_session_queues: dict[str, _SessionQueue] = {}


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop
    loop.create_task(_gc_loop())


def new_client_turn_id() -> str:
    return f"turn_{uuid4().hex[:12]}"


async def publish_event(client_turn_id: str, event: dict[str, Any]) -> None:
    if not client_turn_id:
        return
    await _queues[client_turn_id].put(event)


def ensure_queue(turn_id: str) -> None:
    """Pre-create the event queue so events published before the SSE subscriber
    connects are not lost (defaultdict creates the queue on first access)."""
    _ = _queues[turn_id]


def publish_event_sync(client_turn_id: str | None, event: dict[str, Any]) -> None:
    if not client_turn_id or _loop is None or not _loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(publish_event(client_turn_id, event), _loop)


def _get_or_create_session_queue(session_id: str) -> _SessionQueue:
    if session_id not in _session_queues:
        _session_queues[session_id] = _SessionQueue()
    sq = _session_queues[session_id]
    sq.last_active = time.monotonic()
    return sq


async def publish_session_event(session_id: str, event: dict[str, Any]) -> None:
    """Fan-out delivery: copy the event to every active subscriber's individual queue.

    If no subscribers are active the event is dropped. Reconnecting clients call
    loadHistory() to catch up from DB, so no in-memory buffering is needed.
    """
    if not session_id:
        return
    sq = _session_queues.get(session_id)
    if sq is None or not sq.queues:
        return
    sq.last_active = time.monotonic()
    # Snapshot the list so a concurrent subscribe/disconnect can't corrupt iteration.
    for q in list(sq.queues):
        if q.qsize() >= _SESSION_QUEUE_MAX_SIZE:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(event)


def publish_session_event_sync(session_id: str | None, event: dict[str, Any]) -> None:
    if not session_id or _loop is None or not _loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(publish_session_event(session_id, event), _loop)


async def subscribe_session(session_id: str):
    """Persistent SSE channel for a chat session — never terminates on event type.
    Unlike subscribe(), the generator continues across job_done/job_error events;
    the client disconnecting is the only termination signal.

    Each call owns a private asyncio.Queue added to the session's fan-out list.
    The queue is removed when the generator's finally block runs (real disconnect
    or generator cancellation). Zombie connections whose TCP sockets are half-open
    accumulate events in their individual queues (capped at _SESSION_QUEUE_MAX_SIZE)
    until the next heartbeat write fails and the generator terminates normally.
    """
    sq = _get_or_create_session_queue(session_id)
    my_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    sq.queues.append(my_queue)
    write_log(level="INFO", module="realtime_events", event="sse_subscriber_connected",
              payload={"session_id": session_id, "subscriber_count": len(sq.queues)})
    pending: asyncio.Task[dict[str, Any]] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(my_queue.get())
            try:
                event = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=_HEARTBEAT_INTERVAL
                )
                pending = None
            except asyncio.TimeoutError:
                yield None
                continue
            yield event
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        if my_queue in sq.queues:
            sq.queues.remove(my_queue)
        sq.last_active = time.monotonic()
        write_log(level="INFO", module="realtime_events", event="sse_subscriber_disconnected",
                  payload={"session_id": session_id})


def has_active_subscriber(session_id: str) -> bool:
    """Return True if at least one SSE client is connected for this session."""
    sq = _session_queues.get(session_id)
    return sq is not None and bool(sq.queues)


def set_session_visibility(session_id: str, is_visible: bool) -> None:
    """Record whether the tab holding the SSE connection is in the foreground.

    Called from POST /events/visibility. No-op if no session queue exists yet
    (e.g. POST arrives before the SSE connection is established).
    """
    sq = _session_queues.get(session_id)
    if sq is not None:
        sq.is_visible = is_visible


def get_subscriber_state(session_id: str) -> Literal["visible", "background", "none"]:
    """Return the visibility state of the SSE subscriber for this session.

    "visible"    — tab connected and in foreground (deliver via SSE only)
    "background" — tab connected but not visible (deliver via SSE + push)
    "none"       — no SSE connection (deliver via push or pending)
    """
    sq = _session_queues.get(session_id)
    if sq is None or not sq.queues:
        return "none"
    return "visible" if sq.is_visible else "background"


def gc_once() -> list[str]:
    """Evict one round of dead session queues. Exposed for testing."""
    now = time.monotonic()
    dead = [
        sid for sid, sq in list(_session_queues.items())
        if not sq.queues and (now - sq.last_active) > _SESSION_QUEUE_TTL_SECONDS
    ]
    for sid in dead:
        _session_queues.pop(sid, None)
    if dead:
        write_log(level="INFO", module="realtime_events", event="session_queues_gc",
                  payload={"evicted": dead})
    return dead


async def _gc_loop() -> None:
    while True:
        await asyncio.sleep(_SESSION_QUEUE_GC_INTERVAL)
        gc_once()
        deleted = purge_old_logs()
        if deleted:
            write_log(level="INFO", module="realtime_events", event="log_files_purged",
                      payload={"deleted": deleted})


async def subscribe(client_turn_id: str):
    """Yield events from the queue, emitting None as a heartbeat sentinel every
    _HEARTBEAT_INTERVAL seconds when idle. The caller must convert None to an
    SSE comment (': heartbeat\\n\\n') before writing to the wire."""
    queue = _queues[client_turn_id]
    # Keep a single pending Task so shield() can be reused across timeouts
    # without spawning extra queue.get() coroutines.
    pending: asyncio.Task[dict[str, Any]] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(queue.get())
            try:
                event = await asyncio.wait_for(
                    asyncio.shield(pending), timeout=_HEARTBEAT_INTERVAL
                )
                pending = None  # consumed; next iteration creates a fresh task
            except asyncio.TimeoutError:
                yield None  # heartbeat sentinel — caller emits ": heartbeat\n\n"
                continue
            yield event
            if event.get("type") in {"done", "error"}:
                break
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        _queues.pop(client_turn_id, None)

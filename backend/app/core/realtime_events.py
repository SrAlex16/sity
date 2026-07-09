from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.trace.logger import write_log

_HEARTBEAT_INTERVAL = 15.0          # seconds between SSE comment heartbeats
_SESSION_QUEUE_MAX_SIZE = 20        # oldest event dropped on overflow
_SESSION_QUEUE_TTL_SECONDS = 3600   # idle queues evicted after 1 hour
_SESSION_QUEUE_GC_INTERVAL = 600    # GC runs every 10 minutes

_queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)
_loop: asyncio.AbstractEventLoop | None = None


@dataclass
class _SessionQueue:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    last_active: float = field(default_factory=time.monotonic)
    subscriber_count: int = 0


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
    if not session_id:
        return
    sq = _get_or_create_session_queue(session_id)
    # Drop the oldest event when at capacity so a runaway job can't exhaust RAM.
    if sq.queue.qsize() >= _SESSION_QUEUE_MAX_SIZE:
        try:
            sq.queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    await sq.queue.put(event)


def publish_session_event_sync(session_id: str | None, event: dict[str, Any]) -> None:
    if not session_id or _loop is None or not _loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(publish_session_event(session_id, event), _loop)


async def subscribe_session(session_id: str):
    """Persistent SSE channel for a chat session — never terminates on event type.
    Unlike subscribe(), the generator continues across job_done/job_error events;
    the client disconnecting is the only termination signal.

    The underlying queue is kept alive after disconnect so events published while
    no subscriber is connected are delivered when the subscriber reconnects.
    Idle queues are evicted by _gc_loop() after _SESSION_QUEUE_TTL_SECONDS.
    """
    sq = _get_or_create_session_queue(session_id)
    sq.subscriber_count += 1
    write_log(level="INFO", module="realtime_events", event="sse_subscriber_connected",
              payload={"session_id": session_id, "qsize": sq.queue.qsize()})
    pending: asyncio.Task[dict[str, Any]] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(sq.queue.get())
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
        sq.subscriber_count -= 1
        sq.last_active = time.monotonic()
        write_log(level="INFO", module="realtime_events", event="sse_subscriber_disconnected",
                  payload={"session_id": session_id})


def gc_once() -> list[str]:
    """Evict one round of dead session queues. Exposed for testing."""
    now = time.monotonic()
    dead = [
        sid for sid, sq in list(_session_queues.items())
        if sq.subscriber_count == 0 and (now - sq.last_active) > _SESSION_QUEUE_TTL_SECONDS
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

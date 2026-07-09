from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from uuid import uuid4

_HEARTBEAT_INTERVAL = 15.0  # seconds between SSE comment heartbeats

_queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)
_session_queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


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


async def publish_session_event(session_id: str, event: dict[str, Any]) -> None:
    if not session_id:
        return
    await _session_queues[session_id].put(event)


def publish_session_event_sync(session_id: str | None, event: dict[str, Any]) -> None:
    if not session_id or _loop is None or not _loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(publish_session_event(session_id, event), _loop)


async def subscribe_session(session_id: str):
    """Persistent SSE channel for a chat session — never terminates on event type.
    Unlike subscribe(), the generator continues across job_done/job_error events;
    the client disconnecting is the only termination signal.
    """
    queue = _session_queues[session_id]
    pending: asyncio.Task[dict[str, Any]] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(queue.get())
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
        _session_queues.pop(session_id, None)


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

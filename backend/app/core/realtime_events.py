from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from uuid import uuid4


_queues: dict[str, asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)
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


def publish_event_sync(client_turn_id: str | None, event: dict[str, Any]) -> None:
    if not client_turn_id or _loop is None:
        return
    asyncio.run_coroutine_threadsafe(publish_event(client_turn_id, event), _loop)


async def subscribe(client_turn_id: str):
    queue = _queues[client_turn_id]

    try:
        while True:
            event = await queue.get()
            yield event

            if event.get("type") in {"done", "error"}:
                break
    finally:
        _queues.pop(client_turn_id, None)

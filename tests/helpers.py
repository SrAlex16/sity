"""Shared test utilities — not pytest fixtures, just plain functions."""
from __future__ import annotations

import json
from typing import Any


def chat_post_and_drain(client: Any, message: str, **kwargs: Any) -> dict[str, Any]:
    """POST /chat/message (202) then drain /chat/stream until done.

    Returns the response-data dict from the 'response' SSE event,
    or {} if no response event was emitted (e.g. error path).
    """
    resp = client.post("/chat/message", json={"message": message, **kwargs})
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    turn_id = resp.json()["turn_id"]
    return drain_chat_stream(client, turn_id)


def drain_chat_stream(client: Any, turn_id: str) -> dict[str, Any]:
    """Drain /chat/stream/{turn_id} and return the response-data dict."""
    final: dict[str, Any] = {}
    with client.stream("GET", f"/chat/stream/{turn_id}") as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev: dict[str, Any] = json.loads(line[6:])
            except Exception:
                continue
            if ev.get("type") == "response":
                final = ev.get("data") or {}
            if ev.get("type") in ("done", "error", "cancelled"):
                break
    return final

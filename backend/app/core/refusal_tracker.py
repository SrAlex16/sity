from __future__ import annotations

from typing import Any


_last_refusal: dict[str, Any] | None = None


def set_last_refusal(*, user_message: str, assistant_message: str, trace_id: str) -> None:
    global _last_refusal
    _last_refusal = {
        "user_message": user_message,
        "assistant_message": assistant_message,
        "trace_id": trace_id,
    }


def get_last_refusal() -> dict[str, Any] | None:
    return _last_refusal

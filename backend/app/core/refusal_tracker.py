from __future__ import annotations

from typing import Any


# Keyed by session_id. Stores the IMMEDIATELY preceding refusal for that session.
# Cleared on every non-refusal turn via clear_last_refusal().
_last_refusal_by_session: dict[str, dict[str, Any]] = {}


def set_last_refusal(
    *,
    session_id: str,
    user_message: str,
    assistant_message: str,
    trace_id: str,
) -> None:
    _last_refusal_by_session[session_id] = {
        "user_message": user_message,
        "assistant_message": assistant_message,
        "trace_id": trace_id,
    }


def get_last_refusal(session_id: str = "") -> dict[str, Any] | None:
    if not session_id:
        return None
    return _last_refusal_by_session.get(session_id)


def clear_last_refusal(session_id: str) -> None:
    """Call after every non-refusal turn so the context doesn't bleed into later turns."""
    _last_refusal_by_session.pop(session_id, None)

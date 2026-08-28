from __future__ import annotations

from typing import Any


# Keyed by session_id. Stores the IMMEDIATELY preceding refusal for that session.
# Cleared on every non-refusal turn via clear_last_refusal().
_last_refusal_by_session: dict[str, dict[str, Any]] = {}

# Consecutive structural-refusal counter, keyed by session_id.
# Incremented on each refusal, reset to 0 on any non-refusal turn.
_consecutive_refusals_by_session: dict[str, int] = {}


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


def increment_consecutive_refusals(session_id: str) -> int:
    """Increment the consecutive-refusal counter and return the new count."""
    count = _consecutive_refusals_by_session.get(session_id, 0) + 1
    _consecutive_refusals_by_session[session_id] = count
    return count


def reset_consecutive_refusals(session_id: str) -> None:
    """Reset the consecutive-refusal counter on any non-refusal turn."""
    _consecutive_refusals_by_session.pop(session_id, None)


def get_consecutive_refusals(session_id: str) -> int:
    return _consecutive_refusals_by_session.get(session_id, 0)

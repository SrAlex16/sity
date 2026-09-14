"""Per-session turn queue — serializes concurrent turns from the same session.

Guarantees that when turn B starts _chat_message_inner, turn A's response is
already persisted in the DB.  This prevents the hallucination pattern where B
builds its context without seeing A's reply.

## Supersede logic

A monotonically-increasing version counter per session detects the case where
messages arrive faster than the previous AI call can complete.  When turn B
acquires the lock after waiting, it checks whether a newer turn C arrived
while it was blocked.  If so, B exits without calling the AI — C will handle
it next.

Concretely:

  A arrives → version=1 → acquires lock immediately → processes
  B arrives (while A runs) → version=2 → blocks on lock
  A finishes → releases lock
  B acquires lock → version still 2 → B processes (full context of A's response)

Supersede only fires when two messages arrive faster than lock acquisition,
i.e. sub-100 ms apart in practice:

  A arrives → version=1 → tries to acquire lock
  B arrives (<50 ms) → version=2 → tries to acquire lock
  Whoever acquires first checks version → if version changed, that turn exits.
  The turn with version=2 will eventually hold the lock and process.

## Design constraints

In-memory only.  No Redis, no DB.  Appropriate for single-user Raspberry Pi.
_session_locks grows with unique session IDs but never shrinks — leak is
negligible at this scale (< 100 sessions in a typical lifetime).
"""
from __future__ import annotations

import threading

_global_lock = threading.Lock()
_session_locks: dict[str, threading.Lock] = {}
_session_version: dict[str, int] = {}


def _get_session_lock(session_id: str) -> threading.Lock:
    with _global_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def claim_session_slot(session_id: str) -> int:
    """Register this turn as the latest for the session.

    Returns a monotonic version number.  Pass it to is_superseded() after
    acquiring the session lock.
    """
    with _global_lock:
        v = _session_version.get(session_id, 0) + 1
        _session_version[session_id] = v
        return v


def is_superseded(session_id: str, version: int) -> bool:
    """Return True if a newer turn claimed the session slot after ours."""
    with _global_lock:
        return _session_version.get(session_id, 0) != version


def acquire_session_lock(session_id: str) -> threading.Lock:
    """Acquire the per-session turn lock.  Blocks until the current turn releases it."""
    lock = _get_session_lock(session_id)
    lock.acquire()
    return lock

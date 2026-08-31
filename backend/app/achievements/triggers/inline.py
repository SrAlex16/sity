"""Inline achievement trigger helpers for Paso 2 Fase 2a.

`fire(db, session_id, slug)` is the single entry point used by all hook sites.
It is fire-and-forget: guests are silently skipped, repeats are idempotent,
and exceptions never propagate to callers.
"""
from __future__ import annotations

from typing import Any, Optional


def _user_id_from_session(session_id: str) -> Optional[int]:
    """Extract user_id from a session_id like 'user:123'. Returns None for guests."""
    if not session_id or not session_id.startswith("user:"):
        return None
    try:
        return int(session_id.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


def fire(db: Any, session_id: str, slug: str) -> bool:
    """Unlock achievement `slug` for the authenticated user bound to `session_id`.

    Returns True only on the first unlock for that (user, slug) pair.
    Returns False for guests, unknown slugs, already-unlocked, or any error.
    Never raises.
    """
    user_id = _user_id_from_session(session_id)
    if user_id is None:
        return False
    try:
        from app.achievements.unlock import try_unlock_achievement
        return try_unlock_achievement(db, user_id, slug)
    except Exception:
        return False

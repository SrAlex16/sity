"""Achievement endpoints.

GET /achievements — full catalog with per-user unlock state.
  Guest: all locked, secrets category omitted.
  User/Admin: own unlock state, secrets visible once first secret is unlocked.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.achievements.unlock import get_user_achievements
from app.auth.dependencies import CurrentUser, get_current_user
from app.memory.db import get_session

router = APIRouter(prefix="/achievements", tags=["achievements"])


@router.get("")
def list_achievements(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Return the achievement catalog with unlock state for the current user.

    Guest callers see everything as locked and the secrets category is omitted.
    Authenticated users see their real progress; secrets become visible once they
    unlock at least one.
    """
    user_id = current.user_id  # None for Guest

    items = get_user_achievements(db, user_id)

    unlocked_count = sum(1 for a in items if a["unlocked"])
    total_visible = len(items)

    return {
        "achievements": items,
        "unlocked_count": unlocked_count,
        "total_count": total_visible,
    }

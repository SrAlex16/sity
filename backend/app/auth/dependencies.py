"""FastAPI dependency: resolve the current caller as a real User or a Guest sentinel.

Usage:
    from app.auth.dependencies import CurrentUser, get_current_user

    @router.get("/protected")
    def protected(current: CurrentUser = Depends(get_current_user)):
        if current.is_guest:
            raise HTTPException(status_code=401, detail="Autenticación requerida")
        ...

NOTE (Fase 1): this dependency is not yet wired to /chat/*, /events/*, etc.
It is built and tested in isolation. Wiring to existing routes happens in Fase 3.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from fastapi import Cookie, Depends
from sqlmodel import Session

from app.memory.db import get_session
from app.auth.jwt_utils import decode_token

if TYPE_CHECKING:
    from app.memory.models import User as UserModel


class CurrentUser:
    """Resolved identity for a request — either an authenticated User or a Guest."""

    def __init__(self, user: Optional[UserModel] = None) -> None:
        self.user = user
        self.role: str = user.role if user else "guest"
        self.user_id: Optional[int] = user.id if user else None
        self.is_authenticated: bool = user is not None
        self.is_admin: bool = user is not None and user.role == "admin"
        self.is_guest: bool = user is None


def get_current_user(
    sity_session: Optional[str] = Cookie(default=None),
    session: Session = Depends(get_session),
) -> CurrentUser:
    """Resolve the session cookie to a CurrentUser. Never raises — falls back to Guest."""
    if not sity_session:
        return CurrentUser()

    payload = decode_token(sity_session)
    if not payload:
        return CurrentUser()

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return CurrentUser()

    from app.memory.models import User
    user = session.get(User, user_id)
    if not user or not user.is_active:
        return CurrentUser()

    return CurrentUser(user)

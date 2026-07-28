"""FastAPI dependency: resolve the current caller as a real User or a Guest sentinel.

Usage:
    from app.auth.dependencies import CurrentUser, get_current_user

    @router.get("/protected")
    def protected(current: CurrentUser = Depends(get_current_user)):
        if current.is_guest:
            raise HTTPException(status_code=401, detail="Autenticación requerida")
        ...

Session-id strategy (Fase 2):
  - Authenticated User/Admin: f"user:{user_id}" — stable, deterministic
  - Guest: f"guest:{uuid4().hex}" stored in sity_guest_session httpOnly session cookie
    (no Max-Age → browser-session lifetime, deleted on tab close).
    On first visit the backend generates a new UUID and sets the cookie.
    On subsequent requests the same UUID is read from the cookie — isolation preserved.
    On login/register, routes_auth deletes sity_guest_session so the cookie is gone.
"""

from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from fastapi import Cookie, Depends, Response
from sqlmodel import Session

from app.memory.db import get_session
from app.auth.jwt_utils import decode_token
from app.trace.logger import write_log

if TYPE_CHECKING:
    from app.memory.models import User as UserModel

_GUEST_COOKIE = "sity_guest_session"


def _cookie_secure() -> bool:
    return os.environ.get("SITY_COOKIE_SECURE", "true").lower() == "true"


class CurrentUser:
    """Resolved identity for a request — either an authenticated User or a Guest."""

    def __init__(self, user: Optional[UserModel] = None, session_id: str = "") -> None:
        self.user = user
        self.role: str = user.role if user else "guest"
        self.user_id: Optional[int] = user.id if user else None
        self.session_id: str = session_id
        self.is_authenticated: bool = user is not None
        self.is_admin: bool = user is not None and user.role == "admin"
        self.is_guest: bool = user is None


def get_current_user(
    response: Response,
    sity_session: Optional[str] = Cookie(default=None),
    sity_guest_session: Optional[str] = Cookie(default=None),
    session: Session = Depends(get_session),
) -> CurrentUser:
    """Resolve the session cookie to a CurrentUser. Never raises — falls back to Guest.

    Sets sity_guest_session cookie on first Guest visit (UUID, session-scoped).
    """
    if isinstance(sity_session, str) and sity_session:
        payload = decode_token(sity_session)
        if payload:
            try:
                user_id = int(payload["sub"])
            except (KeyError, ValueError, TypeError):
                pass
            else:
                from app.memory.models import User
                user = session.get(User, user_id)
                if user and user.is_active:
                    return CurrentUser(user=user, session_id=f"user:{user_id}")

    # Guest path — use existing cookie UUID or generate a fresh one
    # isinstance guard: when called directly in tests (not via FastAPI injection),
    # Cookie(default=None) descriptor objects may appear as the default value.
    guest_id = sity_guest_session if isinstance(sity_guest_session, str) else None
    if not guest_id:
        guest_id = f"guest:{uuid4().hex}"
        response.set_cookie(
            key=_GUEST_COOKIE,
            value=guest_id,
            httponly=True,
            secure=_cookie_secure(),
            samesite="lax",
            path="/",
            # No max_age → session cookie (deleted when browser tab closes)
        )
        write_log(
            level="INFO",
            module="auth",
            event="guest_session_created",
            payload={"session_id": guest_id},
        )

    return CurrentUser(session_id=guest_id)

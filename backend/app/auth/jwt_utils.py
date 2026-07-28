"""JWT creation and validation for session cookies.

Secret is read from SITY_JWT_SECRET env var at call time (not at import),
so tests can override it via monkeypatch or conftest env setup.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

_ALGORITHM = "HS256"
_DEFAULT_EXPIRY_HOURS = 72


def _secret() -> str:
    value = os.environ.get("SITY_JWT_SECRET", "")
    if not value:
        from app.trace.logger import write_log
        write_log(
            level="WARN",
            module="auth",
            event="jwt_secret_missing",
            payload={"hint": "Set SITY_JWT_SECRET env var — using insecure default"},
        )
        return "insecure_dev_secret_change_me"
    return value


def create_token(user_id: int, role: str, expiry_hours: int = _DEFAULT_EXPIRY_HOURS) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
    payload = {"sub": str(user_id), "role": role, "exp": exp}
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

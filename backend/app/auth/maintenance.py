"""MaintenanceModeMiddleware — blocks Guest/User with 503 when SITY_MAINTENANCE_MODE=true.

Pure ASGI middleware (not BaseHTTPMiddleware) so SSE streaming responses pass
through untouched when maintenance is off.

Exempt paths (always allowed regardless of role):
  /health      — infrastructure checks
  /auth/login  — Admin must be able to authenticate during maintenance
  /auth/logout — graceful logout during maintenance

Admin detection: reads the sity_session JWT cookie from raw ASGI headers.
If the token is valid and role=="admin", the request passes through.
All other callers (unauthenticated, Guest, User) receive 503.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.core.runtime_config import get_runtime_config

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

_EXEMPT_PATHS = frozenset({"/health", "/auth/login", "/auth/logout"})
_MAINTENANCE_BODY = json.dumps(
    {"detail": "Sity está en mantenimiento. Vuelve más tarde."}
).encode()


def _extract_session_token(cookie_str: str) -> str | None:
    for part in cookie_str.split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == "sity_session":
            return value.strip() or None
    return None


class MaintenanceModeMiddleware:
    def __init__(self, app: "ASGIApp") -> None:
        self._app = app

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if not get_runtime_config().maintenance_mode:
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path in _EXEMPT_PATHS:
            await self._app(scope, receive, send)
            return

        # Try to identify admin via sity_session JWT cookie
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() == b"cookie":
                token = _extract_session_token(raw_value.decode("latin-1"))
                if token:
                    try:
                        from app.auth.jwt_utils import decode_token
                        payload = decode_token(token)
                        if payload and payload.get("role") == "admin":
                            await self._app(scope, receive, send)
                            return
                    except Exception:
                        pass
                break

        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(_MAINTENANCE_BODY)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": _MAINTENANCE_BODY,
            "more_body": False,
        })

"""Route security audit — verify access control for every sensitive endpoint.

Each parametrized case is (method, path, role, expected_access).

  allowed → response must NOT be 401 or 403
  denied  → response MUST be 401 or 403

Roles:
  guest → no sity_session cookie
  user  → authenticated regular user
  admin → authenticated admin user
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import make_admin_token, make_user_token

# ---------------------------------------------------------------------------
# Fixtures — one TestClient per role, reused across all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guest() -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c  # type: ignore[misc]


@pytest.fixture(scope="module")
def user() -> TestClient:
    token = make_user_token()
    with TestClient(app, raise_server_exceptions=False, cookies={"sity_session": token}) as c:
        yield c  # type: ignore[misc]


@pytest.fixture(scope="module")
def admin() -> TestClient:
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=False, cookies={"sity_session": token}) as c:
        yield c  # type: ignore[misc]


@pytest.fixture(scope="module")
def clients(guest: TestClient, user: TestClient, admin: TestClient) -> dict[str, TestClient]:
    return {"guest": guest, "user": user, "admin": admin}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _assert_access(status: int, expected: str, role: str, route: str) -> None:
    if expected == "denied":
        assert status in (401, 403), (
            f"{role} should be DENIED {route} but got HTTP {status}"
        )
    else:
        assert status not in (401, 403), (
            f"{role} should be ALLOWED {route} but got HTTP {status}"
        )


# ---------------------------------------------------------------------------
# Security matrix
#
# Format: (method, path, role, expected_access)
# For routes requiring a body, a minimal stub is sent — auth checks fire before
# body validation so the stub is always enough to trigger the correct status.
# ---------------------------------------------------------------------------

_MATRIX: list[tuple[str, str, str, str]] = [
    # -- Public (all roles allowed) ------------------------------------------
    ("GET",  "/health",                    "guest", "allowed"),
    ("GET",  "/health",                    "user",  "allowed"),
    ("GET",  "/health",                    "admin", "allowed"),

    ("GET",  "/settings/voice",            "guest", "allowed"),
    ("GET",  "/settings/voice",            "user",  "allowed"),
    ("GET",  "/settings/voice",            "admin", "allowed"),

    ("GET",  "/chat/current",              "guest", "allowed"),
    ("GET",  "/chat/current",              "user",  "allowed"),
    ("GET",  "/chat/current",              "admin", "allowed"),

    ("GET",  "/notifications/vapid-public-key", "guest", "allowed"),
    ("GET",  "/notifications/vapid-public-key", "user",  "allowed"),
    ("GET",  "/notifications/vapid-public-key", "admin", "allowed"),

    # -- User + Admin (guest denied) -----------------------------------------
    # /auth/me returns 200 for everyone — it's the "who am I?" endpoint
    ("GET",  "/auth/me",                   "guest", "allowed"),
    ("GET",  "/auth/me",                   "user",  "allowed"),
    ("GET",  "/auth/me",                   "admin", "allowed"),

    ("GET",  "/chat/export",               "guest", "denied"),
    ("GET",  "/chat/export",               "user",  "allowed"),
    ("GET",  "/chat/export",               "admin", "allowed"),

    ("PUT",  "/settings/voice",            "guest", "denied"),
    ("PUT",  "/settings/voice",            "user",  "allowed"),
    ("PUT",  "/settings/voice",            "admin", "allowed"),

    ("GET",  "/memory/semantic-facts",     "guest", "denied"),
    ("GET",  "/memory/semantic-facts",     "user",  "allowed"),
    ("GET",  "/memory/semantic-facts",     "admin", "allowed"),

    ("GET",  "/files",                     "guest", "denied"),
    ("GET",  "/files",                     "user",  "allowed"),
    ("GET",  "/files",                     "admin", "allowed"),

    ("POST", "/notifications/subscribe",   "guest", "denied"),
    ("POST", "/notifications/subscribe",   "user",  "allowed"),
    ("POST", "/notifications/subscribe",   "admin", "allowed"),

    # -- Audio endpoints (added auth 2026-10-08) -----------------------------
    ("POST", "/audio/transcribe",          "guest", "denied"),
    ("POST", "/audio/transcribe",          "user",  "allowed"),
    ("POST", "/audio/transcribe",          "admin", "allowed"),

    ("POST", "/audio/synthesize",          "guest", "denied"),
    ("POST", "/audio/synthesize",          "user",  "allowed"),
    ("POST", "/audio/synthesize",          "admin", "allowed"),

    ("GET",  "/audio/tts/test.wav",        "guest", "denied"),
    ("GET",  "/audio/tts/test.wav",        "user",  "allowed"),
    ("GET",  "/audio/tts/test.wav",        "admin", "allowed"),

    ("GET",  "/audio/stored/test.wav",     "guest", "denied"),
    ("GET",  "/audio/stored/test.wav",     "user",  "allowed"),
    ("GET",  "/audio/stored/test.wav",     "admin", "allowed"),

    # -- Admin-only ----------------------------------------------------------
    ("POST", "/audio/cleanup",             "guest", "denied"),
    ("POST", "/audio/cleanup",             "user",  "denied"),
    ("POST", "/audio/cleanup",             "admin", "allowed"),

    ("GET",  "/captures/camera/test.jpg",  "guest", "denied"),
    ("GET",  "/captures/camera/test.jpg",  "user",  "denied"),
    ("GET",  "/captures/camera/test.jpg",  "admin", "allowed"),

    ("GET",  "/captures/audio/test.wav",   "guest", "denied"),
    ("GET",  "/captures/audio/test.wav",   "user",  "denied"),
    ("GET",  "/captures/audio/test.wav",   "admin", "allowed"),

    ("GET",  "/debug/events/recent",       "guest", "denied"),
    ("GET",  "/debug/events/recent",       "user",  "denied"),
    ("GET",  "/debug/events/recent",       "admin", "allowed"),

    ("GET",  "/bug-reports",               "guest", "denied"),
    ("GET",  "/bug-reports",               "user",  "denied"),
    ("GET",  "/bug-reports",               "admin", "allowed"),

    ("GET",  "/uploads/bug-reports/test.jpg", "guest", "denied"),
    ("GET",  "/uploads/bug-reports/test.jpg", "user",  "denied"),
    ("GET",  "/uploads/bug-reports/test.jpg", "admin", "allowed"),
]


def _make_request_kwargs(method: str, path: str) -> dict[str, Any]:
    """Return the minimal kwargs needed to reach auth checks for this route."""
    if method == "GET" or method == "DELETE":
        return {}
    # POST / PUT — supply a body stub so FastAPI can route to the handler
    if path == "/audio/transcribe":
        return {"files": {"file": ("stub.wav", io.BytesIO(b"\x00"), "audio/wav")}}
    if path == "/audio/synthesize":
        return {"json": {"text": "hi"}}
    if path == "/notifications/subscribe":
        return {"json": {"endpoint": "x", "keys": {"auth": "x", "p256dh": "x"}}}
    if path.startswith("/settings/voice"):
        return {"json": {}}
    return {"json": {}}


@pytest.mark.parametrize(
    "method,path,role,expected",
    _MATRIX,
    ids=[f"{m}_{p.replace('/', '_').strip('_')}__{r}" for m, p, r, _ in _MATRIX],
)
def test_route_security(
    clients: dict[str, TestClient],
    method: str,
    path: str,
    role: str,
    expected: str,
) -> None:
    c = clients[role]
    kwargs = _make_request_kwargs(method, path)
    resp = getattr(c, method.lower())(path, **kwargs)
    _assert_access(resp.status_code, expected, role, f"{method} {path}")

"""Personality isolation tests — Fase 2b.

Verifies that personality settings are isolated per session:
  - Two sessions can hold different values for the same parameter.
  - A new session (no overrides) inherits the global fallback.
  - /personality/reset removes overrides and falls back to global.
  - All roles (guest, user, admin) can read and adjust their own session.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import make_admin_token, make_user_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADJUST_SARCASM = {
    "parameter": "sarcasm_level",
    "operation": "set_absolute",
    "amount": 0.77,
    "source": "test",
}

_ADJUST_WARMTH = {
    "parameter": "warmth_level",
    "operation": "set_absolute",
    "amount": 0.88,
    "source": "test",
}


def _fresh_guest_cookie() -> str:
    """Return a unique guest session cookie value."""
    return f"guest:{uuid.uuid4().hex}"


def _guest_client(cookie: str) -> TestClient:
    return TestClient(app, raise_server_exceptions=True,
                      cookies={"sity_guest_session": cookie})


def _user_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True,
                      cookies={"sity_session": make_user_token()})


def _admin_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True,
                      cookies={"sity_session": make_admin_token()})


# ---------------------------------------------------------------------------
# 1. Two sessions change the same parameter independently
# ---------------------------------------------------------------------------

def test_two_guest_sessions_are_isolated() -> None:
    """Guest A adjusts sarcasm; Guest B should see the unmodified global value."""
    cookie_a = _fresh_guest_cookie()
    cookie_b = _fresh_guest_cookie()

    with _guest_client(cookie_a) as a, _guest_client(cookie_b) as b:
        baseline = b.get("/settings/personality").json()["sarcasm_level"]

        r = a.post("/settings/personality/adjust", json=_ADJUST_SARCASM)
        assert r.status_code == 200
        assert r.json()["new_value"] == pytest.approx(0.77)

        # A sees its own value
        assert a.get("/settings/personality").json()["sarcasm_level"] == pytest.approx(0.77)
        # B still sees the original global value
        assert b.get("/settings/personality").json()["sarcasm_level"] == pytest.approx(baseline)


def test_user_and_guest_sessions_are_isolated() -> None:
    """User adjusts warmth; an independent guest session is unaffected."""
    cookie_g = _fresh_guest_cookie()

    with _user_client() as u, _guest_client(cookie_g) as g:
        baseline = g.get("/settings/personality").json()["warmth_level"]

        r = u.post("/settings/personality/adjust", json=_ADJUST_WARMTH)
        assert r.status_code == 200

        assert u.get("/settings/personality").json()["warmth_level"] == pytest.approx(0.88)
        assert g.get("/settings/personality").json()["warmth_level"] == pytest.approx(baseline)


# ---------------------------------------------------------------------------
# 2. New session inherits global fallback
# ---------------------------------------------------------------------------

def test_new_session_inherits_global_fallback() -> None:
    """A fresh guest session with no overrides reads the global default values."""
    from app.settings.settings_service import CANONICAL_PERSONALITY

    cookie = _fresh_guest_cookie()
    with _guest_client(cookie) as c:
        personality = c.get("/settings/personality").json()
        for key, expected in CANONICAL_PERSONALITY.items():
            assert personality[key] == pytest.approx(expected, abs=1e-4), (
                f"{key}: expected global default {expected}, got {personality[key]}"
            )


# ---------------------------------------------------------------------------
# 3. Reset removes session overrides and falls back to global
# ---------------------------------------------------------------------------

def test_reset_removes_session_overrides() -> None:
    """After adjust + reset, the session reads the global value again."""
    from app.settings.settings_service import CANONICAL_PERSONALITY

    cookie = _fresh_guest_cookie()
    global_sarcasm = CANONICAL_PERSONALITY["sarcasm_level"]

    with _guest_client(cookie) as c:
        c.post("/settings/personality/adjust", json=_ADJUST_SARCASM)
        assert c.get("/settings/personality").json()["sarcasm_level"] == pytest.approx(0.77)

        r = c.post("/settings/personality/reset")
        assert r.status_code == 200
        assert c.get("/settings/personality").json()["sarcasm_level"] == pytest.approx(global_sarcasm)


def test_reset_does_not_affect_other_sessions() -> None:
    """Resetting session A does not change session B's overrides."""
    cookie_a = _fresh_guest_cookie()
    cookie_b = _fresh_guest_cookie()

    with _guest_client(cookie_a) as a, _guest_client(cookie_b) as b:
        a.post("/settings/personality/adjust", json=_ADJUST_SARCASM)
        b.post("/settings/personality/adjust", json=_ADJUST_SARCASM)

        a.post("/settings/personality/reset")

        # A is back to global
        from app.settings.settings_service import CANONICAL_PERSONALITY
        assert a.get("/settings/personality").json()["sarcasm_level"] == pytest.approx(
            CANONICAL_PERSONALITY["sarcasm_level"]
        )
        # B retains its override
        assert b.get("/settings/personality").json()["sarcasm_level"] == pytest.approx(0.77)


# ---------------------------------------------------------------------------
# 4. All roles can access their own personality (reset is open to all)
# ---------------------------------------------------------------------------

def test_guest_can_adjust_and_reset_personality() -> None:
    cookie = _fresh_guest_cookie()
    with _guest_client(cookie) as c:
        assert c.post("/settings/personality/adjust", json=_ADJUST_SARCASM).status_code == 200
        assert c.post("/settings/personality/reset").status_code == 200


def test_user_can_adjust_and_reset_personality() -> None:
    with _user_client() as c:
        assert c.post("/settings/personality/adjust", json=_ADJUST_WARMTH).status_code == 200
        assert c.post("/settings/personality/reset").status_code == 200


def test_admin_can_adjust_and_reset_personality() -> None:
    with _admin_client() as c:
        assert c.post("/settings/personality/adjust", json=_ADJUST_SARCASM).status_code == 200
        assert c.post("/settings/personality/reset").status_code == 200

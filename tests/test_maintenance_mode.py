"""Tests for MaintenanceModeMiddleware (SITY_MAINTENANCE_MODE).

Scenarios:
- Maintenance OFF (default) → all roles proceed normally
- Maintenance ON:
  - Admin (valid JWT, role=admin) → passes through
  - User (valid JWT, role=user) → 503 with message
  - Guest (no cookie) → 503 with message
  - /health → always exempt (no block)
  - /auth/login → always exempt (no block)
  - /auth/logout → always exempt (no block)
- 503 body is valid JSON with "detail" key
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.runtime_config import RuntimeConfig, get_runtime_config
from app.main import app
from helpers import make_admin_token, make_user_token


# ---------------------------------------------------------------------------
# Helper: patch runtime_config.maintenance_mode
# ---------------------------------------------------------------------------

def _maintenance_on():
    """Context manager that enables maintenance mode in runtime_config."""
    base = get_runtime_config()
    patched = RuntimeConfig(
        project_root=base.project_root,
        platform=base.platform,
        profile=base.profile,
        ai_provider=base.ai_provider,
        daily_token_hard_cap=base.daily_token_hard_cap,
        local_only=base.local_only,
        local_ai_enabled=base.local_ai_enabled,
        local_ai_provider=base.local_ai_provider,
        maintenance_mode=True,
    )
    return patch("app.auth.maintenance.get_runtime_config", return_value=patched)


# ---------------------------------------------------------------------------
# Maintenance OFF — default behaviour unchanged
# ---------------------------------------------------------------------------

def test_maintenance_off_guest_can_hit_health():
    with TestClient(app, raise_server_exceptions=True) as c:
        assert c.get("/health").status_code == 200


def test_maintenance_off_guest_can_hit_auth_me():
    with TestClient(app, raise_server_exceptions=True) as c:
        assert c.get("/auth/me").status_code == 200


def test_maintenance_off_user_can_hit_auth_me():
    token = make_user_token()
    with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
        assert c.get("/auth/me").status_code == 200


# ---------------------------------------------------------------------------
# Maintenance ON — exempt paths
# ---------------------------------------------------------------------------

def test_maintenance_on_health_exempt():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            assert c.get("/health").status_code == 200


def test_maintenance_on_login_exempt():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            # POST /auth/login with bad creds → 401, not 503
            resp = c.post("/auth/login", json={"email": "x@x.com", "password": "bad"})
            assert resp.status_code != 503


def test_maintenance_on_logout_exempt():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.post("/auth/logout")
            assert resp.status_code != 503


# ---------------------------------------------------------------------------
# Maintenance ON — Admin passes through
# ---------------------------------------------------------------------------

def test_maintenance_on_admin_passes_auth_me():
    token = make_admin_token()
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
            resp = c.get("/auth/me")
            assert resp.status_code == 200
            assert resp.json()["role"] == "admin"


def test_maintenance_on_admin_passes_health():
    token = make_admin_token()
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
            assert c.get("/health").status_code == 200


def test_maintenance_on_admin_passes_settings():
    token = make_admin_token()
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
            # /settings/personality is a real endpoint; admin gets through maintenance
            resp = c.get("/settings/personality")
            assert resp.status_code != 503


# ---------------------------------------------------------------------------
# Maintenance ON — Guest blocked
# ---------------------------------------------------------------------------

def test_maintenance_on_guest_blocked_auth_me():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/auth/me")
            assert resp.status_code == 503


def test_maintenance_on_guest_blocked_has_detail():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/auth/me")
            body = resp.json()
            assert "detail" in body
            assert "mantenimiento" in body["detail"].lower()


def test_maintenance_on_guest_blocked_chat():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.post("/chat/message", json={"message": "hola"})
            assert resp.status_code == 503


def test_maintenance_on_guest_blocked_settings():
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/settings/personality")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Maintenance ON — Authenticated User blocked
# ---------------------------------------------------------------------------

def test_maintenance_on_user_blocked_auth_me():
    token = make_user_token()
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
            resp = c.get("/auth/me")
            assert resp.status_code == 503


def test_maintenance_on_user_blocked_chat():
    token = make_user_token()
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
            resp = c.post("/chat/message", json={"message": "hola"})
            assert resp.status_code == 503


def test_maintenance_on_user_blocked_has_detail():
    token = make_user_token()
    with _maintenance_on():
        with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
            resp = c.get("/auth/me")
            assert "mantenimiento" in resp.json()["detail"].lower()

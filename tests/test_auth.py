"""Tests for /auth endpoints.

Coverage:
  POST   /auth/register       — happy path, duplicate email, weak password, invalid email
  POST   /auth/login          — happy path, wrong password, unknown email, last_login update
  POST   /auth/logout         — clears cookie
  GET    /auth/me             — authenticated, guest
  POST   /auth/forgot-password — known email, unknown email (same 200 — anti-enumeration)
  POST   /auth/reset-password — success, expired token, used token, invalid token, weak new password
  DELETE /auth/me             — authenticated deletes own row; guest gets 401
  Dependency get_current_user — no cookie, invalid token, valid token
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.db import engine
from app.memory.models import PasswordResetToken, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _email(tag: str = "") -> str:
    """Unique email per invocation — UUID suffix prevents collisions across re-runs."""
    prefix = tag or "user"
    return f"test_{prefix}_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register(client: TestClient, email: str, password: str = "Str0ngPass1") -> dict:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_reset_token(email: str, hours_offset: float = 1.0) -> str:
    """Insert a PasswordResetToken directly into the test DB. Returns the token string."""
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        assert user is not None, f"User {email!r} not found in DB"
        token_str = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours_offset)
        session.add(PasswordResetToken(token=token_str, user_id=user.id, expires_at=expires_at))
        session.commit()
    return token_str


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


def test_register_success():
    email = _email("reg_ok")
    with _client() as c:
        resp = c.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert data["email"] == email
    assert data["role"] == "user"
    assert "sity_session" in resp.cookies


def test_register_creates_db_row():
    email = _email("reg_db")
    with _client() as c:
        _register(c, email)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
    assert user is not None
    assert user.role == "user"
    assert user.is_active is True


def test_register_duplicate_email():
    email = _email("reg_dup")
    with _client() as c:
        _register(c, email)
        resp = c.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 409
    assert "registrado" in resp.json()["detail"]


def test_register_weak_password_too_short():
    with _client() as c:
        resp = c.post("/auth/register", json={"email": _email(), "password": "Ab1"})
    assert resp.status_code == 422
    assert "8 caracteres" in resp.json()["detail"]


def test_register_weak_password_no_upper():
    with _client() as c:
        resp = c.post("/auth/register", json={"email": _email(), "password": "str0ngpass"})
    assert resp.status_code == 422
    assert "mayúscula" in resp.json()["detail"]


def test_register_weak_password_no_lower():
    with _client() as c:
        resp = c.post("/auth/register", json={"email": _email(), "password": "STR0NGPASS"})
    assert resp.status_code == 422
    assert "minúscula" in resp.json()["detail"]


def test_register_weak_password_no_digit():
    with _client() as c:
        resp = c.post("/auth/register", json={"email": _email(), "password": "StrongPass"})
    assert resp.status_code == 422
    assert "número" in resp.json()["detail"]


def test_register_invalid_email():
    with _client() as c:
        resp = c.post("/auth/register", json={"email": "notanemail", "password": "Str0ngPass1"})
    assert resp.status_code == 422
    assert "email" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success():
    email = _email("login_ok")
    with _client() as c:
        _register(c, email)
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["role"] == "user"
    assert "sity_session" in resp.cookies


def test_login_wrong_password():
    email = _email("login_wp")
    with _client() as c:
        _register(c, email)
        resp = c.post("/auth/login", json={"email": email, "password": "WrongPass9"})
    assert resp.status_code == 401


def test_login_unknown_email():
    with _client() as c:
        resp = c.post("/auth/login", json={"email": "nobody@sity-test.invalid", "password": "Str0ngPass1"})
    assert resp.status_code == 401


def test_login_updates_last_login():
    email = _email("login_ts")
    with _client() as c:
        _register(c, email)
        c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
    assert user is not None
    assert user.last_login_at is not None


def test_login_inactive_account():
    """is_active=False → 403 even with correct password."""
    email = _email("login_inactive")
    with _client() as c:
        _register(c, email)
    # Manually deactivate
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        user.is_active = False
        session.add(user)
        session.commit()
    with _client() as c:
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_returns_ok():
    email = _email("logout")
    with _client() as c:
        _register(c, email)
        resp = c.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_logout_guest_also_ok():
    """Logout without a session should still succeed (idempotent)."""
    with _client() as c:
        resp = c.post("/auth/logout")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


def test_me_authenticated():
    email = _email("me_auth")
    with _client() as c:
        _register(c, email)
        resp = c.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "user"
    assert data["email"] == email
    assert data["id"] is not None


def test_me_guest():
    with _client() as c:
        resp = c.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "guest"
    assert data.get("email") is None
    assert data.get("id") is None


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------


def test_forgot_password_known_email():
    email = _email("forgot_ok")
    with _client() as c:
        _register(c, email)
        resp = c.post("/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_forgot_password_known_email_creates_token():
    email = _email("forgot_tok")
    with _client() as c:
        _register(c, email)
        c.post("/auth/forgot-password", json={"email": email})
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        rt = session.exec(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        ).first()
    assert rt is not None
    assert rt.used_at is None


def test_forgot_password_unknown_email_still_200():
    """Anti-enumeration: never reveal whether the email exists."""
    with _client() as c:
        resp = c.post("/auth/forgot-password", json={"email": "nobody@sity-test.invalid"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------


def test_reset_password_success():
    email = _email("reset_ok")
    with _client() as c:
        _register(c, email)
    token_str = _make_reset_token(email)
    with _client() as c:
        resp = c.post("/auth/reset-password", json={"token": token_str, "new_password": "N3wPasswd"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # Confirm new password works
    with _client() as c:
        resp = c.post("/auth/login", json={"email": email, "password": "N3wPasswd"})
    assert resp.status_code == 200


def test_reset_password_old_password_no_longer_works():
    email = _email("reset_old")
    with _client() as c:
        _register(c, email)
    token_str = _make_reset_token(email)
    with _client() as c:
        c.post("/auth/reset-password", json={"token": token_str, "new_password": "N3wPasswd"})
    with _client() as c:
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 401


def test_reset_password_marks_token_used():
    email = _email("reset_mark")
    with _client() as c:
        _register(c, email)
    token_str = _make_reset_token(email)
    with _client() as c:
        c.post("/auth/reset-password", json={"token": token_str, "new_password": "N3wPasswd"})
    with Session(engine) as session:
        rt = session.exec(
            select(PasswordResetToken).where(PasswordResetToken.token == token_str)
        ).first()
    assert rt.used_at is not None


def test_reset_password_expired_token():
    email = _email("reset_exp")
    with _client() as c:
        _register(c, email)
    token_str = _make_reset_token(email, hours_offset=-0.001)  # already expired
    with _client() as c:
        resp = c.post("/auth/reset-password", json={"token": token_str, "new_password": "N3wPasswd"})
    assert resp.status_code == 400
    assert "expirado" in resp.json()["detail"]


def test_reset_password_used_token():
    email = _email("reset_used")
    with _client() as c:
        _register(c, email)
    token_str = _make_reset_token(email)
    with _client() as c:
        c.post("/auth/reset-password", json={"token": token_str, "new_password": "N3wPasswd"})
        resp = c.post("/auth/reset-password", json={"token": token_str, "new_password": "An0therPass"})
    assert resp.status_code == 400
    assert "utilizado" in resp.json()["detail"]


def test_reset_password_invalid_token():
    with _client() as c:
        resp = c.post("/auth/reset-password", json={"token": "nonexistent-token-xyz", "new_password": "N3wPasswd"})
    assert resp.status_code == 400


def test_reset_password_weak_new_password():
    email = _email("reset_weak")
    with _client() as c:
        _register(c, email)
    token_str = _make_reset_token(email)
    with _client() as c:
        resp = c.post("/auth/reset-password", json={"token": token_str, "new_password": "weak"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Delete account
# ---------------------------------------------------------------------------


def test_delete_account_success():
    email = _email("del_ok")
    with _client() as c:
        data = _register(c, email)
        user_id = data["id"]
        resp = c.delete("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    with Session(engine) as session:
        user = session.get(User, user_id)
    assert user is None


def test_delete_account_guest_fails():
    with _client() as c:
        resp = c.delete("/auth/me")
    assert resp.status_code == 401


def test_delete_account_login_fails_after():
    email = _email("del_login")
    with _client() as c:
        _register(c, email)
        c.delete("/auth/me")
    with _client() as c:
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------


def _mock_response():
    """Minimal Response stub for calling get_current_user() directly in tests."""
    from fastapi import Response
    return Response()


def test_dependency_no_cookie_is_guest():
    from app.auth.dependencies import CurrentUser, get_current_user
    from sqlmodel import Session as _Session

    with _Session(engine) as session:
        result = get_current_user(response=_mock_response(), sity_session=None, session=session)
    assert isinstance(result, CurrentUser)
    assert result.is_guest is True
    assert result.role == "guest"
    assert result.user_id is None
    assert result.session_id.startswith("guest:")


def test_dependency_invalid_cookie_is_guest():
    from app.auth.dependencies import get_current_user
    from sqlmodel import Session as _Session

    with _Session(engine) as session:
        result = get_current_user(response=_mock_response(), sity_session="not.a.valid.jwt", session=session)
    assert result.is_guest is True


def test_dependency_valid_cookie_resolves_user():
    from app.auth.dependencies import get_current_user
    from app.auth.jwt_utils import create_token
    from sqlmodel import Session as _Session

    email = _email("dep_auth")
    with _client() as c:
        data = _register(c, email)
    user_id = data["id"]

    token = create_token(user_id=user_id, role="user")
    with _Session(engine) as session:
        result = get_current_user(response=_mock_response(), sity_session=token, session=session)

    assert result.is_guest is False
    assert result.is_authenticated is True
    assert result.role == "user"
    assert result.user_id == user_id
    assert result.session_id == f"user:{user_id}"
    assert result.is_admin is False


def test_dependency_expired_token_is_guest():
    from app.auth.dependencies import get_current_user
    from app.auth.jwt_utils import create_token
    from sqlmodel import Session as _Session

    email = _email("dep_exp")
    with _client() as c:
        data = _register(c, email)
    user_id = data["id"]

    token = create_token(user_id=user_id, role="user", expiry_hours=-1)  # already expired
    with _Session(engine) as session:
        result = get_current_user(response=_mock_response(), sity_session=token, session=session)
    assert result.is_guest is True

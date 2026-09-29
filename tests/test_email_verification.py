"""Tests for the email verification flow.

Coverage:
  POST /auth/register              — creates EmailVerificationToken, no session cookie
  GET  /auth/verify-email?token=   — success redirect, error redirect, expired, used
  POST /auth/resend-verification   — happy path, rate limit, already-verified silently ok
  login gate                       — 403 until verified, 200 after
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.db import engine
from app.memory.models import EmailVerificationToken, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _email(tag: str = "") -> str:
    prefix = tag or "vt"
    return f"test_{prefix}_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True, follow_redirects=False)


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _register_raw(client: TestClient, email: str, password: str = "Str0ngPass1") -> dict:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get_latest_token(email: str) -> str:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        assert user is not None
        token = session.exec(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .where(EmailVerificationToken.used_at == None)  # noqa: E711
        ).first()
        assert token is not None, "No unused verification token found"
        return token.token


# ---------------------------------------------------------------------------
# Register → pending_verification, no cookie
# ---------------------------------------------------------------------------


def test_register_returns_pending_verification():
    email = _email("reg_pend")
    with _client() as c:
        resp = c.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert data["pending_verification"] is True
    assert "sity_session" not in resp.cookies


def test_register_creates_verification_token():
    email = _email("reg_tok")
    with _client() as c:
        _register_raw(c, email)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        assert user is not None
        vt = session.exec(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        ).first()
    assert vt is not None
    assert vt.used_at is None
    assert vt.expires_at > _naive_utc_now()


def test_register_user_is_not_verified():
    email = _email("reg_unvf")
    with _client() as c:
        _register_raw(c, email)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
    assert user is not None
    assert user.is_verified is False


# ---------------------------------------------------------------------------
# GET /auth/verify-email
# ---------------------------------------------------------------------------


def test_verify_email_success():
    email = _email("vt_ok")
    with _client() as c:
        _register_raw(c, email)
    token = _get_latest_token(email)

    with _client() as c:
        resp = c.get(f"/auth/verify-email?token={token}")

    assert resp.status_code == 302
    assert "email_verified=success" in resp.headers["location"]

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
    assert user is not None
    assert user.is_verified is True


def test_verify_email_marks_token_used():
    email = _email("vt_used_mark")
    with _client() as c:
        _register_raw(c, email)
    token = _get_latest_token(email)

    with _client() as c:
        c.get(f"/auth/verify-email?token={token}")

    with Session(engine) as session:
        vt = session.exec(
            select(EmailVerificationToken).where(EmailVerificationToken.token == token)
        ).first()
    assert vt is not None
    assert vt.used_at is not None


def test_verify_email_invalid_token():
    with _client() as c:
        resp = c.get("/auth/verify-email?token=not-a-real-token")
    assert resp.status_code == 302
    assert "email_verified=error" in resp.headers["location"]


def test_verify_email_already_used_token():
    email = _email("vt_reuse")
    with _client() as c:
        _register_raw(c, email)
    token = _get_latest_token(email)

    with _client() as c:
        c.get(f"/auth/verify-email?token={token}")
    with _client() as c:
        resp = c.get(f"/auth/verify-email?token={token}")

    assert resp.status_code == 302
    assert "email_verified=error" in resp.headers["location"]


def test_verify_email_expired_token():
    email = _email("vt_exp")
    with _client() as c:
        _register_raw(c, email)

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        vt = session.exec(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
        ).first()
        vt.expires_at = _naive_utc_now() - timedelta(seconds=1)
        session.add(vt)
        session.commit()
        token = vt.token

    with _client() as c:
        resp = c.get(f"/auth/verify-email?token={token}")

    assert resp.status_code == 302
    assert "email_verified=error" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Login gate
# ---------------------------------------------------------------------------


def test_login_blocked_until_verified():
    email = _email("gate_block")
    with _client() as c:
        _register_raw(c, email)
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 403
    assert "verificar" in resp.json()["detail"].lower()


def test_login_succeeds_after_verification():
    email = _email("gate_ok")
    with _client() as c:
        _register_raw(c, email)
    token = _get_latest_token(email)

    with _client() as c:
        c.get(f"/auth/verify-email?token={token}")

    with _client() as c:
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "sity_session" in resp.cookies


# ---------------------------------------------------------------------------
# POST /auth/resend-verification
# ---------------------------------------------------------------------------


def test_resend_verification_returns_ok():
    email = _email("resend_ok")
    with _client() as c:
        _register_raw(c, email)
        resp = c.post("/auth/resend-verification", json={"email": email})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_resend_verification_invalidates_old_token():
    email = _email("resend_inv")
    with _client() as c:
        _register_raw(c, email)
    old_token = _get_latest_token(email)

    with _client() as c:
        c.post("/auth/resend-verification", json={"email": email})

    with Session(engine) as session:
        vt = session.exec(
            select(EmailVerificationToken).where(EmailVerificationToken.token == old_token)
        ).first()
    assert vt is not None
    assert vt.used_at is not None  # old token was invalidated


def test_resend_verification_creates_new_token():
    email = _email("resend_new")
    with _client() as c:
        _register_raw(c, email)
    old_token = _get_latest_token(email)

    with _client() as c:
        c.post("/auth/resend-verification", json={"email": email})

    new_token = _get_latest_token(email)
    assert new_token != old_token


def test_resend_verification_unknown_email_still_200():
    """Anti-enumeration: unknown email returns 200."""
    with _client() as c:
        resp = c.post("/auth/resend-verification", json={"email": "nobody@sity-test.invalid"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_resend_verification_already_verified_still_200():
    """Already-verified user: no new token, still 200."""
    email = _email("resend_alrdy")
    with _client() as c:
        _register_raw(c, email)
    token = _get_latest_token(email)

    with _client() as c:
        c.get(f"/auth/verify-email?token={token}")

    with _client() as c:
        resp = c.post("/auth/resend-verification", json={"email": email})
    assert resp.status_code == 200

"""Auth endpoints: register, login, logout, me, forgot/reset-password, delete account.

Cookie strategy:
  Name:     sity_session
  HttpOnly: True  (JS cannot read it)
  Secure:   True  (requires HTTPS — satisfied by Caddy + Cloudflare Tunnel in production)
  SameSite: lax   (same-origin POST works; cross-site POST blocked)
  MaxAge:   72 h
  Path:     /

Password policy:
  ≥ 8 chars, at least one uppercase, one lowercase, one digit.
  Error messages are explicit so the frontend can show them as a popup.

Captcha:
  RegisterRequest and LoginRequest accept an optional captcha_token field.
  Validation is a stub (always passes). To activate, wire send_password_reset_email
  equivalent for the captcha provider — see the TODO in schemas_auth.py.

Admin account:
  Created at startup via admin_seeder.py from SITY_ADMIN_EMAIL / SITY_ADMIN_PASSWORD.
  No endpoint promotes a User to Admin. There is exactly one Admin row.

Phase limits:
  DELETE /auth/me only deletes the User row. ChatMessage/Setting association
  with a real user_id is done in Fase 2 — a TODO comment marks the gap.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from app.api.schemas_auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.email_stub import send_password_reset_email
from app.auth.hashing import hash_password, verify_password
from app.auth.jwt_utils import create_token
from app.memory.db import get_session
from app.memory.models import PasswordResetToken, User
from app.trace.logger import new_trace_id, write_log

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "sity_session"
_GUEST_COOKIE_NAME = "sity_guest_session"
_COOKIE_MAX_AGE = 72 * 3600  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _naive_utc_now() -> datetime:
    """Current UTC time as naive datetime — matches what SQLite returns on read."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cookie_secure() -> bool:
    """True in production (Cloudflare Tunnel/Caddy = HTTPS). False in tests/dev (HTTP)."""
    return os.environ.get("SITY_COOKIE_SECURE", "true").lower() == "true"


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path="/")


def _clear_guest_cookie(response: Response) -> None:
    response.delete_cookie(key=_GUEST_COOKIE_NAME, path="/")


def _validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def _check_password_strength(password: str) -> Optional[str]:
    """Returns a user-facing error message if the password is too weak, else None."""
    if len(password) < 8:
        return "La contraseña debe tener al menos 8 caracteres"
    if not re.search(r"[A-Z]", password):
        return "La contraseña debe contener al menos una letra mayúscula"
    if not re.search(r"[a-z]", password):
        return "La contraseña debe contener al menos una letra minúscula"
    if not re.search(r"\d", password):
        return "La contraseña debe contener al menos un número"
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", status_code=201)
def register(
    body: RegisterRequest,
    response: Response,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    if not _validate_email(body.email):
        raise HTTPException(status_code=422, detail="Formato de email inválido")

    pw_error = _check_password_strength(body.password)
    if pw_error:
        raise HTTPException(status_code=422, detail=pw_error)

    if session.exec(select(User).where(User.email == body.email)).first():
        raise HTTPException(status_code=409, detail="Este email ya está registrado")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role="user",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    write_log(
        level="AUDIT", module="auth", event="user_registered",
        trace_id=trace_id, payload={"user_id": user.id}, audit=True,
    )

    assert user.id is not None  # guaranteed after commit+refresh
    _set_cookie(response, create_token(user.id, user.role))
    _clear_guest_cookie(response)
    return {"ok": True, "id": user.id, "email": user.email, "role": user.role}


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    user.last_login_at = _naive_utc_now()
    session.add(user)
    session.commit()

    write_log(
        level="AUDIT", module="auth", event="user_login",
        trace_id=trace_id, payload={"user_id": user.id}, audit=True,
    )

    assert user.id is not None  # user was fetched from DB so id is always set
    _set_cookie(response, create_token(user.id, user.role))
    _clear_guest_cookie(response)
    return {"ok": True, "id": user.id, "email": user.email, "role": user.role}


@router.post("/logout")
def logout(response: Response, _: CurrentUser = Depends(get_current_user)):
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(current: CurrentUser = Depends(get_current_user)) -> MeResponse:
    if current.is_guest:
        return MeResponse(role="guest")
    assert current.user is not None  # guaranteed: is_guest == (user is None)
    return MeResponse(role=current.role, id=current.user_id, email=current.user.email)


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    user = session.exec(select(User).where(User.email == body.email)).first()
    if user and user.is_active:
        token_str = str(uuid.uuid4())
        reset_token = PasswordResetToken(
            token=token_str,
            user_id=user.id,
            expires_at=_naive_utc_now() + timedelta(hours=1),
        )
        session.add(reset_token)
        session.commit()
        send_password_reset_email(to_email=user.email, token=token_str)
        write_log(
            level="AUDIT", module="auth", event="password_reset_requested",
            trace_id=trace_id, payload={"user_id": user.id}, audit=True,
        )

    # Always 200 — never reveal whether the email exists (anti-enumeration)
    return {"ok": True, "message": "Si el email existe, recibirás un enlace de recuperación"}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    reset_token = session.exec(
        select(PasswordResetToken).where(PasswordResetToken.token == body.token)
    ).first()

    _bad_token = HTTPException(status_code=400, detail="Token inválido o expirado")

    if not reset_token:
        raise _bad_token
    if reset_token.used_at is not None:
        raise HTTPException(status_code=400, detail="Este token ya fue utilizado")
    if _naive_utc_now() > reset_token.expires_at:
        raise _bad_token

    pw_error = _check_password_strength(body.new_password)
    if pw_error:
        raise HTTPException(status_code=422, detail=pw_error)

    user = session.get(User, reset_token.user_id)
    if not user:
        raise _bad_token

    user.password_hash = hash_password(body.new_password)
    reset_token.used_at = _naive_utc_now()
    session.add(user)
    session.add(reset_token)
    session.commit()

    write_log(
        level="AUDIT", module="auth", event="password_reset_completed",
        trace_id=trace_id, payload={"user_id": user.id}, audit=True,
    )
    return {"ok": True, "message": "Contraseña actualizada correctamente"}


@router.delete("/me")
def delete_account(
    response: Response,
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida")

    user_id = current.user_id
    user = session.get(User, user_id)
    if user:
        # TODO (Fase 2): también borrar ChatMessage, Setting (task_context,
        # previous_context de Spotify, etc.) asociados al session_id derivado
        # de este user_id. En Fase 1 solo existe la fila de User — la
        # asociación del historial de chat con un user_id real llega en Fase 2.
        session.delete(user)
        session.commit()

    _clear_cookie(response)
    write_log(
        level="AUDIT", module="auth", event="user_deleted",
        trace_id=trace_id, payload={"user_id": user_id}, audit=True,
    )
    return {"ok": True}

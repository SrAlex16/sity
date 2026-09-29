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

reCAPTCHA v3:
  register and login verify a reCAPTCHA v3 token via verify_recaptcha_token().
  If RECAPTCHA_SECRET_KEY is not set, bypass mode is active (always passes,
  logs a WARN). See app/auth/recaptcha.py.

Admin account:
  Created at startup via admin_seeder.py from SITY_ADMIN_EMAIL / SITY_ADMIN_PASSWORD.
  No endpoint promotes a User to Admin. There is exactly one Admin row.

Account deletion:
  DELETE /auth/me calls _purge_user_data() which erases all rows in every
  table keyed by user_id or session_id, deletes physical files, then removes
  the User row itself.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session, delete as _bulk_delete, select

from app.api.schemas_auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
)
from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.email_stub import send_password_reset_email, send_verification_email
from app.auth.hashing import hash_password, verify_password
from app.auth.ip_rate_limiter import get_auth_rate_limiter, get_real_client_ip
from app.auth.jwt_utils import create_token
from app.auth.recaptcha import verify_recaptcha_token
from app.core.runtime_config import get_public_base_url
from app.memory.db import get_session
from app.memory.models import (
    AIUsage, AutobiographicalNarrative, BeliefAttribution, BugReport,
    ChatMessage, ChatSession, DailyMessageUsage, DailyTtsUsage,
    EmailVerificationToken, Episode, Expectation, FileArtifact,
    Goal, GoalMilestone, InitiativeEvalLog, MentalState, NotificationLog,
    OpenLoop, PasswordResetToken, PendingAction, PersonalityAlter,
    ProceduralObservation, ProceduralPattern, PushSubscription,
    ReflectionLog, RelationshipSnapshot, ScheduledTask, SemanticFact,
    Setting, SharedConversation, SocialProfile, SocialReflection,
    User, UserAchievement, UserIntegration, UserKnowledge, utc_now,
)
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
    # Must match the original cookie attributes (secure, httponly, samesite) so that
    # browsers (Chrome 104+) actually delete the Secure cookie rather than ignoring
    # a deletion header that lacks the Secure attribute.
    response.delete_cookie(
        key=_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )


def _clear_guest_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_GUEST_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )


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
    request: Request,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    ip = get_real_client_ip(request)
    allowed, retry_after = get_auth_rate_limiter().check_register_ip(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    if not _validate_email(body.email):
        raise HTTPException(status_code=422, detail="Formato de email inválido")

    pw_error = _check_password_strength(body.password)
    if pw_error:
        raise HTTPException(status_code=422, detail=pw_error)

    if not verify_recaptcha_token(body.recaptcha_token):
        raise HTTPException(status_code=403, detail="Verificación de seguridad fallida")

    if session.exec(select(User).where(User.email == body.email)).first():
        raise HTTPException(status_code=409, detail="Este email ya está registrado")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role="user",
        display_name=body.email.split("@")[0],
        is_verified=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    assert user.id is not None  # guaranteed after commit+refresh

    token_str = str(uuid.uuid4())
    verification_token = EmailVerificationToken(
        token=token_str,
        user_id=user.id,
        expires_at=_naive_utc_now() + timedelta(hours=1),
    )
    session.add(verification_token)
    session.commit()

    try:
        send_verification_email(to_email=user.email, token=token_str)
    except Exception:
        pass  # email_stub already logged the error; preserve the 201 response

    write_log(
        level="AUDIT", module="auth", event="user_registered",
        trace_id=trace_id, payload={"user_id": user.id}, audit=True,
    )
    return {"ok": True, "pending_verification": True, "id": user.id, "email": user.email, "role": user.role}


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    ip = get_real_client_ip(request)
    limiter = get_auth_rate_limiter()

    allowed, retry_after = limiter.check_login_ip(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    email_norm = body.email.strip().lower()
    allowed, retry_after = limiter.check_login_email(email_norm)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos fallidos. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    if not verify_recaptcha_token(body.recaptcha_token):
        raise HTTPException(status_code=403, detail="Verificación de seguridad fallida")

    user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        limiter.record_login_failure(email_norm)
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email sin verificar")

    limiter.reset_login_email(email_norm)

    _prev_login = user.last_login_at
    user.last_login_at = _naive_utc_now()
    session.add(user)
    session.commit()

    write_log(
        level="AUDIT", module="auth", event="user_login",
        trace_id=trace_id, payload={"user_id": user.id}, audit=True,
    )
    try:
        if _prev_login is not None:
            from app.settings.config_loader import load_default_config
            _gap_days = int(load_default_config().get("achievements", {}).get("youre_finally_awake_days", 7))
            _now_utc = utc_now()
            _delta = (_now_utc - _prev_login).days
            if _delta >= _gap_days:
                from app.achievements.triggers.inline import fire as _fire_ach
                _fire_ach(session, f"user:{user.id}", "youre_finally_awake")
    except Exception:
        pass

    assert user.id is not None  # user was fetched from DB so id is always set
    _set_cookie(response, create_token(user.id, user.role))
    _clear_guest_cookie(response)
    return {"ok": True, "id": user.id, "email": user.email, "role": user.role}


@router.post("/logout")
def logout(
    response: Response,
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not current.is_guest and current.user_id is not None:
        try:
            from app.cognition.goal_service import resolve_short_term_goals_on_logout
            resolve_short_term_goals_on_logout(session, current.user_id)
        except Exception:
            pass
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(current: CurrentUser = Depends(get_current_user)) -> MeResponse:
    if current.is_guest:
        return MeResponse(role="guest")
    assert current.user is not None  # guaranteed: is_guest == (user is None)
    return MeResponse(role=current.role, id=current.user_id, email=current.user.email,
                      display_name=current.user.display_name)


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    ip = get_real_client_ip(request)
    allowed, retry_after = get_auth_rate_limiter().check_forgot_ip(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )


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
        try:
            send_password_reset_email(to_email=user.email, token=token_str)
        except Exception:
            pass  # email_stub already logged the error; preserve anti-enumeration 200
        write_log(
            level="AUDIT", module="auth", event="password_reset_requested",
            trace_id=trace_id, payload={"user_id": user.id}, audit=True,
        )

    # Always 200 — never reveal whether the email exists (anti-enumeration)
    return {"ok": True, "message": "Si el email existe, recibirás un enlace de recuperación"}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()

    ip = get_real_client_ip(request)
    allowed, retry_after = get_auth_rate_limiter().check_reset_ip(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )


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


@router.get("/verify-email")
def verify_email(
    token: str,
    session: Session = Depends(get_session),
):
    base_url = get_public_base_url()
    _bad = RedirectResponse(url=f"{base_url}/?email_verified=error", status_code=302)

    vt = session.exec(
        select(EmailVerificationToken).where(EmailVerificationToken.token == token)
    ).first()

    if not vt or vt.used_at is not None or _naive_utc_now() > vt.expires_at:
        return _bad

    user = session.get(User, vt.user_id)
    if not user:
        return _bad

    user.is_verified = True
    vt.used_at = _naive_utc_now()
    session.add(user)
    session.add(vt)
    session.commit()

    write_log(
        level="AUDIT", module="auth", event="email_verified",
        payload={"user_id": user.id}, audit=True,
    )
    return RedirectResponse(url=f"{base_url}/?email_verified=success", status_code=302)


@router.post("/resend-verification")
def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    allowed, retry_after = get_auth_rate_limiter().check_resend_email(body.email)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    user = session.exec(select(User).where(User.email == body.email)).first()
    if user and user.is_active and not user.is_verified:
        old_tokens = session.exec(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .where(EmailVerificationToken.used_at == None)  # noqa: E711
        ).all()
        for ot in old_tokens:
            ot.used_at = _naive_utc_now()
            session.add(ot)

        token_str = str(uuid.uuid4())
        vt = EmailVerificationToken(
            token=token_str,
            user_id=user.id,
            expires_at=_naive_utc_now() + timedelta(hours=1),
        )
        session.add(vt)
        session.commit()
        try:
            send_verification_email(to_email=user.email, token=token_str)
        except Exception:
            pass

    # Always 200 — never reveal whether the email exists (anti-enumeration)
    return {"ok": True}


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _purge_user_data(db: Session, user_id: int) -> None:
    """Delete every row associated with user_id before removing the User row.

    Order: disk files → child-FK tables → user_id tables → session_id tables
    → ChatSession row.  SQLite does not enforce FK constraints, but the order
    prevents orphan rows in dependent tables for engines that do.
    """
    sid = f"user:{user_id}"

    # ── Physical files on disk ────────────────────────────────────────────
    for fa in db.exec(select(FileArtifact).where(FileArtifact.user_id == user_id)).all():
        path = (_PROJECT_ROOT / fa.rel_path).resolve()
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except Exception:
            pass

    # ── Child tables (no direct user_id; FK to parent) ───────────────────
    goal_ids = [
        r.id for r in db.exec(select(Goal).where(Goal.user_id == user_id)).all()
        if r.id is not None
    ]
    if goal_ids:
        db.exec(_bulk_delete(GoalMilestone).where(GoalMilestone.goal_id.in_(goal_ids)))  # type: ignore[call-overload]

    profile_ids = [
        r.id for r in db.exec(select(SocialProfile).where(SocialProfile.user_id == user_id)).all()
        if r.id is not None
    ]
    if profile_ids:
        db.exec(_bulk_delete(RelationshipSnapshot).where(RelationshipSnapshot.profile_id.in_(profile_ids)))  # type: ignore[call-overload]
        db.exec(_bulk_delete(SocialReflection).where(SocialReflection.profile_id.in_(profile_ids)))  # type: ignore[call-overload]

    # ── Tables keyed by user_id ───────────────────────────────────────────
    db.exec(_bulk_delete(FileArtifact).where(FileArtifact.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(UserIntegration).where(UserIntegration.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(PersonalityAlter).where(PersonalityAlter.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(UserAchievement).where(UserAchievement.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(MentalState).where(MentalState.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(Goal).where(Goal.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(Episode).where(Episode.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(AutobiographicalNarrative).where(AutobiographicalNarrative.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(ReflectionLog).where(ReflectionLog.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(ProceduralObservation).where(ProceduralObservation.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(ProceduralPattern).where(ProceduralPattern.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(UserKnowledge).where(UserKnowledge.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(BeliefAttribution).where(BeliefAttribution.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(Expectation).where(Expectation.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(SemanticFact).where(SemanticFact.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(BugReport).where(BugReport.user_id == user_id))  # type: ignore[call-overload]
    db.exec(_bulk_delete(SocialProfile).where(SocialProfile.user_id == user_id))  # type: ignore[call-overload]

    # ── Tables keyed by session_id ────────────────────────────────────────
    db.exec(_bulk_delete(Setting).where(Setting.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(AIUsage).where(AIUsage.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(ChatMessage).where(ChatMessage.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(DailyMessageUsage).where(DailyMessageUsage.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(DailyTtsUsage).where(DailyTtsUsage.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(SharedConversation).where(SharedConversation.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(NotificationLog).where(NotificationLog.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(PushSubscription).where(PushSubscription.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(ScheduledTask).where(ScheduledTask.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(OpenLoop).where(OpenLoop.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(InitiativeEvalLog).where(InitiativeEvalLog.session_id == sid))  # type: ignore[call-overload]
    db.exec(_bulk_delete(PendingAction).where(PendingAction.session_id == sid))  # type: ignore[call-overload]

    # ── ChatSession row (PK = session_id string) ──────────────────────────
    cs = db.get(ChatSession, sid)
    if cs:
        db.delete(cs)


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
        _purge_user_data(session, user_id)
        session.delete(user)
        session.commit()

    _clear_cookie(response)
    write_log(
        level="AUDIT", module="auth", event="user_deleted",
        trace_id=trace_id, payload={"user_id": user_id}, audit=True,
    )
    return {"ok": True}

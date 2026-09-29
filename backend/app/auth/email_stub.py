"""Auth email senders: password reset and email verification.

Requires these env vars to send real email (e.g. via Resend SMTP):
  SITY_SMTP_HOST       — SMTP server hostname  (e.g. smtp.resend.com)
  SITY_SMTP_PORT       — port, default 587 (STARTTLS)
  SITY_SMTP_USER       — SMTP login username   (Resend: literal "resend")
  SITY_SMTP_PASSWORD   — SMTP login password / API key
  SITY_SMTP_FROM_EMAIL — From address          (e.g. no-reply@sity.aletm.com)
  SITY_BASE_URL        — public base URL for the reset link

If SITY_SMTP_HOST is not set, the link is logged at WARN level (dev/stub mode).
"""

import os
import smtplib
from email.mime.text import MIMEText

from app.core.runtime_config import get_public_base_url
from app.trace.logger import write_log


def send_password_reset_email(to_email: str, token: str) -> None:
    base_url = get_public_base_url()
    reset_url = f"{base_url}/reset-password?token={token}"

    smtp_host = os.environ.get("SITY_SMTP_HOST", "")
    if not smtp_host:
        write_log(
            level="WARN",
            module="auth",
            event="password_reset_link_logged_only",
            payload={
                "to": to_email,
                "reset_url": reset_url,
                "hint": "Set SITY_SMTP_HOST to send real emails",
            },
        )
        return

    smtp_port = int(os.environ.get("SITY_SMTP_PORT", "587"))
    smtp_user = os.environ.get("SITY_SMTP_USER", "")
    smtp_password = os.environ.get("SITY_SMTP_PASSWORD", "")
    from_email = os.environ.get("SITY_SMTP_FROM_EMAIL", smtp_user)

    body = (
        f"Hola,\n\n"
        f"Restablece tu contraseña en Sity haciendo clic en el siguiente enlace:\n\n"
        f"{reset_url}\n\n"
        f"El enlace expira en 1 hora. Si no solicitaste este restablecimiento, "
        f"ignora este mensaje.\n\n"
        f"— Sity"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "Restablecer contraseña — Sity"
    msg["From"] = from_email
    msg["To"] = to_email

    write_log(
        level="INFO",
        module="auth",
        event="smtp_send_attempt",
        payload={"to": to_email, "host": smtp_host, "port": smtp_port},
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
            s.starttls()
            s.login(smtp_user, smtp_password)
            s.send_message(msg)
        write_log(
            level="INFO",
            module="auth",
            event="smtp_send_success",
            payload={"to": to_email},
        )
    except smtplib.SMTPAuthenticationError as exc:
        write_log(
            level="ERROR",
            module="auth",
            event="smtp_auth_failed",
            payload={"host": smtp_host, "error": str(exc)[:300]},
        )
        raise
    except Exception as exc:
        write_log(
            level="ERROR",
            module="auth",
            event="smtp_send_failed",
            payload={
                "to": to_email,
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
            },
        )
        raise


def send_verification_email(to_email: str, token: str, lang: str = "es") -> None:
    """Send an email-verification link to a newly registered user.

    Same SMTP configuration as send_password_reset_email.
    If SITY_SMTP_HOST is not set, the link is logged at WARN level (dev/stub mode).
    """
    base_url = get_public_base_url()
    verify_url = f"{base_url}/auth/verify-email?token={token}"

    smtp_host = os.environ.get("SITY_SMTP_HOST", "")
    if not smtp_host:
        write_log(
            level="WARN",
            module="auth",
            event="verification_link_logged_only",
            payload={
                "to": to_email,
                "verify_url": verify_url,
                "hint": "Set SITY_SMTP_HOST to send real emails",
            },
        )
        return

    smtp_port = int(os.environ.get("SITY_SMTP_PORT", "587"))
    smtp_user = os.environ.get("SITY_SMTP_USER", "")
    smtp_password = os.environ.get("SITY_SMTP_PASSWORD", "")
    from_email = os.environ.get("SITY_SMTP_FROM_EMAIL", smtp_user)

    if lang == "en":
        subject = "Verify your Sity account"
        body = (
            f"Hi,\n\n"
            f"Please verify your Sity account by clicking the link below:\n\n"
            f"{verify_url}\n\n"
            f"The link expires in 1 hour. If you did not create this account, "
            f"you can safely ignore this message.\n\n"
            f"— Sity"
        )
    else:
        subject = "Verifica tu cuenta en Sity"
        body = (
            f"Hola,\n\n"
            f"Activa tu cuenta en Sity haciendo clic en el siguiente enlace:\n\n"
            f"{verify_url}\n\n"
            f"El enlace expira en 1 hora. Si no creaste esta cuenta, "
            f"ignora este mensaje.\n\n"
            f"— Sity"
        )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    write_log(
        level="INFO",
        module="auth",
        event="smtp_verification_attempt",
        payload={"to": to_email, "host": smtp_host, "port": smtp_port},
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
            s.starttls()
            s.login(smtp_user, smtp_password)
            s.send_message(msg)
        write_log(
            level="INFO",
            module="auth",
            event="smtp_verification_success",
            payload={"to": to_email},
        )
    except smtplib.SMTPAuthenticationError as exc:
        write_log(
            level="ERROR",
            module="auth",
            event="smtp_auth_failed",
            payload={"host": smtp_host, "error": str(exc)[:300]},
        )
        raise
    except Exception as exc:
        write_log(
            level="ERROR",
            module="auth",
            event="smtp_send_failed",
            payload={
                "to": to_email,
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
            },
        )
        raise

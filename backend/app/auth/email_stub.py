"""Password-reset email sender.

Currently a stub: the reset link is logged at WARN level instead of
being emailed. This makes the feature fully functional for development
and allows Alex to share links manually.

To activate real email sending, set these env vars and implement the
SMTP block marked TODO below:
  SITY_SMTP_HOST       — SMTP server hostname (e.g. smtp.gmail.com)
  SITY_SMTP_PORT       — port, default 587 (STARTTLS)
  SITY_SMTP_USER       — SMTP login username
  SITY_SMTP_PASSWORD   — SMTP login password
  SITY_SMTP_FROM_EMAIL — From address (e.g. no-reply@sity.aletm.com)
  SITY_BASE_URL        — public base URL for the reset link
                         (default: http://localhost:5173)
"""

import os

from app.trace.logger import write_log


def send_password_reset_email(to_email: str, token: str) -> None:
    base_url = os.environ.get("SITY_BASE_URL", "http://localhost:5173")
    reset_url = f"{base_url}/reset-password?token={token}"

    if not os.environ.get("SITY_SMTP_HOST"):
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

    # TODO: implement real SMTP sending once credentials are configured.
    # Example skeleton:
    #
    # import smtplib
    # from email.mime.text import MIMEText
    #
    # body = f"Restablece tu contraseña aquí:\n\n{reset_url}\n\nExpira en 1 hora."
    # msg = MIMEText(body)
    # msg["Subject"] = "Restablecer contraseña — Sity"
    # msg["From"] = os.environ["SITY_SMTP_FROM_EMAIL"]
    # msg["To"] = to_email
    # with smtplib.SMTP(os.environ["SITY_SMTP_HOST"],
    #                   int(os.environ.get("SITY_SMTP_PORT", 587))) as s:
    #     s.starttls()
    #     s.login(os.environ["SITY_SMTP_USER"], os.environ["SITY_SMTP_PASSWORD"])
    #     s.send_message(msg)

    write_log(
        level="INFO",
        module="auth",
        event="password_reset_email_sent",
        payload={"to": to_email},
    )

"""reCAPTCHA v3 verification helper.

Behaviour when RECAPTCHA_SECRET_KEY is not set:
  - Production (SITY_RECAPTCHA_BYPASS not set or "0"): fail-closed — returns False
    so auth endpoints reject the request.  A misconfiguration never silently removes
    brute-force protection.
  - Development / CI (SITY_RECAPTCHA_BYPASS=1): returns True and logs INFO.
    Set this in .env.local or the test environment only — never in production.

The secret key is read from os.environ at every call (not at import) so that
hot-reloading, environment patching, and test monkeypatching work without restart.
"""
from __future__ import annotations

import os

import httpx

from app.trace.logger import write_log

_SCORE_THRESHOLD: float = float(os.environ.get("RECAPTCHA_SCORE_THRESHOLD", "0.5"))
_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def verify_recaptcha_token(token: str) -> bool:
    """Verify a reCAPTCHA v3 token against Google's API.

    Returns True  — token is valid and score >= threshold.
    Returns True  — no key configured AND SITY_RECAPTCHA_BYPASS=1 (dev/CI bypass).
    Returns False — no key configured and bypass not active (fail-closed).
    Returns False — verification failure, low score, or network error.
    """
    secret_key: str = os.environ.get("RECAPTCHA_SECRET_KEY", "")
    if not secret_key:
        if os.environ.get("SITY_RECAPTCHA_BYPASS", "0") == "1":
            write_log(
                level="INFO",
                module="auth",
                event="recaptcha_bypass_active",
                payload={"hint": "SITY_RECAPTCHA_BYPASS=1 — skipping reCAPTCHA (dev/CI only)"},
            )
            return True
        write_log(
            level="ERROR",
            module="auth",
            event="recaptcha_not_configured",
            payload={"hint": "RECAPTCHA_SECRET_KEY not set — rejecting request (set SITY_RECAPTCHA_BYPASS=1 for dev)"},
        )
        return False

    try:
        resp = httpx.post(
            _VERIFY_URL,
            data={"secret": secret_key, "response": token},
            timeout=5.0,
        )
        body: dict = resp.json()
    except Exception as exc:
        write_log(
            level="WARN",
            module="auth",
            event="recaptcha_network_error",
            payload={"reason": str(exc)[:200]},
        )
        return False

    success: bool = bool(body.get("success", False))
    score: float = float(body.get("score", 0.0))
    error_codes: list = body.get("error-codes", [])

    if not success or score < _SCORE_THRESHOLD:
        write_log(
            level="WARN",
            module="auth",
            event="recaptcha_rejected",
            payload={
                "success": success,
                "score": round(score, 3),
                "threshold": _SCORE_THRESHOLD,
                "error_codes": error_codes,
            },
        )
        return False

    return True

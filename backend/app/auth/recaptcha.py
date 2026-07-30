"""reCAPTCHA v3 verification helper.

If RECAPTCHA_SECRET_KEY is not set (development / CI without keys), the
function always returns True and logs a WARN so it's obvious in logs that
no real protection is active.
"""
from __future__ import annotations

import os

import httpx

from app.trace.logger import write_log

_SECRET_KEY: str = os.environ.get("RECAPTCHA_SECRET_KEY", "")
_SCORE_THRESHOLD: float = float(os.environ.get("RECAPTCHA_SCORE_THRESHOLD", "0.5"))
_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def verify_recaptcha_token(token: str) -> bool:
    """Verify a reCAPTCHA v3 token against Google's API.

    Returns True when the token is valid and its score >= RECAPTCHA_SCORE_THRESHOLD.
    Returns True unconditionally (bypass) when RECAPTCHA_SECRET_KEY is not set.
    Returns False on verification failure, low score, or network error.
    """
    if not _SECRET_KEY:
        write_log(
            level="WARN",
            module="auth",
            event="recaptcha_not_configured",
            payload={"hint": "RECAPTCHA_SECRET_KEY not set — allowing request (bypass mode)"},
        )
        return True

    try:
        resp = httpx.post(
            _VERIFY_URL,
            data={"secret": _SECRET_KEY, "response": token},
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

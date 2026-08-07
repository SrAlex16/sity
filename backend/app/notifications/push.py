"""Web Push delivery — wraps pywebpush.webpush().

send_push() is synchronous (pywebpush makes a blocking HTTP request).
Callers that run in an async event loop should wrap it in
loop.run_in_executor() if latency matters; for Pasos 2-4, the
dispatcher is called from thread-pool contexts (run_in_executor),
so the blocking call is fine as-is.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from app.memory.models import PushSubscription


@dataclass
class PushResult:
    success: bool
    error: Optional[str] = None
    subscription_expired: bool = False  # True → caller must mark PushSubscription.is_active=False


def send_push(sub: PushSubscription, payload: dict) -> PushResult:
    """Send a Web Push notification to a single PushSubscription.

    Returns PushResult. Never raises — all exceptions are caught and
    returned as PushResult(success=False, error=...).
    """
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    # python-dotenv stores literal \n (two chars) for unquoted .env values.
    # Vapid.from_pem() needs real newlines; from_string() would try to base64-decode
    # the full PEM string including headers and fail with a 237-char invalid base64 error.
    pem = os.environ.get("VAPID_PRIVATE_KEY", "").strip().replace("\\n", "\n")
    contact = os.environ.get("VAPID_CONTACT", "").strip()
    if not pem:
        return PushResult(success=False, error="VAPID_PRIVATE_KEY not configured")

    try:
        vapid = Vapid.from_pem(pem.encode())
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid,
            vapid_claims={"sub": contact},
        )
        return PushResult(success=True)
    except WebPushException as exc:
        expired = False
        if exc.response is not None and getattr(exc.response, "status_code", None) == 410:
            expired = True
        return PushResult(success=False, error=str(exc), subscription_expired=expired)
    except Exception as exc:  # noqa: BLE001
        return PushResult(success=False, error=str(exc))

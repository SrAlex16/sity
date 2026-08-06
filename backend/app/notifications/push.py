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
    from pywebpush import WebPushException, webpush

    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    contact = os.environ.get("VAPID_CONTACT", "").strip()
    if not private_key:
        return PushResult(success=False, error="VAPID_PRIVATE_KEY not configured")

    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=private_key,
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

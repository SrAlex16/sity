"""storage_alert.py — send a push/SSE notification when a user's storage hits 90% or 100%.

Called synchronously from routes_chat.py (in the request thread) after a successful upload.
Deduplication is handled by the dispatcher using fact_id = "storage_{level}_{user_id}_{date}",
so at most one alert per level per day reaches the user.
Never raises.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from app.notifications.dispatcher import dispatch
from app.notifications.fact import NotificationFact
from app.trace.logger import write_log


def maybe_send_storage_alert(
    session_id: str,
    user_id: int,
    used_bytes: int,
    limit_bytes: int,
    db: Session,
) -> None:
    """Fire a storage warning if the user has crossed 90% or 100% of their limit.

    Safe to call on every upload — dedup in the dispatcher prevents spam.
    Never raises.
    """
    if limit_bytes <= 0:
        return
    try:
        pct = used_bytes / limit_bytes
        if pct < 0.90:
            return

        level = "full" if pct >= 1.0 else "warning"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fact_id = f"storage_{level}_{user_id}_{today}"

        used_mb = used_bytes / (1024 * 1024)
        limit_mb = limit_bytes / (1024 * 1024)

        if level == "full":
            title = "Almacenamiento lleno"
            body = (
                f"Has alcanzado el límite de {limit_mb:.0f} MB. "
                "Elimina archivos en Ajustes para poder subir más."
            )
        else:
            title = "Almacenamiento casi lleno"
            body = (
                f"Has usado {used_mb:.0f} MB de {limit_mb:.0f} MB "
                f"({pct*100:.0f}%). Revisa tus archivos en Ajustes."
            )

        fact = NotificationFact(
            session_id=session_id,
            notification_type="external_event",
            fact_id=fact_id,
            urgency="low",
            payload={"title": title, "body": body, "level": level},
        )
        dispatch(fact, db)

    except Exception as exc:
        write_log(
            level="WARN",
            module="storage_alert",
            event="alert_error",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )

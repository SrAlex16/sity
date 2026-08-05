"""Timer service — validation and CRUD for ScheduledTask.

All datetimes are stored and compared in UTC. Callers must pass timezone-aware
datetime objects (or naive datetimes treated as UTC).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.memory.models import ScheduledTask, utc_now
from app.trace.logger import write_log


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_limits() -> tuple[int, int]:
    """Return (max_duration_hours, max_active_per_session) from config."""
    from app.settings.config_loader import load_default_config
    cfg = load_default_config().get("timers", {})
    return (
        int(cfg.get("max_duration_hours", 24)),
        int(cfg.get("max_active_per_session", 5)),
    )


def count_pending(db_session: Session, session_id: str) -> int:
    stmt = select(ScheduledTask).where(
        ScheduledTask.session_id == session_id,
        ScheduledTask.fired_at == None,   # noqa: E711
        ScheduledTask.cancelled_at == None,  # noqa: E711
    )
    return len(list(db_session.exec(stmt)))


def create_scheduled_task(
    db_session: Session,
    session_id: str,
    fires_at: datetime,
    message: str,
) -> ScheduledTask:
    """Create and persist a new timer. Raises ValueError on validation failure."""
    fires_at = _ensure_utc(fires_at)
    now = datetime.now(timezone.utc)
    max_hours, max_active = _get_limits()

    if fires_at <= now:
        raise ValueError("El temporizador debe dispararse en el futuro.")

    delta_hours = (fires_at - now).total_seconds() / 3600
    if delta_hours > max_hours:
        raise ValueError(
            f"El temporizador no puede superar {max_hours} horas en el futuro."
        )

    if count_pending(db_session, session_id) >= max_active:
        raise ValueError(
            f"Límite alcanzado: máximo {max_active} temporizadores activos por sesión."
        )

    task = ScheduledTask(
        id=f"tmr_{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        fires_at=fires_at,
        message=message,
        created_at=utc_now(),
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    write_log(
        level="INFO",
        module="timers",
        event="timer_created",
        payload={
            "timer_id": task.id,
            "session_id": session_id,
            "fires_at": fires_at.isoformat(),
        },
    )
    return task


def list_pending(db_session: Session, session_id: str) -> list[ScheduledTask]:
    stmt = select(ScheduledTask).where(
        ScheduledTask.session_id == session_id,
        ScheduledTask.fired_at == None,   # noqa: E711
        ScheduledTask.cancelled_at == None,  # noqa: E711
    )
    return list(db_session.exec(stmt))


def cancel_task(
    db_session: Session,
    session_id: str,
    timer_id: str,
) -> Optional[ScheduledTask]:
    """Cancel a pending timer owned by session_id. Returns None if not found."""
    stmt = select(ScheduledTask).where(
        ScheduledTask.id == timer_id,
        ScheduledTask.session_id == session_id,
        ScheduledTask.fired_at == None,   # noqa: E711
        ScheduledTask.cancelled_at == None,  # noqa: E711
    )
    task = db_session.exec(stmt).first()
    if task is None:
        return None

    task.cancelled_at = utc_now()
    db_session.add(task)
    db_session.commit()

    write_log(
        level="INFO",
        module="timers",
        event="timer_cancelled",
        payload={"timer_id": timer_id, "session_id": session_id},
    )
    return task

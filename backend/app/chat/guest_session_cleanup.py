"""guest_session_cleanup.py — periodic cleanup of expired guest session data.

Finds ChatSession rows with id LIKE 'guest:%' that have had no activity
for more than _CUTOFF_HOURS hours, then deletes session-scoped operational
data while preserving ChatMessages for the dataset.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, col, delete as sql_delete, select

from app.memory.db import engine
from app.trace.logger import write_log

_CUTOFF_HOURS = 24
_INTERVAL_HOURS = 24


def _to_naive(dt: datetime) -> datetime:
    return dt if dt.tzinfo is None else dt.replace(tzinfo=None)


def cleanup_expired_guest_sessions(db: Session) -> dict:
    """Delete session-scoped data for guest sessions idle > _CUTOFF_HOURS.

    Preserves ChatMessage rows (dataset) and ChatSession metadata rows.
    Returns {"cleaned_sessions": int, "errors": list[str]}.
    """
    from app.memory.models import (
        ChatSession,
        DailyMessageUsage,
        DailyTtsUsage,
        InitiativeEvalLog,
        NotificationLog,
        OpenLoop,
        ScheduledTask,
        Setting,
    )

    cutoff = _to_naive(datetime.now(timezone.utc)) - timedelta(hours=_CUTOFF_HOURS)

    all_guest_sessions = db.exec(
        select(ChatSession).where(col(ChatSession.id).like("guest:%"))
    ).all()
    expired = [s for s in all_guest_sessions if _to_naive(s.updated_at) < cutoff]

    if not expired:
        write_log(
            level="INFO",
            module="guest_cleanup",
            event="guest_session_cleanup_done",
            payload={"cleaned_sessions": 0},
        )
        return {"cleaned_sessions": 0, "errors": []}

    session_ids = [s.id for s in expired]
    errors: list[str] = []

    try:
        for sid in session_ids:
            db.exec(sql_delete(Setting).where(Setting.session_id == sid))  # type: ignore[arg-type]
            db.exec(sql_delete(OpenLoop).where(OpenLoop.session_id == sid))  # type: ignore[arg-type]
            db.exec(sql_delete(NotificationLog).where(NotificationLog.session_id == sid))  # type: ignore[arg-type]
            db.exec(sql_delete(InitiativeEvalLog).where(InitiativeEvalLog.session_id == sid))  # type: ignore[arg-type]
            db.exec(sql_delete(ScheduledTask).where(ScheduledTask.session_id == sid))  # type: ignore[arg-type]

        for sid in session_ids:
            row = db.get(DailyMessageUsage, sid)
            if row:
                db.delete(row)
            tts_row = db.get(DailyTtsUsage, sid)
            if tts_row:
                db.delete(tts_row)

        db.commit()
    except Exception as exc:
        errors.append(str(exc))

    cleaned = len(session_ids)
    write_log(
        level="INFO" if not errors else "WARN",
        module="guest_cleanup",
        event="guest_session_cleanup_done",
        payload={"cleaned_sessions": cleaned, "errors": errors or None},
    )
    return {"cleaned_sessions": cleaned, "errors": errors}


def _run_cleanup_sync() -> None:
    try:
        with Session(engine) as db:
            cleanup_expired_guest_sessions(db)
    except Exception as exc:
        write_log(
            level="ERROR",
            module="guest_cleanup",
            event="guest_session_cleanup_error",
            payload={"error": str(exc)},
        )


async def guest_session_cleanup_loop() -> None:
    """Async loop started from main.py on_startup. Runs immediately then every 24h."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_cleanup_sync)
    while True:
        await asyncio.sleep(_INTERVAL_HOURS * 3600)
        await loop.run_in_executor(None, _run_cleanup_sync)


def start_guest_session_cleanup_loop(loop: asyncio.AbstractEventLoop) -> None:
    loop.create_task(guest_session_cleanup_loop())
    write_log(
        level="INFO",
        module="guest_cleanup",
        event="guest_session_cleanup_started",
        payload={"cutoff_hours": _CUTOFF_HOURS, "interval_hours": _INTERVAL_HOURS},
    )

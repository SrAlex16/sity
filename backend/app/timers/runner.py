"""ScheduledTaskRunner — polls ScheduledTask table and fires due timers.

The runner loop is started from main.py on_startup as an asyncio task.
It wakes up every poll_interval_seconds, marks due tasks as fired,
persists the timer message to ChatMessage history, and publishes a
proactive_message SSE event to the owning session.

fire_pending_once() is the unit-testable core; the async loop calls it
through run_in_executor to avoid blocking the event loop on DB I/O.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import ChatMessage, ScheduledTask
from app.notifications.dispatcher import dispatch
from app.notifications.fact import NotificationFact
from app.trace.logger import write_log


def fire_pending_once(db_session: Session) -> list[str]:
    """Query and fire all due timers. Returns list of fired timer IDs.

    Safe to call from any thread. The db_session must be an open Session.
    After marking timers fired, routes each via dispatcher (SSE if subscriber
    active, Web Push if PushSubscription exists, pending otherwise).
    """
    now = datetime.now(timezone.utc)

    stmt = select(ScheduledTask).where(
        ScheduledTask.fired_at == None,      # noqa: E711
        ScheduledTask.cancelled_at == None,  # noqa: E711
    )
    all_pending = list(db_session.exec(stmt))

    due = []
    for task in all_pending:
        fa = task.fires_at
        if fa.tzinfo is None:
            fa = fa.replace(tzinfo=timezone.utc)
        if fa <= now:
            due.append(task)

    if not due:
        return []

    # Capture notification data before commit (SQLAlchemy post-commit expiry)
    to_notify = [(t.id, t.session_id, t.message) for t in due]

    for task in due:
        task.fired_at = now
        db_session.add(task)
        db_session.add(ChatMessage(
            session_id=task.session_id,
            role="sity",
            text=task.message,
            trace_id=f"tmr_{task.id}",
        ))

    db_session.commit()

    fired_ids = []
    for timer_id, session_id, message in to_notify:
        fact = NotificationFact(
            session_id=session_id,
            notification_type="timer_fired",
            # Deterministic fact_id: if the runner somehow sees the same timer twice,
            # the dispatcher dedup catches it before a duplicate notification is sent.
            fact_id=f"timer:{timer_id}",
            payload={
                "title": "⏰ Sity",
                "body": message,
                "url": "/",
                "urgent": True,
                "timer_id": timer_id,  # passed through to SSE consumer by dispatcher
            },
            urgency="high",
        )
        dispatch(fact, db_session)
        write_log(
            level="INFO",
            module="timers",
            event="timer_fired",
            payload={"timer_id": timer_id, "session_id": session_id},
        )
        fired_ids.append(timer_id)

    return fired_ids


def _poll_once_sync() -> None:
    """Synchronous wrapper used by run_in_executor."""
    try:
        with Session(engine) as db_session:
            fired = fire_pending_once(db_session)
            if fired:
                write_log(
                    level="INFO",
                    module="timers",
                    event="timer_poll_fired",
                    payload={"count": len(fired), "timer_ids": fired},
                )
    except Exception as exc:
        write_log(
            level="ERROR",
            module="timers",
            event="timer_poll_error",
            payload={"error": str(exc)},
        )


async def scheduled_task_runner_loop(poll_interval_seconds: int = 5) -> None:
    """Async loop started from main.py on_startup. Runs forever."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(poll_interval_seconds)
        await loop.run_in_executor(None, _poll_once_sync)


def start_runner(loop: asyncio.AbstractEventLoop) -> None:
    """Start the runner loop as an asyncio task. Called from main.py on_startup."""
    from app.settings.config_loader import load_default_config
    cfg = load_default_config()
    poll_interval = int(cfg.get("timers", {}).get("poll_interval_seconds", 5))
    loop.create_task(scheduled_task_runner_loop(poll_interval))
    write_log(
        level="INFO",
        module="timers",
        event="timer_runner_started",
        payload={"poll_interval_seconds": poll_interval},
    )

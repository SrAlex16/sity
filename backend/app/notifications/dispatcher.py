"""Notification dispatcher — the single decision point for all notifications.

Responsibilities (§1.2 of docs/notifications-architecture.md):
1. Deduplication  — same fact_id already delivered in dedup_window_hours → discard
2. Rate limiting  — per-type limits from default_config.yaml § notifications
3. Channel routing — SSE (if subscriber active) → Web Push → pending
4. Persistence    — writes NotificationLog after every routing decision

Called synchronously from thread-pool contexts (run_in_executor), same
pattern as timers/runner.py::fire_pending_once(). NOT an async function.

GC: notifications_gc_loop() is a separate asyncio coroutine started
from main.py on_startup that periodically purges old NotificationLog rows.
Decision to keep GC separate from realtime_events._gc_loop: different TTL
domain, avoids coupling the realtime_events module to notifications.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlmodel import Session, col, select

from app.core.realtime_events import get_subscriber_state, publish_session_event_sync
from app.memory.db import engine
from app.memory.models import NotificationLog, PushSubscription, utc_now
from app.notifications.fact import DispatchResult, NotificationFact
from app.notifications.push import send_push
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    return load_default_config().get("notifications", {})


def _utc_today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _persist(
    fact: NotificationFact,
    channel: str,
    status: str,
    db: Session,
    delivered_at: Optional[datetime] = None,
    push_error: Optional[str] = None,
) -> NotificationLog:
    entry = NotificationLog(
        session_id=fact.session_id,
        notification_type=fact.notification_type,
        fact_id=fact.fact_id,
        payload_json=json.dumps(fact.payload, ensure_ascii=False),
        delivery_channel=channel,
        delivery_status=status,
        delivered_at=delivered_at,
        push_error=push_error,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Step 1: Deduplication
# ---------------------------------------------------------------------------

def _is_duplicate(fact: NotificationFact, db: Session, dedup_hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=dedup_hours)
    hit = db.exec(
        select(NotificationLog).where(
            NotificationLog.session_id == fact.session_id,
            NotificationLog.fact_id == fact.fact_id,
            NotificationLog.created_at >= cutoff,
            NotificationLog.delivery_status != "failed",
        )
    ).first()
    return hit is not None


# ---------------------------------------------------------------------------
# Step 2: Rate limiting
# ---------------------------------------------------------------------------

def _rate_limit_reason(fact: NotificationFact, db: Session, cfg: dict) -> Optional[str]:
    """Returns a reason string if the fact should be rate-limited, else None."""
    ntype = fact.notification_type

    if ntype == "proactive_initiative":
        max_pd = int(cfg.get("max_proactive_per_day_user", 1))
        count = len(db.exec(
            select(NotificationLog).where(
                NotificationLog.session_id == fact.session_id,
                NotificationLog.notification_type == "proactive_initiative",
                NotificationLog.created_at >= _utc_today_start(),
                NotificationLog.delivery_status != "failed",
            )
        ).all())
        if count >= max_pd:
            return f"max_proactive_per_day_exceeded ({count}/{max_pd})"

    elif ntype == "external_event":
        max_pd = int(cfg.get("max_external_events_per_day_user", 20))
        count = len(db.exec(
            select(NotificationLog).where(
                NotificationLog.session_id == fact.session_id,
                NotificationLog.notification_type == "external_event",
                NotificationLog.created_at >= _utc_today_start(),
                NotificationLog.delivery_status != "failed",
            )
        ).all())
        if count >= max_pd:
            return f"max_external_events_per_day_exceeded ({count}/{max_pd})"

    elif ntype == "recurrent_task":
        cooldown_min = int(cfg.get("recurrent_task_cooldown_minutes", 60))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_min)
        last = db.exec(
            select(NotificationLog).where(
                NotificationLog.session_id == fact.session_id,
                NotificationLog.notification_type == "recurrent_task",
                NotificationLog.created_at >= cutoff,
                NotificationLog.delivery_status != "failed",
            )
        ).first()
        if last:
            return "recurrent_task_cooldown_active"

    # timer_fired, background_result, chat_response: no rate limit (user-triggered)
    return None


# ---------------------------------------------------------------------------
# Step 3: Channel routing
# ---------------------------------------------------------------------------

def _choose_channel(fact: NotificationFact, db: Session) -> str:
    """Returns "sse" | "sse+push" | "push" | "pending" | "guest_drop"."""
    state = get_subscriber_state(fact.session_id)
    is_guest = fact.session_id.startswith("guest:")

    if state == "visible":
        return "sse"

    if state == "background":
        # Guests have no push subscriptions — SSE-only regardless of visibility.
        return "sse" if is_guest else "sse+push"

    # state == "none"
    if is_guest:
        return "guest_drop"

    sub = db.exec(
        select(PushSubscription).where(
            PushSubscription.session_id == fact.session_id,
            col(PushSubscription.is_active) == True,  # noqa: E712
        )
    ).first()
    return "push" if sub else "pending"


# ---------------------------------------------------------------------------
# Push delivery helpers
# ---------------------------------------------------------------------------

def _deliver_push_best_effort(fact: NotificationFact, db: Session) -> None:
    """Send push alongside SSE (background-tab mode). Failures are WARN-only."""
    subs = list(db.exec(
        select(PushSubscription).where(
            PushSubscription.session_id == fact.session_id,
            col(PushSubscription.is_active) == True,  # noqa: E712
        )
    ).all())

    for sub in subs:
        result = send_push(sub, fact.payload)
        if result.success:
            sub.last_used_at = utc_now()
            db.add(sub)
            write_log(
                level="INFO",
                module="notifications",
                event="delivery_push_ok",
                session_id=fact.session_id,
                payload={
                    "notification_type": fact.notification_type,
                    "endpoint_domain": urlparse(sub.endpoint).netloc,
                    "mode": "sse+push",
                },
            )
        else:
            if result.subscription_expired:
                sub.is_active = False
                db.add(sub)
                write_log(
                    level="WARN",
                    module="notifications",
                    event="push_subscription_expired",
                    session_id=fact.session_id,
                    payload={"endpoint_domain": urlparse(sub.endpoint).netloc},
                )
            write_log(
                level="WARN",
                module="notifications",
                event="delivery_push_failed_best_effort",
                session_id=fact.session_id,
                payload={
                    "notification_type": fact.notification_type,
                    "error": result.error,
                    "subscription_expired": result.subscription_expired,
                },
            )
    if subs:
        db.commit()


def _deliver_push(fact: NotificationFact, db: Session) -> DispatchResult:
    subs = list(db.exec(
        select(PushSubscription).where(
            PushSubscription.session_id == fact.session_id,
            col(PushSubscription.is_active) == True,  # noqa: E712
        )
    ).all())

    any_success = False

    for sub in subs:
        result = send_push(sub, fact.payload)
        if result.success:
            sub.last_used_at = utc_now()
            db.add(sub)
            any_success = True
            write_log(
                level="INFO",
                module="notifications",
                event="delivery_push_ok",
                session_id=fact.session_id,
                payload={
                    "notification_type": fact.notification_type,
                    "endpoint_domain": urlparse(sub.endpoint).netloc,
                },
            )
        else:
            if result.subscription_expired:
                sub.is_active = False
                db.add(sub)
                write_log(
                    level="WARN",
                    module="notifications",
                    event="push_subscription_expired",
                    session_id=fact.session_id,
                    payload={"endpoint_domain": urlparse(sub.endpoint).netloc},
                )
            write_log(
                level="WARN",
                module="notifications",
                event="delivery_push_failed",
                session_id=fact.session_id,
                payload={
                    "notification_type": fact.notification_type,
                    "http_status": result.error,
                    "subscription_expired": result.subscription_expired,
                },
            )
    db.commit()

    if any_success:
        entry = _persist(fact, "push", "delivered", db, delivered_at=utc_now())
        return DispatchResult(channel="push", notification_id=entry.id)

    # All pushes failed → fall back to pending
    entry = _persist(fact, "pending", "pending", db)
    return DispatchResult(channel="pending", notification_id=entry.id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dispatch(fact: NotificationFact, db: Session) -> DispatchResult:
    """Route one NotificationFact through all 4 dispatcher responsibilities.

    Synchronous. Safe to call from any thread (same contract as
    publish_session_event_sync and fire_pending_once).
    """
    cfg = _cfg()

    write_log(
        level="INFO",
        module="notifications",
        event="fact_produced",
        session_id=fact.session_id,
        payload={
            "type": fact.notification_type,
            "fact_id": fact.fact_id,
            "urgency": fact.urgency,
            "subtype": fact.subtype,
        },
    )

    # 1. Deduplication
    dedup_hours = int(cfg.get("dedup_window_hours", 24))
    if _is_duplicate(fact, db, dedup_hours):
        write_log(
            level="INFO",
            module="notifications",
            event="fact_discarded_duplicate",
            session_id=fact.session_id,
            payload={"fact_id": fact.fact_id, "type": fact.notification_type},
        )
        return DispatchResult(discarded=True, reason="duplicate")

    # 2. Rate limiting
    rl_reason = _rate_limit_reason(fact, db, cfg)
    if rl_reason:
        write_log(
            level="INFO",
            module="notifications",
            event="fact_discarded_rate_limit",
            session_id=fact.session_id,
            payload={"type": fact.notification_type, "reason": rl_reason},
        )
        return DispatchResult(discarded=True, reason=f"rate_limited:{rl_reason}")

    # 3. Channel routing
    channel = _choose_channel(fact, db)

    if channel == "guest_drop":
        write_log(
            level="INFO",
            module="notifications",
            event="notification_dropped_guest",
            session_id=fact.session_id,
            payload={"type": fact.notification_type},
        )
        return DispatchResult(discarded=True, reason="guest_no_sse")

    write_log(
        level="INFO",
        module="notifications",
        event="routing_decision",
        session_id=fact.session_id,
        payload={"type": fact.notification_type, "channel": channel},
    )

    # 4. Deliver + persist
    if channel in ("sse", "sse+push"):
        # Standard keys are mapped to fixed SSE fields; extra keys (e.g. timer_id,
        # tool_name, job_id) are passed through so frontend consumers can use them.
        # full_text: when present, used as SSE text so the chat bubble shows the
        # complete AI response; push still gets the shorter body snippet.
        _STANDARD = frozenset({"title", "body", "url", "urgent", "full_text"})
        sse_event: dict = {
            "type": "proactive_message",
            "text": fact.payload.get("full_text") or fact.payload.get("body", ""),
            "subtype": fact.notification_type,
            **{k: v for k, v in fact.payload.items() if k not in _STANDARD},
        }
        if fact.subtype:
            sse_event["source"] = fact.subtype
        publish_session_event_sync(fact.session_id, sse_event)
        entry = _persist(fact, channel, "delivered", db, delivered_at=utc_now())
        write_log(
            level="INFO",
            module="notifications",
            event="delivery_sse_ok",
            session_id=fact.session_id,
            payload={"notification_id": entry.id, "type": fact.notification_type, "channel": channel},
        )
        if channel == "sse+push":
            _deliver_push_best_effort(fact, db)
        return DispatchResult(channel=channel, notification_id=entry.id)

    if channel == "push":
        return _deliver_push(fact, db)

    # pending
    entry = _persist(fact, "pending", "pending", db)
    return DispatchResult(channel="pending", notification_id=entry.id)


# ---------------------------------------------------------------------------
# GC
# ---------------------------------------------------------------------------

def purge_old_notification_logs(ttl_days: int = 30) -> int:
    """Delete NotificationLog rows older than ttl_days. Returns count deleted."""
    from sqlalchemy import delete as sa_delete

    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    with Session(engine) as db:
        result = db.exec(  # type: ignore[call-overload]
            sa_delete(NotificationLog).where(col(NotificationLog.created_at) < cutoff)
        )
        db.commit()
        return result.rowcount


async def notifications_gc_loop() -> None:
    """Async loop started from main.py on_startup. Purges old NotificationLog rows."""
    from app.settings.config_loader import load_default_config as _load

    while True:
        cfg = _load().get("notifications", {})
        gc_interval = int(cfg.get("gc_interval_seconds", 600))
        ttl_days = int(cfg.get("notification_log_ttl_days", 30))
        await asyncio.sleep(gc_interval)
        try:
            deleted = purge_old_notification_logs(ttl_days)
            if deleted:
                write_log(
                    level="INFO",
                    module="notifications",
                    event="notification_log_gc",
                    payload={"deleted": deleted, "ttl_days": ttl_days},
                )
        except Exception as exc:  # noqa: BLE001
            write_log(
                level="ERROR",
                module="notifications",
                event="notification_log_gc_error",
                payload={"error": str(exc)},
            )

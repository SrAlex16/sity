"""Paso 3 — timer → dispatcher integration tests.

Verifies that fire_pending_once() routes timer notifications through the
dispatcher (not via direct publish_session_event_sync), and that all three
delivery channels work correctly:

  SSE    — subscriber active → delivered via SSE
  Push   — no SSE, PushSubscription active → delivered via Web Push
  Pending — no SSE, no Push → stored as pending in NotificationLog

Also verifies the deterministic fact_id prevents double-delivery if
fire_pending_once is somehow called twice for the same timer.
"""
from __future__ import annotations

import uuid as _uuid_mod
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import NotificationLog, PushSubscription, ScheduledTask
from app.notifications.push import PushResult
from app.timers.runner import fire_pending_once


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _due_task(db: Session, session_id: str, message: str = "Timer!") -> ScheduledTask:
    from datetime import datetime, timedelta, timezone
    task = ScheduledTask(
        id=f"tmr_{_uid()}",
        session_id=session_id,
        fires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        message=message,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _add_push_sub(session_id: str, db: Session) -> PushSubscription:
    sub = PushSubscription(
        session_id=session_id,
        endpoint=f"https://fcm.googleapis.com/fcm/send/{_uid()}",
        p256dh="test_p256dh==",
        auth="test_auth==",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def _notification_logs(session_id: str) -> list[NotificationLog]:
    with Session(engine) as db:
        return list(db.exec(
            select(NotificationLog).where(NotificationLog.session_id == session_id)
        ).all())


_PATCH_SSE = "app.notifications.dispatcher.has_active_subscriber"
_PATCH_PUSH = "app.notifications.dispatcher.send_push"


# ---------------------------------------------------------------------------
# Timer routes via dispatcher (not direct publish_session_event_sync)
# ---------------------------------------------------------------------------

class TestTimerUsesDispatcher:
    def test_dispatch_called_for_due_timer(self) -> None:
        """fire_pending_once calls dispatch(), not publish_session_event_sync directly."""
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id

        dispatched_facts = []

        def _capture(fact, db):
            dispatched_facts.append(fact)
            from app.notifications.fact import DispatchResult
            return DispatchResult(channel="sse", notification_id=1)

        with patch("app.timers.runner.dispatch", side_effect=_capture):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        assert any(f.fact_id == f"timer:{timer_id}" for f in dispatched_facts)

    def test_fact_properties_are_correct(self) -> None:
        sid = f"user:test_{_uid()}"
        msg = "Recuerda tomar el medicamento"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid, message=msg)
            timer_id = task.id

        dispatched = []

        def _capture(fact, db):
            dispatched.append(fact)
            from app.notifications.fact import DispatchResult
            return DispatchResult(channel="pending", notification_id=42)

        with patch("app.timers.runner.dispatch", side_effect=_capture):
            with Session(engine) as db:
                fire_pending_once(db)

        facts = [f for f in dispatched if f.fact_id == f"timer:{timer_id}"]
        assert len(facts) == 1
        f = facts[0]
        assert f.session_id == sid
        assert f.notification_type == "timer_fired"
        assert f.urgency == "high"
        assert f.payload["body"] == msg
        assert f.payload["timer_id"] == timer_id
        assert f.payload["urgent"] is True


# ---------------------------------------------------------------------------
# SSE path — subscriber active
# ---------------------------------------------------------------------------

class TestTimerSSEPath:
    def test_timer_delivered_via_sse_when_subscriber_active(self) -> None:
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id

        with patch(_PATCH_SSE, return_value=True):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        logs = _notification_logs(sid)
        timer_logs = [l for l in logs if l.fact_id == f"timer:{timer_id}"]
        assert len(timer_logs) == 1
        assert timer_logs[0].delivery_channel == "sse"
        assert timer_logs[0].delivery_status == "delivered"

    def test_sse_event_includes_timer_id(self) -> None:
        """SSE consumer must receive timer_id in the event payload."""
        sid = f"user:test_{_uid()}"
        sse_events = []

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id

        def _capture_sse(session_id, event):
            sse_events.append((session_id, event))

        with patch(_PATCH_SSE, return_value=True), \
             patch("app.notifications.dispatcher.publish_session_event_sync", side_effect=_capture_sse):
            with Session(engine) as db:
                fire_pending_once(db)

        our_events = [e for _, e in sse_events if e.get("timer_id") == timer_id]
        assert len(our_events) == 1
        evt = our_events[0]
        assert evt["type"] == "proactive_message"
        assert evt["subtype"] == "timer_fired"


# ---------------------------------------------------------------------------
# Web Push path — no SSE, PushSubscription active
# ---------------------------------------------------------------------------

class TestTimerWebPushPath:
    def test_timer_delivered_via_push_when_no_sse(self) -> None:
        """THE key milestone: timer fires while PWA is closed → arrives via Web Push."""
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id
            _add_push_sub(sid, db)

        with patch(_PATCH_SSE, return_value=False), \
             patch(_PATCH_PUSH, return_value=PushResult(success=True)):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        logs = _notification_logs(sid)
        timer_logs = [l for l in logs if l.fact_id == f"timer:{timer_id}"]
        assert len(timer_logs) == 1
        assert timer_logs[0].delivery_channel == "push"
        assert timer_logs[0].delivery_status == "delivered"

    def test_push_payload_includes_urgency(self) -> None:
        """Push notification must mark timer_fired as urgent (vibration in browser)."""
        sid = f"user:test_{_uid()}"
        push_calls = []

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            _add_push_sub(sid, db)

        def _capture_push(sub, payload):
            push_calls.append(payload)
            return PushResult(success=True)

        with patch(_PATCH_SSE, return_value=False), \
             patch(_PATCH_PUSH, side_effect=_capture_push):
            with Session(engine) as db:
                fire_pending_once(db)

        assert len(push_calls) == 1
        assert push_calls[0].get("urgent") is True

    def test_push_410_falls_to_pending(self) -> None:
        """If the push service returns 410, timer notification falls back to pending."""
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id
            sub = _add_push_sub(sid, db)

        gone = PushResult(success=False, error="410 Gone", subscription_expired=True)
        with patch(_PATCH_SSE, return_value=False), \
             patch(_PATCH_PUSH, return_value=gone):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        # Subscription must be deactivated — re-query in a fresh session
        with Session(engine) as db:
            refreshed_sub = db.get(PushSubscription, sub.id)
            assert refreshed_sub is not None
            assert refreshed_sub.is_active is False

        # Notification stored as pending
        logs = _notification_logs(sid)
        timer_logs = [l for l in logs if l.fact_id == f"timer:{timer_id}"]
        assert any(l.delivery_status == "pending" for l in timer_logs)


# ---------------------------------------------------------------------------
# Pending fallback — no SSE, no PushSubscription
# ---------------------------------------------------------------------------

class TestTimerPendingFallback:
    def test_timer_stored_as_pending_when_no_channel(self) -> None:
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id

        with patch(_PATCH_SSE, return_value=False):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        logs = _notification_logs(sid)
        timer_logs = [l for l in logs if l.fact_id == f"timer:{timer_id}"]
        assert len(timer_logs) == 1
        assert timer_logs[0].delivery_channel == "pending"
        assert timer_logs[0].delivery_status == "pending"
        assert timer_logs[0].notification_type == "timer_fired"


# ---------------------------------------------------------------------------
# Deterministic fact_id prevents double delivery
# ---------------------------------------------------------------------------

class TestTimerFactIdDedup:
    def test_same_timer_dispatched_twice_delivers_once(self) -> None:
        """If fire_pending_once were called twice before fired_at is persisted,
        the dispatcher's dedup (fact_id='timer:{id}') prevents double delivery."""
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            task = _due_task(db, session_id=sid)
            timer_id = task.id

        # Simulate calling dispatch twice for the same fact_id
        from app.notifications.dispatcher import dispatch
        from app.notifications.fact import NotificationFact

        fact = NotificationFact(
            session_id=sid,
            notification_type="timer_fired",
            fact_id=f"timer:{timer_id}",
            payload={"title": "⏰", "body": "msg", "url": "/", "urgent": True},
            urgency="high",
        )

        with patch(_PATCH_SSE, return_value=True):
            with Session(engine) as db:
                r1 = dispatch(fact, db)
                r2 = dispatch(fact, db)

        assert not r1.discarded
        assert r2.discarded
        assert r2.reason == "duplicate"

        # Only one NotificationLog row
        logs = _notification_logs(sid)
        timer_logs = [l for l in logs if l.fact_id == f"timer:{timer_id}"]
        assert len(timer_logs) == 1

    def test_no_rate_limit_on_multiple_different_timers(self) -> None:
        """timer_fired has no rate limit — many timers can fire for the same session."""
        sid = f"user:test_{_uid()}"

        with Session(engine) as db:
            tasks = [_due_task(db, session_id=sid) for _ in range(5)]
            timer_ids = [t.id for t in tasks]

        with patch(_PATCH_SSE, return_value=True):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        for tid in timer_ids:
            assert tid in fired

        logs = _notification_logs(sid)
        for tid in timer_ids:
            tl = [l for l in logs if l.fact_id == f"timer:{tid}"]
            assert len(tl) == 1
            assert tl[0].delivery_status == "delivered"

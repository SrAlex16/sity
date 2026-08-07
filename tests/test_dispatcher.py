"""Tests for notifications/dispatcher.py — Paso 2.

Covers §7 validation cases: 1, 4, 5, 6, 8.

Case 1  — Isolation: a fact for user:1 never appears in user:2's NotificationLog.
Case 4  — Rate limiting: N+1th proactive_initiative is discarded.
Case 5  — Fallback SSE → Push → pending.
Case 6  — PushSubscription 410 Gone → is_active=False → falls to pending.
Case 8  — Deduplication: same fact_id within dedup window is discarded.

All NotificationFacts are synthetic (not produced by real timers or jobs).
pywebpush.webpush and has_active_subscriber are mocked — no network calls.
"""
from __future__ import annotations

import uuid as _uuid_mod
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import NotificationLog, PushSubscription
from app.notifications.dispatcher import dispatch
from app.notifications.fact import DispatchResult, NotificationFact
from app.notifications.push import PushResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _session_id() -> str:
    return f"user:test_{_uid()}"


def _fact(
    session_id: str,
    *,
    notification_type: str = "background_result",
    fact_id: str | None = None,
    urgency: str = "medium",
    subtype: str | None = None,
) -> NotificationFact:
    return NotificationFact(
        session_id=session_id,
        notification_type=notification_type,
        fact_id=fact_id or f"test:{_uid()}",
        payload={"title": "Test", "body": "Hecho de prueba", "url": "/", "urgent": False},
        urgency=urgency,
        subtype=subtype,
    )


def _add_push_sub(session_id: str, db: Session, endpoint: str | None = None) -> PushSubscription:
    sub = PushSubscription(
        session_id=session_id,
        endpoint=endpoint or f"https://fcm.googleapis.com/fcm/send/{_uid()}",
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


# Patch target for SSE subscriber state (returns "visible" | "background" | "none")
_PATCH_SSE = "app.notifications.dispatcher.get_subscriber_state"
# Patch at the dispatcher's local binding (from app.notifications.push import send_push)
_PATCH_PUSH = "app.notifications.dispatcher.send_push"


# ---------------------------------------------------------------------------
# Case 8 — Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_same_fact_id_discarded_second_time(self) -> None:
        sid = _session_id()
        shared_fact_id = f"timer:fixed_{_uid()}"
        fact = _fact(sid, notification_type="timer_fired", fact_id=shared_fact_id)

        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            r1 = dispatch(fact, db)
            r2 = dispatch(_fact(sid, notification_type="timer_fired", fact_id=shared_fact_id), db)

        assert not r1.discarded
        assert r1.channel == "sse"
        assert r2.discarded
        assert r2.reason == "duplicate"

    def test_different_fact_ids_both_delivered(self) -> None:
        sid = _session_id()
        f1 = _fact(sid, notification_type="background_result")
        f2 = _fact(sid, notification_type="background_result")

        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            r1 = dispatch(f1, db)
            r2 = dispatch(f2, db)

        assert not r1.discarded
        assert not r2.discarded

    def test_same_fact_id_different_sessions_both_delivered(self) -> None:
        """Dedup is per session — same fact_id for two users is OK."""
        sid_a = _session_id()
        sid_b = _session_id()
        shared_fid = f"ext:{_uid()}"

        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            ra = dispatch(_fact(sid_a, fact_id=shared_fid), db)
            rb = dispatch(_fact(sid_b, fact_id=shared_fid), db)

        assert not ra.discarded
        assert not rb.discarded


# ---------------------------------------------------------------------------
# Case 4 — Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_proactive_initiative_rate_limited_after_max(self) -> None:
        """Default max_proactive_per_day_user=1 → second initiative discarded."""
        sid = _session_id()

        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            r1 = dispatch(_fact(sid, notification_type="proactive_initiative"), db)
            r2 = dispatch(_fact(sid, notification_type="proactive_initiative"), db)

        assert not r1.discarded
        assert r2.discarded
        assert "rate_limited" in r2.reason
        assert "max_proactive_per_day" in r2.reason

    def test_timer_fired_not_rate_limited(self) -> None:
        """timer_fired has no rate limit — multiple can be dispatched."""
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            results = [
                dispatch(_fact(sid, notification_type="timer_fired"), db)
                for _ in range(5)
            ]
        assert all(not r.discarded for r in results)

    def test_external_event_rate_limited_after_max(self) -> None:
        """max_external_events_per_day_user=20 → 21st discarded."""
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            results = [
                dispatch(_fact(sid, notification_type="external_event"), db)
                for _ in range(21)
            ]
        # First 20 pass, 21st is rate-limited
        passed = [r for r in results if not r.discarded]
        limited = [r for r in results if r.discarded]
        assert len(passed) == 20
        assert len(limited) == 1
        assert "max_external_events_per_day" in limited[0].reason

    def test_recurrent_task_cooldown(self) -> None:
        """Second recurrent_task within cooldown window is discarded."""
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            r1 = dispatch(_fact(sid, notification_type="recurrent_task"), db)
            r2 = dispatch(_fact(sid, notification_type="recurrent_task"), db)

        assert not r1.discarded
        assert r2.discarded
        assert "rate_limited" in r2.reason
        assert "cooldown" in r2.reason

    def test_rate_limit_does_not_cross_sessions(self) -> None:
        """Rate limit for user:A doesn't affect user:B."""
        sid_a = _session_id()
        sid_b = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            # Exhaust user:A's limit
            dispatch(_fact(sid_a, notification_type="proactive_initiative"), db)
            # user:B should still pass
            rb = dispatch(_fact(sid_b, notification_type="proactive_initiative"), db)

        assert not rb.discarded


# ---------------------------------------------------------------------------
# Case 5 — Fallback SSE → Push → pending
# ---------------------------------------------------------------------------

class TestChannelFallback:
    def test_sse_when_subscriber_active(self) -> None:
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            result = dispatch(_fact(sid), db)

        assert result.channel == "sse"
        logs = _notification_logs(sid)
        assert len(logs) == 1
        assert logs[0].delivery_channel == "sse"
        assert logs[0].delivery_status == "delivered"

    def test_push_when_no_sse_but_subscription_exists(self) -> None:
        sid = _session_id()
        with Session(engine) as db:
            _add_push_sub(sid, db)
            with patch(_PATCH_SSE, return_value="none"), \
                 patch(_PATCH_PUSH, return_value=PushResult(success=True)):
                result = dispatch(_fact(sid), db)

        assert result.channel == "push"
        logs = _notification_logs(sid)
        assert any(log.delivery_channel == "push" and log.delivery_status == "delivered" for log in logs)

    def test_pending_when_no_sse_no_subscription(self) -> None:
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="none"):
            result = dispatch(_fact(sid), db)

        assert result.channel == "pending"
        logs = _notification_logs(sid)
        assert len(logs) == 1
        assert logs[0].delivery_channel == "pending"
        assert logs[0].delivery_status == "pending"

    def test_sse_takes_priority_over_push(self) -> None:
        """Even with an active PushSubscription, SSE wins when subscriber is connected."""
        sid = _session_id()
        with Session(engine) as db:
            _add_push_sub(sid, db)
            with patch(_PATCH_SSE, return_value="visible"):
                result = dispatch(_fact(sid), db)

        assert result.channel == "sse"


# ---------------------------------------------------------------------------
# Case 6 — PushSubscription 410 Gone → is_active=False → pending
# ---------------------------------------------------------------------------

class TestPush410Gone:
    def test_410_marks_subscription_inactive_and_falls_to_pending(self) -> None:
        sid = _session_id()
        with Session(engine) as db:
            sub = _add_push_sub(sid, db)
            sub_id = sub.id

            gone_result = PushResult(success=False, error="410 Gone", subscription_expired=True)
            with patch(_PATCH_SSE, return_value="none"), \
                 patch(_PATCH_PUSH, return_value=gone_result):
                result = dispatch(_fact(sid), db)

            # Subscription must be inactive
            db.refresh(sub)
            assert sub.is_active is False

        assert result.channel == "pending"
        logs = _notification_logs(sid)
        assert any(log.delivery_status == "pending" for log in logs)

    def test_410_does_not_retry_with_same_subscription(self) -> None:
        """After a 410, subscription is inactive → next dispatch goes to pending directly."""
        sid = _session_id()
        with Session(engine) as db:
            _add_push_sub(sid, db)

            gone_result = PushResult(success=False, error="410 Gone", subscription_expired=True)
            with patch(_PATCH_SSE, return_value="none"), \
                 patch(_PATCH_PUSH, return_value=gone_result) as mock_send:
                dispatch(_fact(sid), db)  # triggers 410
                mock_send.reset_mock()
                # Second dispatch: subscription is now inactive → push never called
                result2 = dispatch(_fact(sid), db)
                assert mock_send.call_count == 0

        assert result2.channel == "pending"

    def test_non_410_push_failure_also_falls_to_pending(self) -> None:
        """Any push failure (not just 410) causes fallback to pending."""
        sid = _session_id()
        with Session(engine) as db:
            sub = _add_push_sub(sid, db)

            fail_result = PushResult(success=False, error="503 Service Unavailable", subscription_expired=False)
            with patch(_PATCH_SSE, return_value="none"), \
                 patch(_PATCH_PUSH, return_value=fail_result):
                result = dispatch(_fact(sid), db)

            # Subscription stays active (not a 410)
            db.refresh(sub)
            assert sub.is_active is True

        assert result.channel == "pending"


# ---------------------------------------------------------------------------
# Case 1 — Session isolation
# ---------------------------------------------------------------------------

class TestIsolation:
    def test_notification_for_user1_not_in_user2_log(self) -> None:
        sid_a = _session_id()
        sid_b = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            dispatch(_fact(sid_a), db)

        logs_b = _notification_logs(sid_b)
        assert len(logs_b) == 0

    def test_notification_for_user1_in_user1_log(self) -> None:
        sid_a = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            result = dispatch(_fact(sid_a), db)

        logs_a = _notification_logs(sid_a)
        assert len(logs_a) == 1
        assert logs_a[0].session_id == sid_a
        assert logs_a[0].id == result.notification_id

    def test_push_deactivation_scoped_to_session(self) -> None:
        """410 from user:A's push does not affect user:B's subscription."""
        sid_a = _session_id()
        sid_b = _session_id()

        with Session(engine) as db:
            endpoint = f"https://fcm.test/{_uid()}"
            sub_a = _add_push_sub(sid_a, db, endpoint=endpoint + "_a")
            sub_b = _add_push_sub(sid_b, db, endpoint=endpoint + "_b")

            gone = PushResult(success=False, error="410", subscription_expired=True)
            with patch(_PATCH_SSE, return_value="none"), \
                 patch(_PATCH_PUSH, return_value=gone):
                dispatch(_fact(sid_a), db)

            db.refresh(sub_a)
            db.refresh(sub_b)
            assert sub_a.is_active is False
            assert sub_b.is_active is True


# ---------------------------------------------------------------------------
# Guest isolation
# ---------------------------------------------------------------------------

class TestGuestIsolation:
    def test_guest_with_sse_subscriber_gets_sse(self) -> None:
        sid = f"guest:{_uid()}"
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            result = dispatch(_fact(sid), db)
        assert result.channel == "sse"
        assert not result.discarded

    def test_guest_without_sse_is_dropped(self) -> None:
        sid = f"guest:{_uid()}"
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="none"):
            result = dispatch(_fact(sid), db)
        assert result.discarded
        assert result.reason == "guest_no_sse"
        # No NotificationLog row — guest drops are not persisted
        logs = _notification_logs(sid)
        assert len(logs) == 0

    def test_guest_never_gets_web_push_even_if_subscription_existed(self) -> None:
        """Defensive: even if a guest somehow had a PushSubscription, no push is sent."""
        sid = f"guest:{_uid()}"
        with Session(engine) as db:
            # Manually insert a PushSubscription for a guest (shouldn't happen via API)
            _add_push_sub(sid, db)
            with patch(_PATCH_SSE, return_value="none"), \
                 patch(_PATCH_PUSH) as mock_send:
                result = dispatch(_fact(sid), db)
                assert mock_send.call_count == 0
        assert result.discarded
        assert result.reason == "guest_no_sse"


# ---------------------------------------------------------------------------
# Background channel (sse+push)
# ---------------------------------------------------------------------------

class TestBackgroundChannel:
    def test_sse_plus_push_when_background(self) -> None:
        """Tab in background: deliver via SSE + best-effort push."""
        sid = _session_id()
        with Session(engine) as db:
            _add_push_sub(sid, db)
            with patch(_PATCH_SSE, return_value="background"), \
                 patch(_PATCH_PUSH, return_value=PushResult(success=True)):
                result = dispatch(_fact(sid), db)
        assert result.channel == "sse+push"
        assert not result.discarded
        logs = _notification_logs(sid)
        assert any(log.delivery_channel == "sse+push" and log.delivery_status == "delivered" for log in logs)

    def test_background_push_failure_does_not_break_sse_delivery(self) -> None:
        """Push failure in sse+push mode is best-effort — SSE still marked delivered."""
        sid = _session_id()
        with Session(engine) as db:
            _add_push_sub(sid, db)
            fail = PushResult(success=False, error="503", subscription_expired=False)
            with patch(_PATCH_SSE, return_value="background"), \
                 patch(_PATCH_PUSH, return_value=fail):
                result = dispatch(_fact(sid), db)
        assert result.channel == "sse+push"
        assert not result.discarded
        logs = _notification_logs(sid)
        assert any(log.delivery_status == "delivered" for log in logs)

    def test_background_no_push_sub_still_delivers_sse(self) -> None:
        """Background state without a push subscription: SSE still delivered."""
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="background"):
            result = dispatch(_fact(sid), db)
        assert result.channel == "sse+push"
        assert not result.discarded

    def test_guest_background_gets_sse_only(self) -> None:
        """Guests in background state get SSE-only — no push is attempted."""
        sid = f"guest:{_uid()}"
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="background"), \
             patch(_PATCH_PUSH) as mock_send:
            result = dispatch(_fact(sid), db)
            assert mock_send.call_count == 0
        assert result.channel == "sse"
        assert not result.discarded

    def test_visible_takes_sse_only_no_push(self) -> None:
        """Tab visible: only SSE, push is never called even with an active subscription."""
        sid = _session_id()
        with Session(engine) as db:
            _add_push_sub(sid, db)
            with patch(_PATCH_SSE, return_value="visible"), \
                 patch(_PATCH_PUSH) as mock_send:
                result = dispatch(_fact(sid), db)
                assert mock_send.call_count == 0
        assert result.channel == "sse"


# ---------------------------------------------------------------------------
# DispatchResult integrity
# ---------------------------------------------------------------------------

class TestDispatchResult:
    def test_result_contains_notification_id_on_delivery(self) -> None:
        sid = _session_id()
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            result = dispatch(_fact(sid), db)
        assert result.notification_id is not None
        assert isinstance(result.notification_id, int)

    def test_discarded_result_has_no_notification_id(self) -> None:
        sid = _session_id()
        shared_fid = f"dup:{_uid()}"
        with Session(engine) as db, \
             patch(_PATCH_SSE, return_value="visible"):
            dispatch(_fact(sid, fact_id=shared_fid), db)
            result = dispatch(_fact(sid, fact_id=shared_fid), db)
        assert result.discarded
        assert result.notification_id is None

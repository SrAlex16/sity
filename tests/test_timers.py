"""Tests for the timer/alarm system (ScheduledTask model, service, runner, tools).

Coverage:
- Timer fires at the correct time (fire_pending_once)
- Cancelled timer is not fired
- Firing notifies only the owning session (session isolation)
- Timer persists through simulated restart (DB round-trip)
- max_duration_hours limit enforced
- max_active_per_session limit enforced
- set_timer handler happy path
- set_alarm handler happy path and invalid ISO date
- list_timers handler
- cancel_timer handler
- cancel_timer cannot cancel another session's timer
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import ChatMessage, ScheduledTask
from app.notifications.fact import DispatchResult, NotificationFact
from app.timers.runner import fire_pending_once
from app.timers.service import (
    cancel_task,
    count_pending,
    create_scheduled_task,
    list_pending,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(delta_seconds: float = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)


def _make_task(db: Session, session_id: str = "user:1", delta: float = -1) -> ScheduledTask:
    """Create a ScheduledTask directly (bypassing service validation)."""
    from uuid import uuid4
    task = ScheduledTask(
        id=f"tmr_{uuid4().hex[:8]}",
        session_id=session_id,
        fires_at=_utc(delta),
        message="Test timer fired.",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# fire_pending_once — core firing logic
# ---------------------------------------------------------------------------

class TestFirePendingOnce:
    def test_fires_due_timer_and_marks_fired_at(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, delta=-1)
            timer_id = task.id
            session_id = task.session_id

        dispatched_facts: list[NotificationFact] = []

        def capture_dispatch(fact: NotificationFact, db):
            dispatched_facts.append(fact)
            return DispatchResult(channel="sse", notification_id=1)

        with patch("app.timers.runner.dispatch", side_effect=capture_dispatch):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        our_facts = [f for f in dispatched_facts if f.fact_id == f"timer:{timer_id}"]
        assert len(our_facts) == 1
        fact = our_facts[0]
        assert fact.session_id == session_id
        assert fact.notification_type == "timer_fired"
        assert fact.payload["timer_id"] == timer_id
        assert fact.payload["body"] == "Test timer fired."
        assert fact.urgency == "high"

        with Session(engine) as db:
            row = db.get(ScheduledTask, timer_id)
            assert row is not None
            assert row.fired_at is not None

    def test_does_not_fire_future_timer(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, delta=3600)  # 1 hour in the future
            timer_id = task.id

        with patch("app.timers.runner.dispatch") as mock_dispatch:
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id not in fired
        # dispatch must not be called for this timer (other due timers may exist)
        dispatched_ids = [
            call.args[0].fact_id
            for call in mock_dispatch.call_args_list
        ]
        assert f"timer:{timer_id}" not in dispatched_ids

    def test_does_not_fire_cancelled_timer(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, delta=-1)
            task.cancelled_at = _utc()
            db.add(task)
            db.commit()
            timer_id = task.id

        with patch("app.timers.runner.dispatch") as mock_dispatch:
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id not in fired
        dispatched_ids = [call.args[0].fact_id for call in mock_dispatch.call_args_list]
        assert f"timer:{timer_id}" not in dispatched_ids

    def test_does_not_fire_already_fired_timer(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, delta=-1)
            task.fired_at = _utc(-0.5)
            db.add(task)
            db.commit()
            timer_id = task.id

        with patch("app.timers.runner.dispatch") as mock_dispatch:
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id not in fired
        dispatched_ids = [call.args[0].fact_id for call in mock_dispatch.call_args_list]
        assert f"timer:{timer_id}" not in dispatched_ids

    def test_persists_chat_message_on_fire(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, delta=-1, session_id="user:77")
            timer_id = task.id

        with patch("app.timers.runner.dispatch"):
            with Session(engine) as db:
                fire_pending_once(db)

        with Session(engine) as db:
            msgs = list(db.exec(
                select(ChatMessage).where(ChatMessage.trace_id == f"tmr_{timer_id}")
            ))
        assert len(msgs) == 1
        assert msgs[0].text == "Test timer fired."
        assert msgs[0].session_id == "user:77"

    def test_session_isolation_only_notifies_owning_session(self) -> None:
        """Each timer's NotificationFact must target only its owning session."""
        with Session(engine) as db:
            t1 = _make_task(db, session_id="user:100", delta=-1)
            t2 = _make_task(db, session_id="user:200", delta=-1)
            t1_id, t2_id = t1.id, t2.id

        dispatched_facts: list[NotificationFact] = []

        def capture_dispatch(fact: NotificationFact, db):
            dispatched_facts.append(fact)
            return DispatchResult(channel="sse", notification_id=1)

        with patch("app.timers.runner.dispatch", side_effect=capture_dispatch):
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert t1_id in fired
        assert t2_id in fired
        dispatched_sessions = [f.session_id for f in dispatched_facts]
        assert "user:100" in dispatched_sessions
        assert "user:200" in dispatched_sessions
        # Each session dispatched exactly once for its own timer
        t1_facts = [f for f in dispatched_facts if f.fact_id == f"timer:{t1_id}"]
        t2_facts = [f for f in dispatched_facts if f.fact_id == f"timer:{t2_id}"]
        assert len(t1_facts) == 1 and t1_facts[0].session_id == "user:100"
        assert len(t2_facts) == 1 and t2_facts[0].session_id == "user:200"


# ---------------------------------------------------------------------------
# Persistence through restart (DB round-trip)
# ---------------------------------------------------------------------------

class TestTimerPersistence:
    def test_timer_survives_simulated_restart(self) -> None:
        """Timer created in one DB session must still fire in a fresh session."""
        with Session(engine) as db:
            task = _make_task(db, delta=3600, session_id="user:42")
            timer_id = task.id

        # Simulate restart: verify timer still exists as pending
        with Session(engine) as db:
            row = db.get(ScheduledTask, timer_id)
            assert row is not None
            assert row.fired_at is None
            assert row.cancelled_at is None

        # Now make it due and fire
        with Session(engine) as db:
            row = db.get(ScheduledTask, timer_id)
            row.fires_at = _utc(-1)
            db.add(row)
            db.commit()

        with patch("app.timers.runner.dispatch") as mock_dispatch:
            with Session(engine) as db:
                fired = fire_pending_once(db)

        assert timer_id in fired
        dispatched_ids = [call.args[0].fact_id for call in mock_dispatch.call_args_list]
        assert f"timer:{timer_id}" in dispatched_ids


# ---------------------------------------------------------------------------
# Service — validation
# ---------------------------------------------------------------------------

class TestTimerService:
    def test_create_timer_in_past_rejected(self) -> None:
        with Session(engine) as db:
            with pytest.raises(ValueError, match="futuro"):
                create_scheduled_task(db, "user:1", _utc(-10), "msg")

    def test_create_timer_exceeds_max_duration_rejected(self) -> None:
        fires_at = _utc(25 * 3600)  # 25 hours > default 24h limit
        with Session(engine) as db:
            with pytest.raises(ValueError, match="24"):
                create_scheduled_task(db, "user:1", fires_at, "msg")

    def test_create_timer_exceeds_max_active_rejected(self) -> None:
        session_id = f"user:test_max_{id(object())}"
        with Session(engine) as db:
            for _ in range(5):
                create_scheduled_task(db, session_id, _utc(60), "msg")
            with pytest.raises(ValueError, match="5"):
                create_scheduled_task(db, session_id, _utc(60), "msg")

    def test_count_pending_ignores_fired_and_cancelled(self) -> None:
        session_id = f"user:cnt_{id(object())}"
        with Session(engine) as db:
            t1 = _make_task(db, session_id=session_id, delta=-1)
            t1.fired_at = _utc()
            db.add(t1)
            _make_task(db, session_id=session_id, delta=60)  # pending
            db.commit()
            count = count_pending(db, session_id)
        assert count == 1

    def test_cancel_task_marks_cancelled_at(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, session_id="user:99", delta=3600)
            timer_id = task.id

        with Session(engine) as db:
            result = cancel_task(db, "user:99", timer_id)
            assert result is not None

        with Session(engine) as db:
            row = db.get(ScheduledTask, timer_id)
            assert row.cancelled_at is not None

    def test_cancel_task_wrong_session_returns_none(self) -> None:
        with Session(engine) as db:
            task = _make_task(db, session_id="user:owner", delta=3600)
            timer_id = task.id

        with Session(engine) as db:
            result = cancel_task(db, "user:other", timer_id)
            assert result is None

    def test_list_pending_excludes_fired(self) -> None:
        session_id = f"user:lp_{id(object())}"
        with Session(engine) as db:
            t_pending = _make_task(db, session_id=session_id, delta=60)
            t_fired = _make_task(db, session_id=session_id, delta=-1)
            pending_id = t_pending.id
            fired_id = t_fired.id
            t_fired.fired_at = _utc()
            db.add(t_fired)
            db.commit()
            pending = list_pending(db, session_id)
            ids = [t.id for t in pending]

        assert pending_id in ids
        assert fired_id not in ids


# ---------------------------------------------------------------------------
# Tool handlers via dispatch_tool (same pattern as test_service_config_tool_registry)
# ---------------------------------------------------------------------------

from app.core.tool_executor import ToolExecutor  # noqa: E402
from app.tools.registry import ToolContext, dispatch_tool, has_handler  # noqa: E402


class TestTimerHandlerRegistration:
    @pytest.mark.parametrize("name", ["set_timer", "set_alarm", "list_timers", "cancel_timer"])
    def test_handlers_registered(self, name: str) -> None:
        assert has_handler(name), f"{name} not registered"


class TestTimerHandlers:
    def _ctx(self, db_session: Session, tool_name: str, tool_input: dict) -> ToolContext:
        executor = ToolExecutor(db_session, session_id="user:timer_handler_test")
        return ToolContext(
            tool_name=tool_name,
            tool_input=tool_input,
            trace_id="trc_timer_handler_test",
            executor=executor,
        )

    def test_set_timer_happy_path(self, db_session: Session) -> None:
        ctx = self._ctx(db_session, "set_timer", {"duration_seconds": 120, "message": "Prueba!"})
        result = dispatch_tool(ctx)
        assert result.ok is True, result.message
        assert "tmr_" in result.message
        assert "120" in result.message or "2 min" in result.message

    def test_set_timer_invalid_duration(self, db_session: Session) -> None:
        ctx = self._ctx(db_session, "set_timer", {"duration_seconds": 0})
        result = dispatch_tool(ctx)
        assert result.ok is False

    def test_set_alarm_happy_path(self, db_session: Session) -> None:
        fires_at = (_utc(300)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        ctx = self._ctx(db_session, "set_alarm", {"fires_at": fires_at})
        result = dispatch_tool(ctx)
        assert result.ok is True, result.message
        assert "tmr_" in result.message

    def test_set_alarm_invalid_iso(self, db_session: Session) -> None:
        ctx = self._ctx(db_session, "set_alarm", {"fires_at": "not-a-date"})
        result = dispatch_tool(ctx)
        assert result.ok is False
        assert "ISO 8601" in result.message

    def test_set_alarm_in_past_rejected(self, db_session: Session) -> None:
        fires_at = (_utc(-60)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        ctx = self._ctx(db_session, "set_alarm", {"fires_at": fires_at})
        result = dispatch_tool(ctx)
        assert result.ok is False
        assert "futuro" in result.message

    def test_list_timers_empty_session(self, db_session: Session) -> None:
        # Use a unique session_id guaranteed to have no timers
        executor = ToolExecutor(db_session, session_id="user:list_empty_timer_test")
        ctx = ToolContext(
            tool_name="list_timers",
            tool_input={},
            trace_id="trc_test",
            executor=executor,
        )
        result = dispatch_tool(ctx)
        assert result.ok is True
        assert "No tienes" in result.message

    def test_list_timers_shows_pending(self, db_session: Session) -> None:
        session_id = "user:list_pending_timer_test"
        _make_task(db_session, session_id=session_id, delta=3600)
        executor = ToolExecutor(db_session, session_id=session_id)
        ctx = ToolContext(
            tool_name="list_timers",
            tool_input={},
            trace_id="trc_test",
            executor=executor,
        )
        result = dispatch_tool(ctx)
        assert result.ok is True
        assert "tmr_" in result.message

    def test_cancel_timer_not_found(self, db_session: Session) -> None:
        ctx = self._ctx(db_session, "cancel_timer", {"timer_id": "tmr_00000000"})
        result = dispatch_tool(ctx)
        assert result.ok is False
        assert "no se encontró" in result.message.lower()

    def test_cancel_timer_happy_path(self, db_session: Session) -> None:
        session_id = "user:cancel_timer_test"
        task = _make_task(db_session, session_id=session_id, delta=3600)
        executor = ToolExecutor(db_session, session_id=session_id)
        ctx = ToolContext(
            tool_name="cancel_timer",
            tool_input={"timer_id": task.id},
            trace_id="trc_test",
            executor=executor,
        )
        result = dispatch_tool(ctx)
        assert result.ok is True
        assert task.id in result.message

    def test_cancel_timer_wrong_session(self, db_session: Session) -> None:
        task = _make_task(db_session, session_id="user:owner_session", delta=3600)
        executor = ToolExecutor(db_session, session_id="user:attacker_session")
        ctx = ToolContext(
            tool_name="cancel_timer",
            tool_input={"timer_id": task.id},
            trace_id="trc_test",
            executor=executor,
        )
        result = dispatch_tool(ctx)
        assert result.ok is False

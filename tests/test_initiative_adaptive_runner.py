"""Tests for the adaptive initiative runner (runner.py redesign).

Covers:
  - signal_if_urgent_goals: sets wake event when priority >= 0.85, no-op below
    threshold, no-op for non-user sessions, never raises.
  - _call_timing_haiku: parses valid JSON, clamps below MIN, clamps above MAX,
    falls back to (False, FALLBACK) on invalid/missing response.
  - threading.Event semantics: wait() returns True when set before timeout.
  - _run_adaptive_cycle_sync: no users → fallback, haiku skip → no dispatch,
    haiku initiate → runs initiative flow.
  - @behavior_regression: urgent goal → next_check < 3600; no goals → next_check >= 3600.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from sqlmodel import Session, SQLModel, create_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> Session:
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _add_user(db: Session, user_id: int = 1) -> None:
    from app.memory.models import User
    db.add(User(
        id=user_id,
        email=f"u{user_id}@test.local",
        password_hash="x",
        role="user",
        is_active=True,
    ))
    db.commit()


def _add_goal(
    db: Session,
    user_id: int,
    base_importance: float,
    is_wellbeing: bool = False,
    status: str = "active",
    scope: str = "long_term",
) -> None:
    from app.memory.models import Goal
    db.add(Goal(
        user_id=user_id,
        scope=scope,
        description="test goal",
        origin="autonomous",
        base_importance=base_importance,
        is_wellbeing=is_wellbeing,
        status=status,
    ))
    db.commit()


def _add_msg(db: Session, session_id: str, role: str, age_hours: float = 0) -> None:
    from app.memory.models import ChatMessage
    db.add(ChatMessage(
        session_id=session_id,
        role=role,
        text="hi",
        created_at=_utc_now() - timedelta(hours=age_hours),
    ))
    db.commit()


# ---------------------------------------------------------------------------
# TestSignalIfUrgentGoals
# ---------------------------------------------------------------------------

class TestSignalIfUrgentGoals:
    """signal_if_urgent_goals calls _runner_wake_event.set() iff priority >= threshold.

    We mock the event object to avoid a race condition: the daemon runner thread
    (started by another test's TestClient) can call .clear() between our .set()
    and our assertion. Mocking lets us verify the call without inspecting live state.
    """

    def test_event_set_when_goal_above_threshold(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()
        _add_user(db, 1)
        # base_importance=0.9 → effective_priority ≈ 0.90 (> _URGENT_GOAL_THRESHOLD=0.85)
        _add_goal(db, user_id=1, base_importance=0.9, is_wellbeing=False)

        with patch("app.initiative.runner._runner_wake_event") as mock_evt:
            signal_if_urgent_goals("user:1", db)

        mock_evt.set.assert_called_once()

    def test_event_not_set_below_threshold(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()
        _add_user(db, 1)
        # base_importance=0.6 → effective_priority ≈ 0.60 (< 0.85)
        _add_goal(db, user_id=1, base_importance=0.6, is_wellbeing=False)

        with patch("app.initiative.runner._runner_wake_event") as mock_evt:
            signal_if_urgent_goals("user:1", db)

        mock_evt.set.assert_not_called()

    def test_event_not_set_when_no_goals(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()
        _add_user(db, 1)

        with patch("app.initiative.runner._runner_wake_event") as mock_evt:
            signal_if_urgent_goals("user:1", db)

        mock_evt.set.assert_not_called()

    def test_skips_inactive_goals(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()
        _add_user(db, 1)
        _add_goal(db, user_id=1, base_importance=0.95, status="resolved")

        with patch("app.initiative.runner._runner_wake_event") as mock_evt:
            signal_if_urgent_goals("user:1", db)

        mock_evt.set.assert_not_called()

    def test_skips_non_user_session(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()

        with patch("app.initiative.runner._runner_wake_event") as mock_evt:
            signal_if_urgent_goals("guest:abc", db)

        mock_evt.set.assert_not_called()

    def test_never_raises_on_bad_session(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()
        # "user:notanint" — should not raise
        signal_if_urgent_goals("user:notanint", db)

    def test_never_raises_on_closed_db(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        db = _make_db()
        db.close()
        # Closed session — should not raise
        signal_if_urgent_goals("user:1", db)

    def test_wellbeing_goal_at_threshold(self) -> None:
        from app.initiative.runner import signal_if_urgent_goals
        # Wellbeing goals skip irony-reduction — base_importance=0.85 exactly at threshold
        db = _make_db()
        _add_user(db, 1)
        _add_goal(db, user_id=1, base_importance=0.85, is_wellbeing=True)

        with patch("app.initiative.runner._runner_wake_event") as mock_evt:
            signal_if_urgent_goals("user:1", db)

        mock_evt.set.assert_called_once()


# ---------------------------------------------------------------------------
# TestTimingHaiku
# ---------------------------------------------------------------------------

class TestTimingHaiku:
    """_call_timing_haiku: parsing, clamping, and fallback behavior."""

    def _make_provider(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.ok = True
        resp.text = text
        provider = MagicMock()
        provider.generate.return_value = resp
        return provider

    def test_valid_response_parsed(self) -> None:
        from app.initiative.runner import _call_timing_haiku
        payload = json.dumps({
            "should_initiate": True,
            "next_check_seconds": 1800,
            "reasoning": "razon de prueba",
        })
        provider = self._make_provider(payload)
        with patch("app.initiative.runner.build_ai_provider", return_value=provider):
            ok, ncs, reason = _call_timing_haiku("dummy")

        assert ok is True
        assert ncs == 1800
        assert "razon" in reason

    def test_fallback_on_invalid_json(self) -> None:
        from app.initiative.runner import _call_timing_haiku, _FALLBACK_CHECK_SECONDS
        provider = self._make_provider("not json at all")
        with patch("app.initiative.runner.build_ai_provider", return_value=provider):
            ok, ncs, reason = _call_timing_haiku("dummy")

        assert ok is False
        assert ncs == _FALLBACK_CHECK_SECONDS

    def test_fallback_on_provider_error(self) -> None:
        from app.initiative.runner import _call_timing_haiku, _FALLBACK_CHECK_SECONDS
        with patch(
            "app.initiative.runner.build_ai_provider",
            side_effect=RuntimeError("connection refused"),
        ):
            ok, ncs, reason = _call_timing_haiku("dummy")

        assert ok is False
        assert ncs == _FALLBACK_CHECK_SECONDS

    def test_fallback_on_empty_response(self) -> None:
        from app.initiative.runner import _call_timing_haiku, _FALLBACK_CHECK_SECONDS
        resp = MagicMock()
        resp.ok = False
        resp.text = ""
        provider = MagicMock()
        provider.generate.return_value = resp
        with patch("app.initiative.runner.build_ai_provider", return_value=provider):
            ok, ncs, reason = _call_timing_haiku("dummy")

        assert ok is False
        assert ncs == _FALLBACK_CHECK_SECONDS

    def test_raw_value_not_clamped_inside_caller(self) -> None:
        """_call_timing_haiku returns raw next_check — clamping is the caller's job."""
        from app.initiative.runner import _call_timing_haiku, _MAX_CHECK_SECONDS
        above_max = _MAX_CHECK_SECONDS + 10000
        payload = json.dumps({
            "should_initiate": False,
            "next_check_seconds": above_max,
            "reasoning": "x",
        })
        provider = self._make_provider(payload)
        with patch("app.initiative.runner.build_ai_provider", return_value=provider):
            _, raw_next, _ = _call_timing_haiku("dummy")

        # _call_timing_haiku returns raw value; clamping is the caller's job
        assert raw_next > _MAX_CHECK_SECONDS


# ---------------------------------------------------------------------------
# TestRunnerEventSemantics
# ---------------------------------------------------------------------------

class TestRunnerEventSemantics:
    """Verify threading.Event.wait() returns True when set before timeout."""

    def test_wait_returns_true_when_set_before_timeout(self) -> None:
        evt = threading.Event()

        def _setter():
            time.sleep(0.05)
            evt.set()

        t = threading.Thread(target=_setter)
        t.start()
        result = evt.wait(timeout=2.0)
        t.join()

        assert result is True

    def test_wait_returns_false_on_timeout(self) -> None:
        evt = threading.Event()
        result = evt.wait(timeout=0.05)

        assert result is False


# ---------------------------------------------------------------------------
# TestRunAdaptiveCycleSync
# ---------------------------------------------------------------------------

class TestRunAdaptiveCycleSync:
    """_run_adaptive_cycle_sync behavior under various conditions."""

    def test_no_users_returns_fallback(self) -> None:
        from app.initiative.runner import _run_adaptive_cycle_sync, _FALLBACK_CHECK_SECONDS
        with patch("app.initiative.runner.engine") as mock_engine:
            # Provide a real in-memory engine so Session(engine) works
            real_engine = create_engine(
                "sqlite:///:memory:", connect_args={"check_same_thread": False}
            )
            SQLModel.metadata.create_all(real_engine)
            mock_engine.__class__ = real_engine.__class__

            # Patch Session to return an empty users list
            with patch("app.initiative.runner.Session") as MockSession:
                mock_db = MagicMock()
                MockSession.return_value.__enter__ = lambda s: mock_db
                MockSession.return_value.__exit__ = MagicMock(return_value=False)

                mock_db.exec.return_value.all.return_value = []  # no users

                result = _run_adaptive_cycle_sync(woken_by_signal=False)

        assert result == _FALLBACK_CHECK_SECONDS

    def test_haiku_skip_does_not_dispatch(self) -> None:
        """If Haiku returns should_initiate=False, dispatch must not be called."""
        from app.initiative.runner import _run_adaptive_cycle_sync
        from app.memory.models import User

        fake_user = MagicMock(spec=User)
        fake_user.id = 1

        timing_response = (False, 3600, "no es buen momento")

        with (
            patch("app.initiative.runner.Session") as MockSession,
            patch("app.initiative.runner._build_timing_message", return_value="dummy"),
            patch("app.initiative.runner._call_timing_haiku", return_value=timing_response),
            patch("app.initiative.runner._dispatch_initiative") as mock_dispatch,
            patch("app.initiative.runner._gc_expired_open_loops"),
            patch("app.initiative.runner.write_log"),
        ):
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = lambda s: mock_db
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.exec.return_value.all.return_value = [fake_user]

            _run_adaptive_cycle_sync(woken_by_signal=False)

        mock_dispatch.assert_not_called()

    def test_haiku_initiate_runs_flow(self) -> None:
        """If Haiku returns should_initiate=True AND _is_now_a_good_time is None
        AND there are candidates AND evaluator says send → dispatch called once."""
        from app.initiative.runner import _run_adaptive_cycle_sync
        from app.memory.models import User
        from app.initiative.detector import TriggerCandidate
        from app.initiative.evaluator import EvalResult

        fake_user = MagicMock(spec=User)
        fake_user.id = 42

        fake_candidate = TriggerCandidate(
            session_id="user:42",
            trigger_type="long_inactivity",
        )
        fake_result = EvalResult(decision="send", message="¡Hola!", skip_reason=None)

        timing_ok = (True, 1800, "hay meta urgente")

        with (
            patch("app.initiative.runner.Session") as MockSession,
            patch("app.initiative.runner._build_timing_message", return_value="dummy_msg"),
            patch("app.initiative.runner._call_timing_haiku", return_value=timing_ok),
            patch("app.initiative.runner._is_now_a_good_time", return_value=None),
            patch("app.initiative.runner.get_trigger_candidates", return_value=[fake_candidate]),
            patch("app.initiative.runner.evaluate", return_value=fake_result),
            patch("app.initiative.runner._dispatch_initiative") as mock_dispatch,
            patch("app.initiative.runner._gc_expired_open_loops"),
            patch("app.initiative.runner.write_log"),
        ):
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = lambda s: mock_db
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.exec.return_value.all.return_value = [fake_user]

            _run_adaptive_cycle_sync(woken_by_signal=True)

        mock_dispatch.assert_called_once()
        called_candidate = mock_dispatch.call_args[0][0]
        assert called_candidate.session_id == "user:42"

    def test_next_check_clamped_to_min(self) -> None:
        """Raw haiku value below _MIN_CHECK_SECONDS is clamped up."""
        from app.initiative.runner import _run_adaptive_cycle_sync, _MIN_CHECK_SECONDS
        from app.memory.models import User

        fake_user = MagicMock(spec=User)
        fake_user.id = 1

        timing_below_min = (False, 5, "muy pronto")  # 5 < _MIN_CHECK_SECONDS

        with (
            patch("app.initiative.runner.Session") as MockSession,
            patch("app.initiative.runner._build_timing_message", return_value="dummy"),
            patch("app.initiative.runner._call_timing_haiku", return_value=timing_below_min),
            patch("app.initiative.runner._gc_expired_open_loops"),
            patch("app.initiative.runner.write_log"),
        ):
            mock_db = MagicMock()
            MockSession.return_value.__enter__ = lambda s: mock_db
            MockSession.return_value.__exit__ = MagicMock(return_value=False)
            mock_db.exec.return_value.all.return_value = [fake_user]

            result = _run_adaptive_cycle_sync(woken_by_signal=False)

        assert result >= _MIN_CHECK_SECONDS


# ---------------------------------------------------------------------------
# Behavior regression tests (real Haiku — skipped without API key)
# ---------------------------------------------------------------------------

@pytest.mark.behavior_regression
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping real-model behavior tests",
)
class TestBehaviorRegression:
    """Sanity checks using the real Haiku model. Run with ANTHROPIC_API_KEY set."""

    def _build_timing_msg(self, urgent: bool) -> str:
        if urgent:
            return (
                "Hora local: 15:30 (martes)\n"
                "Franja horaria: tarde\n"
                "Días sin conversación real del usuario: 3.0\n"
                "Iniciativas de Sity sin respuesta (últimas 24h): 0\n"
                "Motivo del ciclo: signal_urgente\n\n"
                "Estado emocional actual:\n"
                "  interés=0.75  melancolía=0.10  aburrimiento=0.10\n"
                "  frustración=0.15  confort_social=0.65\n\n"
                "Relación con el usuario:\n"
                "  familiaridad=0.85  confianza=0.80  afinidad=0.75\n\n"
                "Metas activas con priority ≥ 0.75:\n"
                '- "Apoyo en estrés laboral" (priority=0.92, bienestar)\n'
            )
        else:
            return (
                "Hora local: 14:00 (miércoles)\n"
                "Franja horaria: tarde\n"
                "Días sin conversación real del usuario: 0.2\n"
                "Iniciativas de Sity sin respuesta (últimas 24h): 0\n"
                "Motivo del ciclo: timeout_programado\n\n"
                "Estado emocional actual:\n"
                "  interés=0.50  melancolía=0.10  aburrimiento=0.10\n"
                "  frustración=0.10  confort_social=0.60\n\n"
                "Relación con el usuario:\n"
                "  familiaridad=0.60  confianza=0.65  afinidad=0.60\n\n"
                "Metas activas con priority ≥ 0.75:\n"
                "Ninguna"
            )

    def test_urgent_goal_leads_to_shorter_next_check(self) -> None:
        """With an urgent wellbeing goal and good timing, next_check should be shorter."""
        from app.initiative.runner import _call_timing_haiku, _FALLBACK_CHECK_SECONDS

        msg = self._build_timing_msg(urgent=True)
        _, ncs, _ = _call_timing_haiku(msg)

        # With an urgent goal, Haiku should suggest checking sooner than the 1h fallback
        assert ncs < _FALLBACK_CHECK_SECONDS, (
            f"Expected next_check < {_FALLBACK_CHECK_SECONDS}s for urgent goal, got {ncs}s"
        )

    def test_no_goals_leads_to_longer_next_check(self) -> None:
        """With no urgent goals and recent activity, Haiku should suggest a longer wait."""
        from app.initiative.runner import _call_timing_haiku, _FALLBACK_CHECK_SECONDS

        msg = self._build_timing_msg(urgent=False)
        _, ncs, _ = _call_timing_haiku(msg)

        assert ncs >= _FALLBACK_CHECK_SECONDS, (
            f"Expected next_check >= {_FALLBACK_CHECK_SECONDS}s without goals, got {ncs}s"
        )

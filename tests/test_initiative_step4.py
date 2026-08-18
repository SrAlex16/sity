"""Tests for Initiative Step 4 — runner.py.

Covers:
  - Pipeline completo: candidatos detectados, evaluator "send" → dispatcher llamado con
    NotificationFact correcto; evaluator "skip" → dispatcher NO llamado.
  - Error en un candidato no detiene el ciclo para los demás.
  - OpenLoop marcado "dispatched" tras el envío.
  - GC: OpenLoops expirados marcados "expired".
  - IS_NOW_A_GOOD_TIME? pre-filtros: silence_recent, trust_too_low, rate_limited, initiative_disabled.
  - Priorización: open_loop elegido sobre conversation_abandoned.
  - ChatMessage persistido cuando el resultado es "send".
  - Test de integración completo: DB real + Haiku mockeado → ChatMessage + NotificationLog.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from sqlmodel import Session, SQLModel, create_engine, select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _add_user(db: Session, user_id: int = 1, is_active: bool = True) -> None:
    from app.memory.models import User
    db.add(User(
        id=user_id,
        email=f"user{user_id}@test.local",
        password_hash="x",
        role="user",
        is_active=is_active,
    ))
    db.commit()


def _add_msg(db: Session, session_id: str, role: str, age_hours: float) -> None:
    from app.memory.models import ChatMessage
    db.add(ChatMessage(
        session_id=session_id,
        role=role,
        text="test",
        created_at=_utc_now() - timedelta(hours=age_hours),
    ))
    db.commit()


def _add_social(db: Session, session_id: str, trust: float = 0.8) -> None:
    from app.memory.models import SocialProfile
    user_id = int(session_id.split(":", 1)[1])
    db.add(SocialProfile(user_id=user_id, trust=trust))
    db.commit()


_loop_counter = 0

def _add_open_loop(db: Session, session_id: str, age_days: float = 5.0, status: str = "pending") -> str:
    from app.memory.models import OpenLoop
    global _loop_counter
    _loop_counter += 1
    lid = f"ol_t{_loop_counter:06d}"
    detected = _utc_now() - timedelta(days=age_days)
    db.add(OpenLoop(
        id=lid,
        session_id=session_id,
        user_message="Voy a buscar trabajo.",
        extracted_intent="buscar trabajo",
        detected_at=detected,
        expires_at=detected + timedelta(days=30),
        status=status,
    ))
    db.commit()
    return lid


def _candidate(trigger_type: str = "conversation_abandoned", session_id: str = "user:1",
               open_loop_id: str | None = None):
    from app.initiative.detector import TriggerCandidate
    return TriggerCandidate(
        trigger_type=trigger_type,
        session_id=session_id,
        context={},
        open_loop_id=open_loop_id,
    )


def _eval_result(decision: str, message: str | None = None, skip_reason: str | None = None):
    from app.initiative.evaluator import EvalResult
    return EvalResult(decision=decision, message=message, skip_reason=skip_reason)


# ---------------------------------------------------------------------------
# _gc_expired_open_loops
# ---------------------------------------------------------------------------

class TestGCExpiredOpenLoops:
    def test_marks_expired_open_loops(self):
        from app.initiative.runner import _gc_expired_open_loops
        from app.memory.models import OpenLoop
        db = _make_db()
        sid = "user:1"
        # Already past expires_at
        expired_loop = OpenLoop(
            id="ol_exp001",
            session_id=sid,
            user_message="m",
            extracted_intent="e",
            detected_at=_utc_now() - timedelta(days=35),
            expires_at=_utc_now() - timedelta(days=5),
            status="pending",
        )
        db.add(expired_loop)
        db.commit()

        _gc_expired_open_loops(db)

        loop = db.exec(select(OpenLoop).where(OpenLoop.id == "ol_exp001")).first()
        assert loop.status == "expired"

    def test_does_not_touch_non_expired_loops(self):
        from app.initiative.runner import _gc_expired_open_loops
        from app.memory.models import OpenLoop
        db = _make_db()
        fresh = OpenLoop(
            id="ol_fresh01",
            session_id="user:1",
            user_message="m",
            extracted_intent="e",
            detected_at=_utc_now() - timedelta(days=4),
            expires_at=_utc_now() + timedelta(days=26),
            status="pending",
        )
        db.add(fresh)
        db.commit()

        _gc_expired_open_loops(db)

        loop = db.exec(select(OpenLoop).where(OpenLoop.id == "ol_fresh01")).first()
        assert loop.status == "pending"

    def test_does_not_touch_already_resolved(self):
        from app.initiative.runner import _gc_expired_open_loops
        from app.memory.models import OpenLoop
        db = _make_db()
        resolved = OpenLoop(
            id="ol_res001",
            session_id="user:1",
            user_message="m",
            extracted_intent="e",
            detected_at=_utc_now() - timedelta(days=35),
            expires_at=_utc_now() - timedelta(days=5),
            status="resolved",
        )
        db.add(resolved)
        db.commit()

        _gc_expired_open_loops(db)

        loop = db.exec(select(OpenLoop).where(OpenLoop.id == "ol_res001")).first()
        assert loop.status == "resolved"


# ---------------------------------------------------------------------------
# _is_now_a_good_time pre-filters
# ---------------------------------------------------------------------------

class TestIsNowAGoodTime:
    def _check(self, db, session_id="user:1", silence_hours=4, min_trust=0.3, max_per_day=1):
        from app.initiative.runner import _is_now_a_good_time
        return _is_now_a_good_time(db=db, session_id=session_id,
                                   silence_hours=silence_hours, min_trust=min_trust,
                                   max_per_day=max_per_day)

    def test_recent_message_returns_silence_recent(self):
        db = _make_db()
        _add_msg(db, "user:1", "user", age_hours=1)  # 1h ago < silence_hours=4
        assert self._check(db) == "silence_recent"

    def test_old_message_passes_silence(self):
        db = _make_db()
        _add_msg(db, "user:1", "user", age_hours=10)  # 10h ago > silence_hours=4
        assert self._check(db) is None

    def test_no_messages_passes_silence(self):
        db = _make_db()
        assert self._check(db) is None

    def test_low_trust_returns_trust_too_low(self):
        db = _make_db()
        _add_social(db, "user:1", trust=0.1)
        assert self._check(db) == "trust_too_low"

    def test_sufficient_trust_passes(self):
        db = _make_db()
        _add_social(db, "user:1", trust=0.5)
        assert self._check(db) is None

    def test_no_social_profile_passes_trust(self):
        db = _make_db()
        assert self._check(db) is None

    def test_daily_max_hit_returns_rate_limited(self):
        from app.memory.models import NotificationLog
        db = _make_db()
        db.add(NotificationLog(
            session_id="user:1",
            notification_type="proactive_initiative",
            fact_id="init:user:1:today",
            payload_json="{}",
            delivery_channel="sse",
            delivery_status="delivered",
            created_at=_utc_now(),
        ))
        db.commit()
        assert self._check(db, max_per_day=1) == "rate_limited"

    def test_initiative_disabled_returns_initiative_disabled(self):
        from app.initiative.settings import set_initiative_settings, InitiativeSettings
        db = _make_db()
        set_initiative_settings(db, InitiativeSettings(enabled=False), session_id="user:1")
        assert self._check(db) == "initiative_disabled"


# ---------------------------------------------------------------------------
# _pick_candidate prioritization
# ---------------------------------------------------------------------------

class TestPickCandidate:
    def test_open_loop_beats_conversation_abandoned(self):
        from app.initiative.runner import _pick_candidate
        candidates = [
            _candidate("conversation_abandoned"),
            _candidate("open_loop", open_loop_id="ol_x"),
        ]
        assert _pick_candidate(candidates).trigger_type == "open_loop"

    def test_open_loop_beats_long_inactivity(self):
        from app.initiative.runner import _pick_candidate
        candidates = [
            _candidate("long_inactivity"),
            _candidate("open_loop", open_loop_id="ol_y"),
        ]
        assert _pick_candidate(candidates).trigger_type == "open_loop"

    def test_conversation_abandoned_beats_long_inactivity(self):
        from app.initiative.runner import _pick_candidate
        candidates = [
            _candidate("long_inactivity"),
            _candidate("conversation_abandoned"),
        ]
        assert _pick_candidate(candidates).trigger_type == "conversation_abandoned"

    def test_single_candidate_returned(self):
        from app.initiative.runner import _pick_candidate
        candidates = [_candidate("long_inactivity")]
        assert _pick_candidate(candidates).trigger_type == "long_inactivity"


# ---------------------------------------------------------------------------
# _dispatch_initiative
# ---------------------------------------------------------------------------

class TestDispatchInitiative:
    def test_chat_message_persisted(self):
        from app.initiative.runner import _dispatch_initiative
        from app.memory.models import ChatMessage
        db = _make_db()
        cand = _candidate("conversation_abandoned", session_id="user:1")
        result = _eval_result("send", message="¿Cómo estás?")

        with patch("app.initiative.runner.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(discarded=False)
            _dispatch_initiative(cand, result, db)

        msgs = db.exec(
            select(ChatMessage).where(
                ChatMessage.session_id == "user:1",
                ChatMessage.role == "sity",
            )
        ).all()
        assert len(msgs) == 1
        assert msgs[0].text == "¿Cómo estás?"

    def test_dispatch_called_with_correct_fact(self):
        from app.initiative.runner import _dispatch_initiative
        db = _make_db()
        cand = _candidate("long_inactivity", session_id="user:2")
        result = _eval_result("send", message="Oye, ¿todo bien?")

        with patch("app.initiative.runner.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(discarded=False)
            _dispatch_initiative(cand, result, db)

        assert mock_dispatch.call_count == 1
        fact = mock_dispatch.call_args[0][0]
        assert fact.notification_type == "proactive_initiative"
        assert fact.session_id == "user:2"
        assert fact.payload["full_text"] == "Oye, ¿todo bien?"
        assert fact.payload["trigger_type"] == "long_inactivity"
        assert "initiative:user:2:" in fact.fact_id

    def test_open_loop_marked_dispatched(self):
        from app.initiative.runner import _dispatch_initiative
        from app.memory.models import OpenLoop
        db = _make_db()
        lid = _add_open_loop(db, "user:1", age_days=5)
        cand = _candidate("open_loop", session_id="user:1", open_loop_id=lid)
        result = _eval_result("send", message="¿Cómo va la búsqueda?")

        with patch("app.initiative.runner.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(discarded=False)
            _dispatch_initiative(cand, result, db)

        loop = db.exec(select(OpenLoop).where(OpenLoop.id == lid)).first()
        assert loop.status == "dispatched"

    def test_non_open_loop_trigger_does_not_touch_open_loops(self):
        from app.initiative.runner import _dispatch_initiative
        from app.memory.models import OpenLoop
        db = _make_db()
        lid = _add_open_loop(db, "user:1", age_days=5)
        cand = _candidate("conversation_abandoned", session_id="user:1")
        result = _eval_result("send", message="Hola")

        with patch("app.initiative.runner.dispatch"):
            _dispatch_initiative(cand, result, db)

        loop = db.exec(select(OpenLoop).where(OpenLoop.id == lid)).first()
        assert loop.status == "pending"


# ---------------------------------------------------------------------------
# _run_cycle_sync — pipeline orchestration
# ---------------------------------------------------------------------------

class TestRunCycleSync:
    def _make_eligible_db(self, user_id: int = 1) -> Session:
        """DB with one active user, old-enough messages, good trust, no prior notifications."""
        db = _make_db()
        sid = f"user:{user_id}"
        _add_user(db, user_id=user_id)
        _add_msg(db, sid, "user", age_hours=10)  # old enough for silence
        _add_social(db, sid, trust=0.8)
        return db

    def test_send_candidate_reaches_dispatcher(self):
        from app.initiative.runner import _run_cycle_sync
        db = self._make_eligible_db()
        sid = "user:1"
        _add_open_loop(db, sid, age_days=5)

        haiku_send = json.dumps({"decision": "send", "message": "¿Qué tal?", "reasoning": "r"})
        mock_provider = MagicMock()
        mock_provider.generate.return_value = MagicMock(ok=True, text=haiku_send)

        dispatched: list = []

        def fake_dispatch(fact, db_session):
            dispatched.append(fact)
            return MagicMock(discarded=False)

        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider), \
             patch("app.initiative.runner.dispatch", side_effect=fake_dispatch), \
             patch("app.initiative.open_loop_hook.build_ai_provider", return_value=mock_provider):
            _run_cycle_sync()

        assert len(dispatched) == 1
        assert dispatched[0].notification_type == "proactive_initiative"
        assert dispatched[0].session_id == sid

    def test_skip_candidate_does_not_reach_dispatcher(self):
        from app.initiative.runner import _run_cycle_sync
        db = self._make_eligible_db()
        sid = "user:1"
        _add_open_loop(db, sid, age_days=5)

        haiku_skip = json.dumps({"decision": "skip", "reasoning": "no context"})
        mock_provider = MagicMock()
        mock_provider.generate.return_value = MagicMock(ok=True, text=haiku_skip)

        dispatched: list = []

        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider), \
             patch("app.initiative.runner.dispatch", side_effect=lambda f, d: dispatched.append(f)):
            _run_cycle_sync()

        assert len(dispatched) == 0

    def test_error_in_one_session_does_not_stop_others(self):
        """If evaluator raises for session 1, session 2 is still processed."""
        from app.initiative.runner import _run_cycle_sync
        db = _make_db()

        _add_user(db, user_id=1)
        _add_user(db, user_id=2)
        sid1, sid2 = "user:1", "user:2"
        for sid in [sid1, sid2]:
            _add_msg(db, sid, "user", age_hours=10)
            _add_social(db, sid, trust=0.8)
            _add_open_loop(db, sid, age_days=5)

        call_count = 0
        dispatched: list = []

        def fake_evaluate(candidate, db_session):
            nonlocal call_count
            call_count += 1
            if candidate.session_id == sid1:
                raise RuntimeError("evaluator exploded")
            from app.initiative.evaluator import EvalResult
            return EvalResult(decision="send", message="Hola", haiku_verdict="send")

        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.runner.evaluate", side_effect=fake_evaluate), \
             patch("app.initiative.runner.dispatch", side_effect=lambda f, d: dispatched.append(f)):
            _run_cycle_sync()

        # Session 2 should have been dispatched despite session 1 failing
        assert any(f.session_id == sid2 for f in dispatched)

    def test_inactive_user_not_processed(self):
        from app.initiative.runner import _run_cycle_sync
        db = _make_db()
        _add_user(db, user_id=1, is_active=False)
        _add_msg(db, "user:1", "user", age_hours=10)
        _add_open_loop(db, "user:1", age_days=5)

        dispatched: list = []
        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.runner.dispatch", side_effect=lambda f, d: dispatched.append(f)):
            _run_cycle_sync()

        assert len(dispatched) == 0

    def test_silence_filter_skips_recent_session(self):
        from app.initiative.runner import _run_cycle_sync
        db = _make_db()
        _add_user(db, user_id=1)
        _add_msg(db, "user:1", "user", age_hours=1)  # 1h ago → within silence_hours=4
        _add_open_loop(db, "user:1", age_days=5)

        dispatched: list = []
        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.runner.dispatch", side_effect=lambda f, d: dispatched.append(f)):
            _run_cycle_sync()

        assert len(dispatched) == 0


# ---------------------------------------------------------------------------
# Integration test — real DB, Haiku mocked, checks ChatMessage + NotificationLog
# ---------------------------------------------------------------------------

class TestRunnerIntegration:
    def test_open_loop_send_persists_chat_message_and_notification_log(self):
        """Full pipeline: open_loop trigger → Haiku says send → ChatMessage + NotificationLog created."""
        from app.initiative.runner import _run_cycle_sync
        from app.memory.models import ChatMessage, NotificationLog, OpenLoop

        db = _make_db()
        _add_user(db, user_id=1)
        sid = "user:1"
        _add_msg(db, sid, "user", age_hours=8)   # old enough (>4h silence)
        _add_social(db, sid, trust=0.7)
        lid = _add_open_loop(db, sid, age_days=5)

        haiku_resp = json.dumps({
            "decision": "send",
            "open_loop_resolved": False,
            "message": "¿Cómo va la búsqueda de trabajo?",
            "reasoning": "still pending after 5 days",
        })
        mock_provider = MagicMock()
        mock_provider.generate.return_value = MagicMock(ok=True, text=haiku_resp)

        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider), \
             patch("app.notifications.dispatcher.publish_session_event_sync"):
            _run_cycle_sync()

        # ChatMessage persisted
        sity_msgs = db.exec(
            select(ChatMessage).where(ChatMessage.session_id == sid, ChatMessage.role == "sity")
        ).all()
        assert len(sity_msgs) == 1
        assert "búsqueda" in sity_msgs[0].text

        # NotificationLog created by dispatcher
        notif_logs = db.exec(
            select(NotificationLog).where(
                NotificationLog.session_id == sid,
                NotificationLog.notification_type == "proactive_initiative",
            )
        ).all()
        assert len(notif_logs) == 1

        # OpenLoop marked dispatched
        loop = db.exec(select(OpenLoop).where(OpenLoop.id == lid)).first()
        assert loop.status == "dispatched"

    def test_conversation_abandoned_send_persists_chat_message(self):
        """conversation_abandoned trigger → send → ChatMessage created with sity role."""
        from app.initiative.runner import _run_cycle_sync
        from app.memory.models import ChatMessage

        db = _make_db()
        _add_user(db, user_id=2)
        sid = "user:2"
        _add_msg(db, sid, "user", age_hours=50)
        _add_msg(db, sid, "sity", age_hours=30)  # last msg is sity, 30h old → abandoned trigger
        _add_social(db, sid, trust=0.6)

        haiku_resp = json.dumps({
            "decision": "send",
            "message": "¡Hola! ¿Sigues por ahí?",
            "reasoning": "abandoned conversation",
        })
        mock_provider = MagicMock()
        mock_provider.generate.return_value = MagicMock(ok=True, text=haiku_resp)

        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider), \
             patch("app.notifications.dispatcher.publish_session_event_sync"):
            _run_cycle_sync()

        sity_msgs = db.exec(
            select(ChatMessage).where(ChatMessage.session_id == sid, ChatMessage.role == "sity")
        ).all()
        # One was pre-seeded (30h old), one added by the runner
        assert len(sity_msgs) == 2
        assert any("Hola" in m.text for m in sity_msgs)

    def test_haiku_skip_no_chat_message_no_notification_log(self):
        """Haiku says skip → neither ChatMessage nor NotificationLog created."""
        from app.initiative.runner import _run_cycle_sync
        from app.memory.models import ChatMessage, NotificationLog

        db = _make_db()
        _add_user(db, user_id=3)
        sid = "user:3"
        _add_msg(db, sid, "user", age_hours=8)
        _add_social(db, sid, trust=0.7)
        _add_open_loop(db, sid, age_days=5)

        haiku_resp = json.dumps({"decision": "skip", "reasoning": "not a good time"})
        mock_provider = MagicMock()
        mock_provider.generate.return_value = MagicMock(ok=True, text=haiku_resp)

        with patch("app.initiative.runner.engine", db.bind), \
             patch("app.initiative.runner.Session", side_effect=lambda bind: db), \
             patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider), \
             patch("app.notifications.dispatcher.publish_session_event_sync"):
            _run_cycle_sync()

        sity_msgs = db.exec(
            select(ChatMessage).where(ChatMessage.session_id == sid, ChatMessage.role == "sity")
        ).all()
        assert len(sity_msgs) == 0

        notif_logs = db.exec(
            select(NotificationLog).where(NotificationLog.session_id == sid)
        ).all()
        assert len(notif_logs) == 0

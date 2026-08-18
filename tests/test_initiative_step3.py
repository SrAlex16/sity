"""Tests for Initiative Step 3 — evaluator.py (SHOULD_I_TALK? gate).

Covers:
  - send: Haiku confirms + limits OK → decision="send", message set, EvalLog persisted
  - rate_limited: daily max hit → skip, Haiku NOT called
  - cooldown_active: within cooldown window → skip, Haiku NOT called
  - model_skip: Haiku returns "skip" → skip, skip_reason="model_skip"
  - evaluator_error: Haiku call raises → skip, skip_reason="evaluator_error"
  - open_loop_resolved: Haiku signals resolved=True → OpenLoop marked, skip
  - open_loop send: Haiku sends without resolved signal → decision="send"
  - InitiativeEvalLog persisted for both send and skip paths
  - SocialProfile values reach the Haiku prompt (build_user_message)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

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


def _candidate(trigger_type: str = "conversation_abandoned", session_id: str = "user:1",
               context: dict | None = None, open_loop_id: str | None = None):
    from app.initiative.detector import TriggerCandidate
    return TriggerCandidate(
        trigger_type=trigger_type,
        session_id=session_id,
        context=context or {"hours_since_last_message": 30},
        open_loop_id=open_loop_id,
    )


def _add_notification_log(db: Session, session_id: str, age_hours: float = 0) -> None:
    from app.memory.models import NotificationLog
    created = _utc_now() - timedelta(hours=age_hours)
    db.add(NotificationLog(
        session_id=session_id,
        notification_type="proactive_initiative",
        fact_id=f"init:{session_id}:{created.date().isoformat()}:{age_hours}",
        payload_json="{}",
        delivery_channel="sse",
        delivery_status="delivered",
        created_at=created,
    ))
    db.commit()


def _add_social_profile(db: Session, session_id: str, opinion: float = 0.5, trust: float = 0.7) -> None:
    from app.memory.models import SocialProfile
    user_id = int(session_id.split(":", 1)[1])
    db.add(SocialProfile(user_id=user_id, opinion=opinion, trust=trust))
    db.commit()


def _mock_haiku(text: str, ok: bool = True) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.text = text
    mock_provider = MagicMock()
    mock_provider.generate.return_value = resp
    mock_factory = MagicMock(return_value=mock_provider)
    return mock_factory


# ---------------------------------------------------------------------------
# Happy path — send decision
# ---------------------------------------------------------------------------

class TestEvaluatorSend:
    def test_haiku_send_returns_send_result(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        cand = _candidate()
        haiku_json = json.dumps({"decision": "send", "message": "¿Todo bien?", "reasoning": "inactivity"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "send"
        assert result.message == "¿Todo bien?"
        assert result.haiku_verdict == "send"
        assert result.skip_reason is None
        assert mock_factory.called

    def test_send_persists_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        cand = _candidate()
        haiku_json = json.dumps({"decision": "send", "message": "Hola", "reasoning": "context"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        logs = db.exec(select(InitiativeEvalLog).where(InitiativeEvalLog.session_id == "user:1")).all()
        assert len(logs) == 1
        assert logs[0].decision == "send"
        assert logs[0].trigger_type == "conversation_abandoned"
        assert logs[0].haiku_verdict == "send"
        assert logs[0].message_preview == "Hola"

    def test_message_truncated_in_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        cand = _candidate()
        long_msg = "x" * 300
        haiku_json = json.dumps({"decision": "send", "message": long_msg, "reasoning": "r"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog)).first()
        assert len(log.message_preview) == 200  # truncated to 200


# ---------------------------------------------------------------------------
# Rate limiting — Haiku must NOT be called
# ---------------------------------------------------------------------------

class TestEvaluatorRateLimits:
    def test_daily_max_hit_returns_rate_limited(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        sid = "user:10"
        _add_notification_log(db, sid, age_hours=1)  # today, 1h ago
        cand = _candidate(session_id=sid)
        mock_factory = MagicMock()

        # Default max_proactive_per_day_user = 1
        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "skip"
        assert result.skip_reason == "rate_limited"
        assert not mock_factory.called  # Haiku never called

    def test_rate_limited_persists_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        sid = "user:11"
        _add_notification_log(db, sid, age_hours=0)
        cand = _candidate(session_id=sid)

        with patch("app.initiative.evaluator.build_ai_provider", MagicMock()):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog).where(InitiativeEvalLog.session_id == sid)).first()
        assert log is not None
        assert log.skip_reason == "rate_limited"
        assert log.haiku_verdict is None

    def test_cooldown_active_skip_no_haiku(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        sid = "user:12"
        cand = _candidate(session_id=sid)
        mock_factory = MagicMock()

        # Patch config: max_per_day=100 (won't hit daily limit), cooldown=24h
        custom_notif_cfg = {
            "max_proactive_per_day_user": 100,
            "initiative_cooldown_hours": 24,
        }
        _add_notification_log(db, sid, age_hours=2)  # 2h ago, within 24h cooldown

        with patch("app.initiative.evaluator.load_default_config",
                   return_value={"notifications": custom_notif_cfg}):
            with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
                result = evaluate(cand, db)

        assert result.decision == "skip"
        assert result.skip_reason == "cooldown_active"
        assert not mock_factory.called

    def test_failed_notifications_not_counted(self):
        """delivery_status='failed' must not count toward the daily limit."""
        from app.initiative.evaluator import evaluate
        from app.memory.models import NotificationLog
        db = _make_db()
        sid = "user:13"

        # Add a failed notification today — should not block
        db.add(NotificationLog(
            session_id=sid,
            notification_type="proactive_initiative",
            fact_id="init:user:13:fail",
            payload_json="{}",
            delivery_channel="sse",
            delivery_status="failed",
            created_at=_utc_now(),
        ))
        db.commit()

        haiku_json = json.dumps({"decision": "send", "message": "¡Hola!", "reasoning": "r"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand := _candidate(session_id=sid), db)

        assert result.decision == "send"

    def test_no_prior_notifications_passes_limits(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        cand = _candidate(session_id="user:14")
        haiku_json = json.dumps({"decision": "send", "message": "Hola", "reasoning": "r"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "send"


# ---------------------------------------------------------------------------
# Model skip
# ---------------------------------------------------------------------------

class TestEvaluatorModelSkip:
    def test_haiku_skip_returns_model_skip(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        cand = _candidate()
        haiku_json = json.dumps({"decision": "skip", "message": None, "reasoning": "no context"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "skip"
        assert result.skip_reason == "model_skip"
        assert result.haiku_verdict == "skip"
        assert result.message is None

    def test_haiku_skip_persists_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        cand = _candidate()
        haiku_json = json.dumps({"decision": "skip", "reasoning": "not a good time"})
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog)).first()
        assert log is not None
        assert log.decision == "skip"
        assert log.skip_reason == "model_skip"
        assert log.haiku_verdict == "skip"
        assert log.haiku_reasoning == "not a good time"

    def test_invalid_json_from_haiku_returns_model_skip(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        cand = _candidate()
        mock_factory = _mock_haiku("this is not json {{")

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        # JSON parse falls back to {"decision": "skip", "reasoning": "json_parse_error"}
        assert result.decision == "skip"
        assert result.skip_reason == "model_skip"


# ---------------------------------------------------------------------------
# Evaluator error
# ---------------------------------------------------------------------------

class TestEvaluatorError:
    def test_haiku_raises_returns_evaluator_error(self):
        from app.initiative.evaluator import evaluate
        db = _make_db()
        cand = _candidate()
        mock_factory = MagicMock(side_effect=RuntimeError("provider down"))

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "skip"
        assert result.skip_reason == "evaluator_error"

    def test_evaluator_error_does_not_raise(self):
        """evaluate() must never propagate exceptions."""
        from app.initiative.evaluator import evaluate
        db = _make_db()
        cand = _candidate()
        mock_factory = MagicMock(side_effect=RuntimeError("boom"))

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            # Must not raise
            result = evaluate(cand, db)
        assert result is not None

    def test_evaluator_error_persists_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        cand = _candidate()
        mock_factory = MagicMock(side_effect=ValueError("fail"))

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog)).first()
        assert log is not None
        assert log.skip_reason == "evaluator_error"


# ---------------------------------------------------------------------------
# open_loop trigger — resolved signal
# ---------------------------------------------------------------------------

class TestEvaluatorOpenLoopResolved:
    def _make_open_loop(self, db: Session, session_id: str) -> str:
        from app.memory.models import OpenLoop
        lid = "ol_test1234"
        db.add(OpenLoop(
            id=lid,
            session_id=session_id,
            user_message="Voy a buscar trabajo.",
            extracted_intent="buscar trabajo",
            detected_at=_utc_now() - timedelta(days=4),
            expires_at=_utc_now() + timedelta(days=26),
            status="pending",
        ))
        db.commit()
        return lid

    def test_open_loop_resolved_signal_marks_loop(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import OpenLoop
        db = _make_db()
        sid = "user:50"
        lid = self._make_open_loop(db, sid)
        cand = _candidate(
            trigger_type="open_loop",
            session_id=sid,
            context={"extracted_intent": "buscar trabajo", "days_since_detected": 4},
            open_loop_id=lid,
        )
        haiku_json = json.dumps({
            "decision": "skip",
            "open_loop_resolved": True,
            "message": None,
            "reasoning": "ya lo resolvió",
        })
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "skip"
        assert result.skip_reason == "open_loop_resolved"

        loop = db.exec(select(OpenLoop).where(OpenLoop.id == lid)).first()
        assert loop.status == "resolved"
        assert loop.resolved_at is not None

    def test_open_loop_resolved_persists_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        sid = "user:51"
        lid = self._make_open_loop(db, sid)
        cand = _candidate(trigger_type="open_loop", session_id=sid,
                          context={}, open_loop_id=lid)
        haiku_json = json.dumps({
            "decision": "skip", "open_loop_resolved": True, "reasoning": "resuelto"
        })
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog).where(InitiativeEvalLog.session_id == sid)).first()
        assert log is not None
        assert log.skip_reason == "open_loop_resolved"
        assert log.open_loop_id == lid

    def test_open_loop_send_without_resolved_signal(self):
        """open_loop_resolved missing/false → normal send path."""
        from app.initiative.evaluator import evaluate
        from app.memory.models import OpenLoop
        db = _make_db()
        sid = "user:52"
        lid = self._make_open_loop(db, sid)
        cand = _candidate(trigger_type="open_loop", session_id=sid,
                          context={"extracted_intent": "buscar trabajo"}, open_loop_id=lid)
        haiku_json = json.dumps({
            "decision": "send",
            "open_loop_resolved": False,
            "message": "¿Cómo va la búsqueda de trabajo?",
            "reasoning": "still pending",
        })
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "send"
        assert result.message == "¿Cómo va la búsqueda de trabajo?"

        # Loop must NOT be marked resolved
        loop = db.exec(select(OpenLoop).where(OpenLoop.id == lid)).first()
        assert loop.status == "pending"

    def test_open_loop_resolved_true_with_send_decision_still_skips(self):
        """If Haiku sends resolved=True AND decision='send', resolved takes precedence."""
        from app.initiative.evaluator import evaluate
        db = _make_db()
        sid = "user:53"
        lid = "ol_testaaaa"
        from app.memory.models import OpenLoop
        db.add(OpenLoop(
            id=lid, session_id=sid, user_message="m",
            extracted_intent="i", detected_at=_utc_now() - timedelta(days=4),
            expires_at=_utc_now() + timedelta(days=26), status="pending",
        ))
        db.commit()
        cand = _candidate(trigger_type="open_loop", session_id=sid,
                          context={}, open_loop_id=lid)
        haiku_json = json.dumps({
            "decision": "send",
            "open_loop_resolved": True,
            "message": "algo",
            "reasoning": "conflict",
        })
        mock_factory = _mock_haiku(haiku_json)

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            result = evaluate(cand, db)

        assert result.decision == "skip"
        assert result.skip_reason == "open_loop_resolved"


# ---------------------------------------------------------------------------
# SocialProfile injection
# ---------------------------------------------------------------------------

class TestEvaluatorSocialProfile:
    def test_social_profile_values_in_prompt(self):
        """The build_user_message must include opinion and trust from SocialProfile."""
        from app.initiative.evaluator import _build_user_message, _get_social_profile
        db = _make_db()
        sid = "user:60"
        _add_social_profile(db, sid, opinion=1.23, trust=0.85)

        cand = _candidate(session_id=sid)
        social = _get_social_profile(sid, db)
        msg = _build_user_message(cand, social)

        assert "opinion=1.23" in msg
        assert "trust=0.85" in msg

    def test_no_social_profile_uses_zero_defaults(self):
        from app.initiative.evaluator import _build_user_message, _get_social_profile
        db = _make_db()
        sid = "user:61"
        social = _get_social_profile(sid, db)
        cand = _candidate(session_id=sid)
        msg = _build_user_message(cand, social)

        assert "opinion=0.00" in msg
        assert "trust=0.00" in msg

    def test_social_profile_fetched_before_haiku(self):
        """evaluate() calls build_ai_provider (Haiku) — social profile should be in the prompt."""
        from app.initiative.evaluator import evaluate
        db = _make_db()
        sid = "user:62"
        _add_social_profile(db, sid, opinion=-0.5, trust=0.4)
        cand = _candidate(session_id=sid)

        captured_request: list = []

        def fake_factory(provider_name, model):
            mock_provider = MagicMock()
            def capture_generate(req):
                captured_request.append(req)
                resp = MagicMock()
                resp.ok = True
                resp.text = json.dumps({"decision": "skip", "reasoning": "ok"})
                return resp
            mock_provider.generate.side_effect = capture_generate
            return mock_provider

        with patch("app.initiative.evaluator.build_ai_provider", fake_factory):
            evaluate(cand, db)

        assert len(captured_request) == 1
        assert "opinion=-0.50" in captured_request[0].user_message
        assert "trust=0.40" in captured_request[0].user_message


# ---------------------------------------------------------------------------
# Prompt construction per trigger type
# ---------------------------------------------------------------------------

class TestEvaluatorPromptConstruction:
    def test_conversation_abandoned_context_in_prompt(self):
        from app.initiative.evaluator import _build_user_message
        ctx = {
            "hours_since_last_message": 36.5,
            "last_messages": [
                {"role": "user", "text": "Hasta luego."},
                {"role": "sity", "text": "¡Hasta!"},
            ],
        }
        cand = _candidate(trigger_type="conversation_abandoned", context=ctx)
        msg = _build_user_message(cand, None)

        assert "36.5" in msg
        assert "Hasta luego." in msg
        assert "¡Hasta!" in msg

    def test_long_inactivity_context_in_prompt(self):
        from app.initiative.evaluator import _build_user_message
        ctx = {
            "days_since_last_message": 7.2,
            "last_message_role": "user",
            "last_message_text": "Oye, te escribo mañana.",
        }
        cand = _candidate(trigger_type="long_inactivity", context=ctx)
        msg = _build_user_message(cand, None)

        assert "7.2" in msg
        assert "Oye, te escribo mañana." in msg

    def test_open_loop_context_in_prompt(self):
        from app.initiative.evaluator import _build_user_message
        ctx = {
            "extracted_intent": "buscar trabajo esta semana",
            "days_since_detected": 5.0,
            "original_user_message": "Voy a buscar trabajo.",
            "recent_messages_after_detection": [
                {"role": "sity", "text": "¿Y cómo va?"},
            ],
        }
        cand = _candidate(trigger_type="open_loop", context=ctx)
        msg = _build_user_message(cand, None)

        assert "buscar trabajo esta semana" in msg
        assert "5.0" in msg
        assert "¿Y cómo va?" in msg

    def test_open_loop_no_after_messages_note(self):
        from app.initiative.evaluator import _build_user_message
        ctx = {
            "extracted_intent": "llamar al médico",
            "days_since_detected": 3.0,
            "original_user_message": "Lo llamo esta semana.",
            "recent_messages_after_detection": [],
        }
        cand = _candidate(trigger_type="open_loop", context=ctx)
        msg = _build_user_message(cand, None)

        assert "No ha habido mensajes" in msg

    def test_open_loop_uses_open_loop_system_prompt(self):
        """open_loop trigger must use the open_loop_resolved JSON format."""
        from app.initiative.evaluator import _SYSTEM_OPEN_LOOP, _SYSTEM_STANDARD, evaluate
        db = _make_db()
        cand = _candidate(trigger_type="open_loop", context={})

        captured_request: list = []

        def fake_factory(provider_name, model):
            mock_provider = MagicMock()
            def capture(req):
                captured_request.append(req)
                resp = MagicMock()
                resp.ok = True
                resp.text = json.dumps({"decision": "skip", "open_loop_resolved": False, "reasoning": "r"})
                return resp
            mock_provider.generate.side_effect = capture
            return mock_provider

        with patch("app.initiative.evaluator.build_ai_provider", fake_factory):
            evaluate(cand, db)

        assert len(captured_request) == 1
        assert "open_loop_resolved" in captured_request[0].system_prompt

    def test_standard_trigger_uses_standard_system_prompt(self):
        from app.initiative.evaluator import _SYSTEM_STANDARD, evaluate
        db = _make_db()
        cand = _candidate(trigger_type="conversation_abandoned", context={})

        captured_request: list = []

        def fake_factory(provider_name, model):
            mock_provider = MagicMock()
            def capture(req):
                captured_request.append(req)
                resp = MagicMock()
                resp.ok = True
                resp.text = json.dumps({"decision": "skip", "reasoning": "r"})
                return resp
            mock_provider.generate.side_effect = capture
            return mock_provider

        with patch("app.initiative.evaluator.build_ai_provider", fake_factory):
            evaluate(cand, db)

        assert "open_loop_resolved" not in captured_request[0].system_prompt


# ---------------------------------------------------------------------------
# EvalLog — trigger_context_json and open_loop_id fields
# ---------------------------------------------------------------------------

class TestEvalLogFields:
    def test_trigger_context_json_serialized(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        ctx = {"hours_since_last_message": 25.5, "last_messages": []}
        cand = _candidate(context=ctx)
        mock_factory = _mock_haiku(json.dumps({"decision": "skip", "reasoning": "r"}))

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog)).first()
        parsed = json.loads(log.trigger_context_json)
        assert parsed["hours_since_last_message"] == 25.5

    def test_open_loop_id_stored_in_eval_log(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        cand = _candidate(trigger_type="open_loop", open_loop_id="ol_abcd1234", context={})
        mock_factory = _mock_haiku(json.dumps({"decision": "skip", "reasoning": "r"}))

        with patch("app.initiative.evaluator.build_ai_provider", mock_factory):
            evaluate(cand, db)

        log = db.exec(select(InitiativeEvalLog)).first()
        assert log.open_loop_id == "ol_abcd1234"

    def test_multiple_evaluations_multiple_logs(self):
        from app.initiative.evaluator import evaluate
        from app.memory.models import InitiativeEvalLog
        db = _make_db()
        haiku_skip = json.dumps({"decision": "skip", "reasoning": "r"})
        haiku_send = json.dumps({"decision": "send", "message": "hola", "reasoning": "r"})

        cand1 = _candidate(session_id="user:70")
        cand2 = _candidate(session_id="user:71")

        with patch("app.initiative.evaluator.build_ai_provider", _mock_haiku(haiku_skip)):
            evaluate(cand1, db)
        with patch("app.initiative.evaluator.build_ai_provider", _mock_haiku(haiku_send)):
            evaluate(cand2, db)

        logs = db.exec(select(InitiativeEvalLog)).all()
        assert len(logs) == 2
        decisions = {log.session_id: log.decision for log in logs}
        assert decisions["user:70"] == "skip"
        assert decisions["user:71"] == "send"

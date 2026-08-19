"""Tests for Initiative Step 2 — open_loop_hook and detector.

Covers:
  open_loop_hook:
    - Haiku returns has_intent=true → OpenLoop created
    - Haiku returns has_intent=false → no OpenLoop created
    - Invalid JSON from Haiku → no OpenLoop, logs WARN (no exception)
    - Haiku call fails entirely → no OpenLoop, logs WARN (no exception)
    - Deduplication: 2nd call within 24h skips creation
    - Dedup window: 25h-old pending loop does NOT block creation

  detector:
    - conversation_abandoned: returned when last message is sity, age in window
    - conversation_abandoned: not returned if last message is user role
    - conversation_abandoned: not returned if age < min_hours
    - conversation_abandoned: not returned if age > max_days
    - long_inactivity: returned after min_days with no messages
    - long_inactivity: not returned if recent messages exist
    - open_loop: returned for pending loops older than min_days
    - open_loop: not returned for loops newer than min_days
    - open_loop: not returned for non-pending status
    - Guest sessions: always empty result
    - Sub-toggle disabled: trigger not returned even if condition matches
    - Multiple triggers: all matching triggers returned
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


def _msg(db: Session, session_id: str, role: str, text: str, age_hours: float = 0) -> None:
    from app.memory.models import ChatMessage
    created = _utc_now() - timedelta(hours=age_hours)
    db.add(ChatMessage(
        session_id=session_id,
        role=role,
        text=text,
        created_at=created,
    ))
    db.commit()


def _open_loop(
    db: Session,
    session_id: str,
    status: str = "pending",
    age_hours: float = 0,
    intent: str = "buscar trabajo",
) -> str:
    from app.memory.models import OpenLoop
    from secrets import token_hex
    lid = f"ol_{token_hex(4)}"
    detected = _utc_now() - timedelta(hours=age_hours)
    db.add(OpenLoop(
        id=lid,
        session_id=session_id,
        user_message="Voy a buscar trabajo.",
        extracted_intent=intent,
        detected_at=detected,
        expires_at=detected + timedelta(days=30),
        status=status,
    ))
    db.commit()
    return lid


def _mock_haiku_response(text: str) -> MagicMock:
    r = MagicMock()
    r.ok = True
    r.text = text
    return r


# ---------------------------------------------------------------------------
# open_loop_hook — _call_haiku + _save_open_loop (tested via internal fns)
# ---------------------------------------------------------------------------

class TestOpenLoopHookDetection:
    def _call_detect_task(self, haiku_text: str | None, session_id: str) -> None:
        """Run _detect_open_loop_task with a mocked Haiku provider."""
        from app.initiative.open_loop_hook import _detect_open_loop_task

        mock_response = MagicMock()
        mock_response.ok = (haiku_text is not None)
        mock_response.text = haiku_text or ""

        with patch("app.initiative.open_loop_hook.build_ai_provider") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.generate.return_value = mock_response
            mock_factory.return_value = mock_provider
            _detect_open_loop_task(
                session_id=session_id,
                user_message="Voy a buscar trabajo esta semana.",
                trace_id="trc_test",
            )

    def test_has_intent_true_creates_open_loop(self):
        from app.memory.models import OpenLoop
        haiku_json = json.dumps({"has_intent": True, "intent": "buscar trabajo esta semana"})
        sid = "user:42"

        with patch("app.initiative.open_loop_hook.engine") as mock_engine:
            # Use real in-memory DB for this test
            real_db = _make_db()
            mock_engine.__class__ = real_db.bind.__class__

            # Patch Session to use our in-memory DB
            with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=real_db)
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_session_cls.return_value = mock_ctx

                self._call_detect_task(haiku_json, sid)

            loops = real_db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
            assert len(loops) == 1
            assert loops[0].extracted_intent == "buscar trabajo esta semana"
            assert loops[0].status == "pending"

    def test_has_intent_false_no_open_loop(self):
        from app.memory.models import OpenLoop
        haiku_json = json.dumps({"has_intent": False, "intent": None})
        sid = "user:43"

        with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
            real_db = _make_db()
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=real_db)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_cls.return_value = mock_ctx

            self._call_detect_task(haiku_json, sid)

        loops = real_db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 0

    def test_invalid_json_no_open_loop_no_exception(self):
        from app.memory.models import OpenLoop
        sid = "user:44"
        real_db = _make_db()

        with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=real_db)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_cls.return_value = mock_ctx

            self._call_detect_task("not valid json {{{", sid)

        loops = real_db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 0

    def test_haiku_error_no_exception_propagated(self):
        """If build_ai_provider raises or .generate raises, task swallows the error."""
        from app.initiative.open_loop_hook import _detect_open_loop_task

        with patch("app.initiative.open_loop_hook.build_ai_provider") as mock_factory:
            mock_factory.side_effect = RuntimeError("provider unavailable")
            # Must NOT raise
            _detect_open_loop_task("user:45", "Tengo que ir al médico.", "trc_x")

    def test_haiku_provider_not_ok_no_open_loop(self):
        from app.memory.models import OpenLoop
        sid = "user:46"
        real_db = _make_db()

        with patch("app.initiative.open_loop_hook.build_ai_provider") as mock_factory:
            mock_provider = MagicMock()
            mock_provider.generate.return_value = MagicMock(ok=False, text="")
            mock_factory.return_value = mock_provider

            with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=real_db)
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_session_cls.return_value = mock_ctx

                from app.initiative.open_loop_hook import _detect_open_loop_task
                _detect_open_loop_task(sid, "Lo miro esta semana.", "trc_y")

        loops = real_db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 0

    def test_json_fenced_with_intent_creates_open_loop(self):
        """Haiku wraps JSON in ```json fences — must parse correctly and create the loop."""
        from app.memory.models import OpenLoop
        fenced = "```json\n" + json.dumps({"has_intent": True, "intent": "llamar al hermano esta semana"}) + "\n```"
        sid = "user:47"
        real_db = _make_db()

        with patch("app.initiative.open_loop_hook.engine") as mock_engine:
            mock_engine.__class__ = real_db.bind.__class__
            with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=real_db)
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_session_cls.return_value = mock_ctx
                self._call_detect_task(fenced, sid)

        loops = real_db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 1
        assert loops[0].extracted_intent == "llamar al hermano esta semana"

    def test_json_fenced_no_intent_no_open_loop(self):
        """Haiku wraps JSON in ```json fences with has_intent=false — must not create loop."""
        from app.memory.models import OpenLoop
        fenced = "```json\n" + json.dumps({"has_intent": False, "intent": None}) + "\n```"
        sid = "user:48"
        real_db = _make_db()

        with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=real_db)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_cls.return_value = mock_ctx
            self._call_detect_task(fenced, sid)

        loops = real_db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 0


class TestStripJsonFences:
    def test_strips_json_block(self):
        from app.initiative._json_utils import strip_json_fences
        raw = "```json\n{\"a\": 1}\n```"
        assert strip_json_fences(raw) == '{"a": 1}'

    def test_strips_plain_code_block(self):
        from app.initiative._json_utils import strip_json_fences
        raw = "```\n{\"a\": 1}\n```"
        assert strip_json_fences(raw) == '{"a": 1}'

    def test_passthrough_clean_json(self):
        from app.initiative._json_utils import strip_json_fences
        raw = '{"decision": "send"}'
        assert strip_json_fences(raw) == raw

    def test_strips_whitespace(self):
        from app.initiative._json_utils import strip_json_fences
        raw = "  ```json\n{\"x\": true}\n```  "
        assert strip_json_fences(raw) == '{"x": true}'


class TestOpenLoopHookDeduplication:
    def _run_save(self, db: Session, session_id: str, intent: str = "buscar trabajo") -> None:
        from app.initiative.open_loop_hook import _save_open_loop
        with patch("app.initiative.open_loop_hook.Session") as mock_session_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=db)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_cls.return_value = mock_ctx
            _save_open_loop(
                session_id=session_id,
                user_message="Voy a buscar trabajo.",
                extracted_intent=intent,
                trace_id="trc_dedup",
            )

    def test_second_call_within_24h_skipped(self):
        from app.memory.models import OpenLoop
        db = _make_db()
        sid = "user:100"

        self._run_save(db, sid)
        self._run_save(db, sid)  # second call — should be skipped

        loops = db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 1

    def test_call_after_25h_creates_new_loop(self):
        from app.memory.models import OpenLoop
        db = _make_db()
        sid = "user:101"

        # Create an existing pending loop older than 24h
        old_detected = _utc_now() - timedelta(hours=25)
        db.add(OpenLoop(
            id="ol_oldie",
            session_id=sid,
            user_message="Voy a llamar.",
            extracted_intent="llamar al médico",
            detected_at=old_detected,
            expires_at=old_detected + timedelta(days=30),
            status="pending",
        ))
        db.commit()

        self._run_save(db, sid, intent="nueva intención")

        loops = db.exec(select(OpenLoop).where(OpenLoop.session_id == sid)).all()
        assert len(loops) == 2

    def test_resolved_loop_does_not_block_new_creation(self):
        from app.memory.models import OpenLoop
        db = _make_db()
        sid = "user:102"

        # Create a recent loop with resolved status — should not block
        db.add(OpenLoop(
            id="ol_resolved",
            session_id=sid,
            user_message="Lo miré.",
            extracted_intent="revisar presupuesto",
            detected_at=_utc_now() - timedelta(hours=1),
            expires_at=_utc_now() + timedelta(days=29),
            status="resolved",
        ))
        db.commit()

        self._run_save(db, sid, intent="otra intención")

        loops = db.exec(
            select(OpenLoop).where(OpenLoop.session_id == sid, OpenLoop.status == "pending")
        ).all()
        assert len(loops) == 1


# ---------------------------------------------------------------------------
# detector — individual trigger checks
# ---------------------------------------------------------------------------

class TestDetectorConversationAbandoned:
    def test_returns_candidate_when_last_is_sity_in_window(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:200"
        _msg(db, sid, "user", "Hola, ¿puedes ayudarme?", age_hours=50)
        _msg(db, sid, "sity", "Claro, cuéntame más.", age_hours=48)  # 48h ago, sity last

        candidates = get_trigger_candidates(sid, db)
        assert any(c.trigger_type == "conversation_abandoned" for c in candidates)

    def test_not_returned_when_last_is_user(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:201"
        _msg(db, sid, "sity", "Te respondo ahora.", age_hours=50)
        _msg(db, sid, "user", "Gracias.", age_hours=48)  # user has the last word

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "conversation_abandoned" for c in candidates)

    def test_not_returned_when_too_recent(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:202"
        _msg(db, sid, "sity", "Hasta luego.", age_hours=5)  # only 5h ago

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "conversation_abandoned" for c in candidates)

    def test_not_returned_when_too_old(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:203"
        _msg(db, sid, "sity", "Buenas noches.", age_hours=200)  # 8+ days ago

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "conversation_abandoned" for c in candidates)

    def test_context_contains_hours_and_messages(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:204"
        _msg(db, sid, "user", "Hola.", age_hours=50)
        _msg(db, sid, "sity", "¿Qué más?", age_hours=30)

        candidates = get_trigger_candidates(sid, db)
        ca = next((c for c in candidates if c.trigger_type == "conversation_abandoned"), None)
        assert ca is not None
        assert "hours_since_last_message" in ca.context
        assert "last_messages" in ca.context
        assert len(ca.context["last_messages"]) > 0


class TestDetectorLongInactivity:
    def test_returned_after_min_days(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:210"
        _msg(db, sid, "user", "Hasta luego.", age_hours=6 * 24)  # 6 days ago

        candidates = get_trigger_candidates(sid, db)
        assert any(c.trigger_type == "long_inactivity" for c in candidates)

    def test_not_returned_when_recent(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:211"
        _msg(db, sid, "user", "Hola.", age_hours=2 * 24)  # 2 days ago

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "long_inactivity" for c in candidates)

    def test_no_messages_returns_none(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:212"

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "long_inactivity" for c in candidates)

    def test_context_contains_days_and_last_message(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:213"
        _msg(db, sid, "sity", "Te mando la info luego.", age_hours=7 * 24)

        candidates = get_trigger_candidates(sid, db)
        li = next((c for c in candidates if c.trigger_type == "long_inactivity"), None)
        assert li is not None
        assert "days_since_last_message" in li.context
        assert li.context["last_message_role"] == "sity"


class TestDetectorOpenLoop:
    def test_returned_for_pending_loop_older_than_min_days(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:220"
        _open_loop(db, sid, status="pending", age_hours=4 * 24)  # 4 days old

        candidates = get_trigger_candidates(sid, db)
        assert any(c.trigger_type == "open_loop" for c in candidates)

    def test_not_returned_for_loop_newer_than_min_days(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:221"
        _open_loop(db, sid, status="pending", age_hours=1 * 24)  # only 1 day old

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "open_loop" for c in candidates)

    def test_not_returned_for_resolved_loop(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:222"
        _open_loop(db, sid, status="resolved", age_hours=5 * 24)

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "open_loop" for c in candidates)

    def test_not_returned_for_dispatched_loop(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:223"
        _open_loop(db, sid, status="dispatched", age_hours=5 * 24)

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "open_loop" for c in candidates)

    def test_open_loop_id_set_on_candidate(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:224"
        lid = _open_loop(db, sid, status="pending", age_hours=5 * 24)

        candidates = get_trigger_candidates(sid, db)
        ol = next((c for c in candidates if c.trigger_type == "open_loop"), None)
        assert ol is not None
        assert ol.open_loop_id == lid

    def test_oldest_loop_returned_when_multiple(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:225"
        _open_loop(db, sid, status="pending", age_hours=5 * 24, intent="intent A")
        older_lid = _open_loop(db, sid, status="pending", age_hours=10 * 24, intent="intent B")

        candidates = get_trigger_candidates(sid, db)
        ol = next((c for c in candidates if c.trigger_type == "open_loop"), None)
        assert ol is not None
        assert ol.open_loop_id == older_lid  # oldest wins


# ---------------------------------------------------------------------------
# detector — role isolation and toggle enforcement
# ---------------------------------------------------------------------------

class TestDetectorIsolation:
    def test_guest_session_returns_empty(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "guest:abc"
        _msg(db, sid, "sity", "Hasta luego.", age_hours=48)

        candidates = get_trigger_candidates(sid, db)
        assert candidates == []

    def test_master_toggle_disabled_returns_empty(self):
        from app.initiative.detector import get_trigger_candidates
        from app.initiative.settings import set_initiative_settings, InitiativeSettings
        db = _make_db()
        sid = "user:300"
        _msg(db, sid, "sity", "Adiós.", age_hours=48)
        set_initiative_settings(db, InitiativeSettings(enabled=False), session_id=sid)

        candidates = get_trigger_candidates(sid, db)
        assert candidates == []

    def test_sub_toggle_conversation_abandoned_disabled(self):
        from app.initiative.detector import get_trigger_candidates
        from app.initiative.settings import set_initiative_settings, InitiativeSettings
        db = _make_db()
        sid = "user:301"
        _msg(db, sid, "sity", "Hasta pronto.", age_hours=48)
        set_initiative_settings(
            db,
            InitiativeSettings(trigger_conversation_abandoned=False),
            session_id=sid,
        )

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "conversation_abandoned" for c in candidates)

    def test_sub_toggle_long_inactivity_disabled(self):
        from app.initiative.detector import get_trigger_candidates
        from app.initiative.settings import set_initiative_settings, InitiativeSettings
        db = _make_db()
        sid = "user:302"
        _msg(db, sid, "user", "Hola.", age_hours=7 * 24)
        set_initiative_settings(
            db,
            InitiativeSettings(trigger_long_inactivity=False),
            session_id=sid,
        )

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "long_inactivity" for c in candidates)

    def test_sub_toggle_open_loop_disabled(self):
        from app.initiative.detector import get_trigger_candidates
        from app.initiative.settings import set_initiative_settings, InitiativeSettings
        db = _make_db()
        sid = "user:303"
        _open_loop(db, sid, status="pending", age_hours=5 * 24)
        set_initiative_settings(
            db,
            InitiativeSettings(trigger_open_loop=False),
            session_id=sid,
        )

        candidates = get_trigger_candidates(sid, db)
        assert not any(c.trigger_type == "open_loop" for c in candidates)

    def test_multiple_triggers_all_returned(self):
        """All three active triggers are included in the result."""
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()
        sid = "user:310"

        # conversation_abandoned condition: last msg is sity, 48h ago
        _msg(db, sid, "user", "Hola.", age_hours=96)
        _msg(db, sid, "sity", "Oye.", age_hours=48)

        # long_inactivity would also fire (48h < 5 days → actually NO)
        # Let's use a different session structure: just test open_loop + conversation_abandoned
        _open_loop(db, sid, status="pending", age_hours=5 * 24)

        candidates = get_trigger_candidates(sid, db)
        trigger_types = {c.trigger_type for c in candidates}
        assert "conversation_abandoned" in trigger_types
        assert "open_loop" in trigger_types

    def test_different_sessions_isolated(self):
        from app.initiative.detector import get_trigger_candidates
        db = _make_db()

        _msg(db, "user:400", "sity", "Hasta luego.", age_hours=48)
        _msg(db, "user:401", "user", "Hola.", age_hours=2)

        candidates_400 = get_trigger_candidates("user:400", db)
        candidates_401 = get_trigger_candidates("user:401", db)

        assert any(c.trigger_type == "conversation_abandoned" for c in candidates_400)
        assert not any(c.trigger_type == "conversation_abandoned" for c in candidates_401)

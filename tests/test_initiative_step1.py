"""Tests for Initiative Step 1 — data models and settings.

Covers:
  - OpenLoop CRUD and status lifecycle
  - InitiativeEvalLog CRUD
  - Session isolation (session_id scoping)
  - get/set_initiative_settings: per-session scope, global fallback, correct defaults
  - All 4 toggles default to True (opt-out, not opt-in)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sqlmodel import Session, SQLModel, create_engine, select


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ol_id(suffix: str = "aabbccdd") -> str:
    return f"ol_{suffix}"


# ---------------------------------------------------------------------------
# OpenLoop — CRUD
# ---------------------------------------------------------------------------

class TestOpenLoopCRUD:
    def test_create_and_retrieve(self):
        from app.memory.models import OpenLoop
        db = _make_session()
        expires = _utc_now() + timedelta(days=30)
        loop = OpenLoop(
            id=_ol_id(),
            session_id="user:1",
            user_message="Voy a buscar trabajo esta semana.",
            extracted_intent="buscar trabajo esta semana",
            expires_at=expires,
        )
        db.add(loop)
        db.commit()

        retrieved = db.exec(select(OpenLoop).where(OpenLoop.id == _ol_id())).first()
        assert retrieved is not None
        assert retrieved.session_id == "user:1"
        assert retrieved.extracted_intent == "buscar trabajo esta semana"
        assert retrieved.status == "pending"
        assert retrieved.resolved_at is None

    def test_default_status_is_pending(self):
        from app.memory.models import OpenLoop
        db = _make_session()
        loop = OpenLoop(
            id=_ol_id("11111111"),
            session_id="user:1",
            user_message="Tengo que llamar al médico.",
            expires_at=_utc_now() + timedelta(days=30),
        )
        db.add(loop)
        db.commit()
        retrieved = db.exec(select(OpenLoop).where(OpenLoop.id == _ol_id("11111111"))).first()
        assert retrieved.status == "pending"
        assert retrieved.extracted_intent == ""

    def test_status_transitions(self):
        from app.memory.models import OpenLoop
        db = _make_session()
        expires = _utc_now() + timedelta(days=30)

        for status, oid in [
            ("resolved",   _ol_id("aaaa0001")),
            ("dispatched", _ol_id("aaaa0002")),
            ("expired",    _ol_id("aaaa0003")),
        ]:
            loop = OpenLoop(
                id=oid,
                session_id="user:1",
                user_message="message",
                expires_at=expires,
                status=status,
            )
            db.add(loop)
        db.commit()

        for status, oid in [
            ("resolved",   _ol_id("aaaa0001")),
            ("dispatched", _ol_id("aaaa0002")),
            ("expired",    _ol_id("aaaa0003")),
        ]:
            row = db.exec(select(OpenLoop).where(OpenLoop.id == oid)).first()
            assert row.status == status

    def test_update_status_to_resolved(self):
        from app.memory.models import OpenLoop
        db = _make_session()
        loop = OpenLoop(
            id=_ol_id("resolve01"),
            session_id="user:1",
            user_message="Lo miro esta semana.",
            expires_at=_utc_now() + timedelta(days=30),
        )
        db.add(loop)
        db.commit()

        row = db.exec(select(OpenLoop).where(OpenLoop.id == _ol_id("resolve01"))).first()
        row.status = "resolved"
        row.resolved_at = _utc_now()
        db.add(row)
        db.commit()

        updated = db.exec(select(OpenLoop).where(OpenLoop.id == _ol_id("resolve01"))).first()
        assert updated.status == "resolved"
        assert updated.resolved_at is not None


# ---------------------------------------------------------------------------
# OpenLoop — session isolation
# ---------------------------------------------------------------------------

class TestOpenLoopSessionIsolation:
    def test_different_sessions_dont_mix(self):
        from app.memory.models import OpenLoop
        db = _make_session()

        for i, sid in enumerate(["user:1", "user:2", "user:3"]):
            db.add(OpenLoop(
                id=_ol_id(f"iso0000{i}"),
                session_id=sid,
                user_message=f"Intención de {sid}",
                expires_at=_utc_now() + timedelta(days=30),
            ))
        db.commit()

        loops_1 = db.exec(
            select(OpenLoop).where(OpenLoop.session_id == "user:1")
        ).all()
        assert len(loops_1) == 1
        assert loops_1[0].session_id == "user:1"

    def test_query_by_status_and_session(self):
        from app.memory.models import OpenLoop
        db = _make_session()
        expires = _utc_now() + timedelta(days=30)

        db.add(OpenLoop(id="ol_p1", session_id="user:1", user_message="x", expires_at=expires, status="pending"))
        db.add(OpenLoop(id="ol_r1", session_id="user:1", user_message="y", expires_at=expires, status="resolved"))
        db.add(OpenLoop(id="ol_p2", session_id="user:2", user_message="z", expires_at=expires, status="pending"))
        db.commit()

        pending_1 = db.exec(
            select(OpenLoop).where(
                OpenLoop.session_id == "user:1",
                OpenLoop.status == "pending",
            )
        ).all()
        assert len(pending_1) == 1
        assert pending_1[0].id == "ol_p1"


# ---------------------------------------------------------------------------
# InitiativeEvalLog — CRUD
# ---------------------------------------------------------------------------

class TestInitiativeEvalLogCRUD:
    def test_create_send_decision(self):
        from app.memory.models import InitiativeEvalLog
        db = _make_session()
        log = InitiativeEvalLog(
            session_id="user:1",
            trigger_type="long_inactivity",
            decision="send",
            haiku_verdict="send",
            haiku_reasoning="7 days of inactivity — worth checking in.",
            message_preview="¿Todo bien? Hace unos días que no hablamos.",
            trigger_context_json='{"days_since_last": 7}',
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        assert log.id is not None
        assert log.decision == "send"
        assert log.skip_reason is None
        assert log.open_loop_id is None

    def test_create_skip_decision(self):
        from app.memory.models import InitiativeEvalLog
        db = _make_session()
        log = InitiativeEvalLog(
            session_id="user:2",
            trigger_type="conversation_abandoned",
            decision="skip",
            skip_reason="trust_too_low",
            haiku_verdict=None,
            trigger_context_json='{"hours_since_last": 30}',
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        assert log.id is not None
        assert log.decision == "skip"
        assert log.skip_reason == "trust_too_low"
        assert log.haiku_verdict is None
        assert log.message_preview is None

    def test_open_loop_id_stored(self):
        from app.memory.models import InitiativeEvalLog
        db = _make_session()
        log = InitiativeEvalLog(
            session_id="user:1",
            trigger_type="open_loop",
            decision="send",
            haiku_verdict="send",
            open_loop_id="ol_aabbccdd",
            trigger_context_json="{}",
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        assert log.open_loop_id == "ol_aabbccdd"

    def test_multiple_logs_same_session(self):
        from app.memory.models import InitiativeEvalLog
        db = _make_session()
        for decision in ["send", "skip", "skip"]:
            db.add(InitiativeEvalLog(
                session_id="user:1",
                trigger_type="long_inactivity",
                decision=decision,
                trigger_context_json="{}",
            ))
        db.commit()

        rows = db.exec(
            select(InitiativeEvalLog).where(InitiativeEvalLog.session_id == "user:1")
        ).all()
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# InitiativeEvalLog — session isolation
# ---------------------------------------------------------------------------

class TestInitiativeEvalLogSessionIsolation:
    def test_logs_scoped_to_session(self):
        from app.memory.models import InitiativeEvalLog
        db = _make_session()
        for sid in ["user:1", "user:2"]:
            db.add(InitiativeEvalLog(
                session_id=sid,
                trigger_type="long_inactivity",
                decision="skip",
                skip_reason="no_trigger_condition",
                trigger_context_json="{}",
            ))
        db.commit()

        rows_1 = db.exec(
            select(InitiativeEvalLog).where(InitiativeEvalLog.session_id == "user:1")
        ).all()
        assert len(rows_1) == 1
        assert rows_1[0].session_id == "user:1"


# ---------------------------------------------------------------------------
# InitiativeSettings — defaults (all True, opt-out)
# ---------------------------------------------------------------------------

class TestInitiativeSettingsDefaults:
    def test_all_defaults_are_true(self):
        from app.initiative.settings import InitiativeSettings
        s = InitiativeSettings()
        assert s.enabled is True
        assert s.trigger_conversation_abandoned is True
        assert s.trigger_long_inactivity is True
        assert s.trigger_open_loop is True

    def test_get_returns_defaults_when_no_db_rows(self):
        from app.initiative.settings import get_initiative_settings
        db = _make_session()
        s = get_initiative_settings(db, session_id="user:1")
        assert s.enabled is True
        assert s.trigger_conversation_abandoned is True
        assert s.trigger_long_inactivity is True
        assert s.trigger_open_loop is True

    def test_get_without_session_id_returns_defaults(self):
        from app.initiative.settings import get_initiative_settings
        db = _make_session()
        s = get_initiative_settings(db, session_id=None)
        assert s.enabled is True


# ---------------------------------------------------------------------------
# InitiativeSettings — per-session write and read
# ---------------------------------------------------------------------------

class TestInitiativeSettingsPerSession:
    def test_set_and_get_per_session(self):
        from app.initiative.settings import get_initiative_settings, set_initiative_settings, InitiativeSettings
        db = _make_session()

        updated = set_initiative_settings(
            db,
            InitiativeSettings(enabled=False, trigger_long_inactivity=False),
            session_id="user:1",
        )
        assert updated.enabled is False
        assert updated.trigger_long_inactivity is False
        assert updated.trigger_conversation_abandoned is True  # unchanged → default
        assert updated.trigger_open_loop is True

    def test_session_overrides_do_not_affect_other_sessions(self):
        from app.initiative.settings import get_initiative_settings, set_initiative_settings, InitiativeSettings
        db = _make_session()

        set_initiative_settings(db, InitiativeSettings(enabled=False), session_id="user:1")

        s2 = get_initiative_settings(db, session_id="user:2")
        assert s2.enabled is True  # still default for user:2

    def test_global_fallback_applies_when_no_session_override(self):
        from app.initiative.settings import get_initiative_settings, set_initiative_settings, InitiativeSettings
        db = _make_session()

        # Write a global default (session_id=None)
        set_initiative_settings(db, InitiativeSettings(trigger_open_loop=False), session_id=None)

        # Session with no override should inherit global
        s = get_initiative_settings(db, session_id="user:99")
        assert s.trigger_open_loop is False

    def test_session_override_wins_over_global(self):
        from app.initiative.settings import get_initiative_settings, set_initiative_settings, InitiativeSettings
        db = _make_session()

        set_initiative_settings(db, InitiativeSettings(enabled=False), session_id=None)
        set_initiative_settings(db, InitiativeSettings(enabled=True), session_id="user:5")

        s = get_initiative_settings(db, session_id="user:5")
        assert s.enabled is True

    def test_set_all_four_toggles(self):
        from app.initiative.settings import get_initiative_settings, set_initiative_settings, InitiativeSettings
        db = _make_session()

        set_initiative_settings(
            db,
            InitiativeSettings(
                enabled=False,
                trigger_conversation_abandoned=False,
                trigger_long_inactivity=False,
                trigger_open_loop=False,
            ),
            session_id="user:10",
        )
        s = get_initiative_settings(db, session_id="user:10")
        assert s.enabled is False
        assert s.trigger_conversation_abandoned is False
        assert s.trigger_long_inactivity is False
        assert s.trigger_open_loop is False

    def test_partial_update_preserves_other_keys(self):
        """set_initiative_settings writes ALL 4 keys — a second call with different values
        overwrites only what changed."""
        from app.initiative.settings import get_initiative_settings, set_initiative_settings, InitiativeSettings
        db = _make_session()

        set_initiative_settings(db, InitiativeSettings(enabled=False), session_id="user:7")
        set_initiative_settings(db, InitiativeSettings(trigger_open_loop=False), session_id="user:7")

        s = get_initiative_settings(db, session_id="user:7")
        # Second call resets enabled back to default (True) since it wrote all 4 keys
        assert s.enabled is True
        assert s.trigger_open_loop is False

    def test_repeated_set_upserts_not_duplicates(self):
        """Calling set twice for the same session_id must not create duplicate Setting rows."""
        from app.initiative.settings import set_initiative_settings, InitiativeSettings
        from app.memory.models import Setting
        db = _make_session()

        set_initiative_settings(db, InitiativeSettings(enabled=False), session_id="user:3")
        set_initiative_settings(db, InitiativeSettings(enabled=True), session_id="user:3")

        rows = db.exec(
            select(Setting).where(
                Setting.key == "initiative.enabled",
                Setting.session_id == "user:3",
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].value_json == "true"

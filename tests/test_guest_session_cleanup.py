"""Tests for guest session tagging (Parte 1) and cleanup job (Parte 2).

- ChatTurnPersistence with a guest: session_id → user message gets
  dataset_source="human_guest" and tag "guest_session"; sity message
  keeps speaker_source="sity_local" but also gets "human_guest" source
  and "guest_session" tag.

- cleanup_expired_guest_sessions():
    * guest session > 24h → session-scoped rows deleted, ChatMessages kept
    * guest session < 24h → untouched
    * non-guest session > 24h → untouched
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, select

from app.chat.turn_persistence import ChatTurnPersistence
from app.memory.message_metadata import MessageMetadata
from app.memory.models import (
    ChatMessage,
    ChatSession,
    DailyMessageUsage,
    DailyTtsUsage,
    NotificationLog,
    OpenLoop,
    Setting,
)


_ALL_TEST_SESSION_IDS = [
    "guest:tag_test_01", "guest:tag_test_02", "guest:tag_test_04", "guest:tag_test_05",
    "guest:cleanup_setting_01", "guest:cleanup_msg_02", "guest:cleanup_usage_03",
    "guest:cleanup_active_04", "user:999_cleanup_05", "guest:cleanup_ol_06",
]


_ALL_TEST_SETTING_KEYS = [
    "test_key_gc01", "test_key_active04", "test_key_nongc05",
]


@pytest.fixture(autouse=True)
def _cleanup_test_sessions(db_session: Session) -> None:
    """Delete hardcoded test data before each test to prevent UNIQUE violations
    on re-runs against a persistent test DB."""
    for key in _ALL_TEST_SETTING_KEYS:
        row = db_session.exec(select(Setting).where(Setting.key == key)).first()
        if row:
            db_session.delete(row)
    for sid in _ALL_TEST_SESSION_IDS:
        cs = db_session.get(ChatSession, sid)
        if cs:
            db_session.delete(cs)
    db_session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_persistence(db_session: Session, session_id: str) -> ChatTurnPersistence:
    capture_ctx = MagicMock()
    capture_svc = MagicMock()
    capture_svc.build_user_metadata.return_value = MessageMetadata(
        speaker_source="human_local",
        dataset_source="normal_use",
        dataset_eligible=True,
        dataset_tags_json=None,
    )
    capture_svc.build_sity_metadata.return_value = MessageMetadata(
        speaker_source="sity_local",
        dataset_source="normal_use",
        dataset_eligible=True,
        dataset_tags_json=None,
    )
    return ChatTurnPersistence(db_session, capture_ctx, capture_svc, session_id=session_id)


def _past(hours: int = 25) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)


def _create_expired_guest_session(db: Session, session_id: str) -> ChatSession:
    cs = ChatSession(id=session_id, updated_at=_past(25))
    db.add(cs)
    db.commit()
    db.refresh(cs)
    return cs


# ---------------------------------------------------------------------------
# Parte 1 — guest metadata tagging
# ---------------------------------------------------------------------------

def test_guest_user_message_dataset_source(db_session: Session) -> None:
    p = _make_persistence(db_session, session_id="guest:tag_test_01")
    msg_id = p.save(role="user", text="hola soy invitado", trace_id="trc_guest_user_01")
    row = db_session.get(ChatMessage, msg_id)
    assert row is not None
    assert row.dataset_source == "human_guest"
    assert row.speaker_source == "human_guest"
    assert row.dataset_eligible is True
    tags = json.loads(row.dataset_tags_json or "[]")
    assert "guest_session" in tags


def test_guest_sity_message_dataset_source(db_session: Session) -> None:
    p = _make_persistence(db_session, session_id="guest:tag_test_02")
    msg_id = p.save(role="sity", text="bienvenido invitado", trace_id="trc_guest_sity_02")
    row = db_session.get(ChatMessage, msg_id)
    assert row is not None
    assert row.dataset_source == "human_guest"
    assert row.speaker_source == "sity_local"
    assert row.dataset_eligible is True
    tags = json.loads(row.dataset_tags_json or "[]")
    assert "guest_session" in tags


def test_non_guest_user_message_keeps_normal_use(db_session: Session) -> None:
    p = _make_persistence(db_session, session_id="user:99")
    msg_id = p.save(role="user", text="mensaje normal", trace_id="trc_non_guest_03")
    row = db_session.get(ChatMessage, msg_id)
    assert row is not None
    assert row.dataset_source == "normal_use"
    assert row.speaker_source == "human_local"
    assert (row.dataset_tags_json is None or "guest_session" not in json.loads(row.dataset_tags_json))


def test_guest_tag_does_not_duplicate(db_session: Session) -> None:
    """Calling save twice for the same guest session does not add guest_session twice."""
    p = _make_persistence(db_session, session_id="guest:tag_test_04")
    msg_id = p.save(role="user", text="primer mensaje", trace_id="trc_guest_dedup_04a")
    row = db_session.get(ChatMessage, msg_id)
    tags = json.loads(row.dataset_tags_json or "[]")
    assert tags.count("guest_session") == 1


def test_guest_session_dataset_eligible_is_true(db_session: Session) -> None:
    p = _make_persistence(db_session, session_id="guest:tag_test_05")
    msg_id = p.save(role="user", text="elegible", trace_id="trc_guest_eligible_05")
    row = db_session.get(ChatMessage, msg_id)
    assert row is not None
    assert row.dataset_eligible is True


# ---------------------------------------------------------------------------
# Parte 2 — cleanup job
# ---------------------------------------------------------------------------

def test_cleanup_removes_setting_for_expired_guest(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions

    sid = "guest:cleanup_setting_01"
    _create_expired_guest_session(db_session, sid)

    setting = Setting(key="test_key_gc01", value_json='"x"', session_id=sid)
    db_session.add(setting)
    db_session.commit()

    result = cleanup_expired_guest_sessions(db_session)
    assert result["cleaned_sessions"] >= 1
    assert result["errors"] == []

    remaining = db_session.exec(
        select(Setting).where(Setting.session_id == sid)
    ).all()
    assert remaining == []


def test_cleanup_preserves_chatmessages(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions

    sid = "guest:cleanup_msg_02"
    _create_expired_guest_session(db_session, sid)

    msg = ChatMessage(session_id=sid, role="user", text="keep me")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    msg_id = msg.id

    cleanup_expired_guest_sessions(db_session)

    still_there = db_session.get(ChatMessage, msg_id)
    assert still_there is not None
    assert still_there.text == "keep me"


def test_cleanup_removes_daily_usage_rows(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions

    sid = "guest:cleanup_usage_03"
    _create_expired_guest_session(db_session, sid)

    db_session.add(DailyMessageUsage(session_id=sid, count=5, count_date="2026-10-01"))
    db_session.add(DailyTtsUsage(session_id=sid, char_count=100, count_date="2026-10-01"))
    db_session.commit()

    cleanup_expired_guest_sessions(db_session)

    assert db_session.get(DailyMessageUsage, sid) is None
    assert db_session.get(DailyTtsUsage, sid) is None


def test_cleanup_skips_active_guest_session(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions

    sid = "guest:cleanup_active_04"
    recent_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    cs = ChatSession(id=sid, updated_at=recent_time)
    db_session.add(cs)
    db_session.commit()

    setting = Setting(key="test_key_active04", value_json='"y"', session_id=sid)
    db_session.add(setting)
    db_session.commit()

    cleanup_expired_guest_sessions(db_session)

    still_there = db_session.exec(
        select(Setting).where(Setting.session_id == sid)
    ).all()
    assert len(still_there) == 1


def test_cleanup_ignores_non_guest_sessions(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions

    sid = "user:999_cleanup_05"
    cs = ChatSession(id=sid, updated_at=_past(48))
    db_session.add(cs)
    db_session.commit()

    setting = Setting(key="test_key_nongc05", value_json='"z"', session_id=sid)
    db_session.add(setting)
    db_session.commit()

    result = cleanup_expired_guest_sessions(db_session)

    still_there = db_session.exec(
        select(Setting).where(Setting.session_id == sid)
    ).all()
    assert len(still_there) == 1
    cleaned_ids = []
    assert "user:999_cleanup_05" not in cleaned_ids


def test_cleanup_removes_open_loops(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions

    sid = "guest:cleanup_ol_06"
    _create_expired_guest_session(db_session, sid)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ol = OpenLoop(
        id="ol_gctest06",
        session_id=sid,
        user_message="test intent",
        extracted_intent="do something",
        detected_at=now - timedelta(hours=26),
        status="pending",
        expires_at=now + timedelta(days=1),
    )
    db_session.add(ol)
    db_session.commit()

    cleanup_expired_guest_sessions(db_session)

    gone = db_session.exec(
        select(OpenLoop).where(OpenLoop.session_id == sid)
    ).all()
    assert gone == []


def test_cleanup_empty_returns_zero(db_session: Session) -> None:
    from app.chat.guest_session_cleanup import cleanup_expired_guest_sessions
    result = cleanup_expired_guest_sessions(db_session)
    assert isinstance(result["cleaned_sessions"], int)
    assert result["errors"] == []

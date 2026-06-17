"""Tests for ChatTurnPersistence."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, select

from app.chat.turn_persistence import ChatTurnPersistence
from app.memory.message_metadata import MessageMetadata
from app.memory.models import ChatMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_persistence(db_session: Session) -> ChatTurnPersistence:
    capture_ctx = MagicMock()
    capture_svc = MagicMock()
    capture_svc.build_user_metadata.return_value = MessageMetadata(
        speaker_id="user_test",
        speaker_label="user",
        speaker_source="test",
        speaker_confidence=1.0,
        identity_evidence_json=None,
        dataset_source="test",
        dataset_eligible=True,
        dataset_tags_json=None,
    )
    capture_svc.build_sity_metadata.return_value = MessageMetadata(
        speaker_id="sity_test",
        speaker_label="sity",
        speaker_source="test",
        speaker_confidence=1.0,
        identity_evidence_json=None,
        dataset_source="test",
        dataset_eligible=True,
        dataset_tags_json=None,
    )
    return ChatTurnPersistence(db_session, capture_ctx, capture_svc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_save_user_role_uses_user_metadata(db_session: Session) -> None:
    persistence = _make_persistence(db_session)
    persistence.save(role="user", text="hola desde test", trace_id="trc_test_usr")

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.trace_id == "trc_test_usr")
    ).first()
    assert row is not None
    assert row.role == "user"
    assert row.text == "hola desde test"
    assert row.speaker_id == "user_test"
    assert row.speaker_label == "user"


def test_save_sity_role_uses_sity_metadata(db_session: Session) -> None:
    persistence = _make_persistence(db_session)
    persistence.save(role="sity", text="respuesta de Sity", trace_id="trc_test_sity")

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.trace_id == "trc_test_sity")
    ).first()
    assert row is not None
    assert row.role == "sity"
    assert row.speaker_id == "sity_test"
    assert row.speaker_label == "sity"


def test_save_passes_optional_fields(db_session: Session) -> None:
    persistence = _make_persistence(db_session)
    persistence.save(
        role="sity",
        text="respuesta con voz",
        trace_id="trc_test_fields",
        tone_meta='{"sarcasm": 0.5}',
        output_mode="voice",
        tts_fragments=2,
        source_channel="telegram",
    )

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.trace_id == "trc_test_fields")
    ).first()
    assert row is not None
    assert row.tone_meta == '{"sarcasm": 0.5}'
    assert row.output_mode == "voice"
    assert row.tts_fragments == 2
    assert row.source_channel == "telegram"


def test_save_explicit_metadata_overrides_default(db_session: Session) -> None:
    persistence = _make_persistence(db_session)
    custom_meta = MessageMetadata(
        speaker_id="custom_speaker",
        speaker_label="custom",
        speaker_source="override",
        speaker_confidence=0.9,
        identity_evidence_json=None,
        dataset_source="custom",
        dataset_eligible=False,
        dataset_tags_json=None,
    )
    persistence.save(role="user", text="override test", trace_id="trc_test_override",
                     metadata=custom_meta)

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.trace_id == "trc_test_override")
    ).first()
    assert row is not None
    assert row.speaker_id == "custom_speaker"
    assert row.dataset_eligible is False


def test_save_callable_works_without_session_arg(db_session: Session) -> None:
    """persistence.save is used as a Callable[..., None] — no session arg required."""
    persistence = _make_persistence(db_session)
    save_fn = persistence.save
    # Called as keyword-only (no session positional arg)
    save_fn(role="user", text="callable test", trace_id="trc_callable")

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.trace_id == "trc_callable")
    ).first()
    assert row is not None
    assert row.text == "callable test"

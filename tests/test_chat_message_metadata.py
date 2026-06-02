"""Tests for ChatMessage metadata fields and MessageMetadata helpers.

Verifies:
- ChatMessage accepts the new provenance/dataset fields.
- build_message_metadata() returns sensible defaults per role.
- save_chat_message() backward-compat: callers that pass no metadata still work.
- save_chat_message() forwards explicit metadata to the DB row.
- Sity role messages still carry tone_meta (pre-existing field).
- created_at is set on every message.
- dataset_eligible defaults to True.
"""
from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select

from app.memory.message_metadata import MessageMetadata, build_message_metadata
from app.memory.models import ChatMessage


# ---------------------------------------------------------------------------
# MessageMetadata dataclass — pure unit tests, no DB
# ---------------------------------------------------------------------------

def test_build_metadata_user_defaults_to_human_local() -> None:
    meta = build_message_metadata(role="user")
    assert meta.speaker_source == "human_local"


def test_build_metadata_sity_defaults_to_sity_local() -> None:
    meta = build_message_metadata(role="sity")
    assert meta.speaker_source == "sity_local"


def test_build_metadata_default_dataset_source_is_normal_use() -> None:
    meta = build_message_metadata()
    assert meta.dataset_source == "normal_use"


def test_build_metadata_dataset_eligible_default_is_true() -> None:
    meta = build_message_metadata()
    assert meta.dataset_eligible is True


def test_build_metadata_explicit_speaker_source_overrides_role() -> None:
    meta = build_message_metadata(role="user", speaker_source="synthetic_claude_user")
    assert meta.speaker_source == "synthetic_claude_user"


def test_build_metadata_synthetic_claude_user() -> None:
    tags = json.dumps(["multi_persona", "v1"])
    meta = build_message_metadata(
        role="user",
        speaker_source="synthetic_claude_user",
        dataset_source="synthetic_claude_user",
        dataset_eligible=True,
        dataset_tags_json=tags,
    )
    assert meta.speaker_source == "synthetic_claude_user"
    assert meta.dataset_source == "synthetic_claude_user"
    assert meta.dataset_tags_json == tags


def test_message_metadata_is_frozen() -> None:
    meta = build_message_metadata()
    with pytest.raises((AttributeError, TypeError)):
        meta.speaker_source = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ChatMessage model fields — create directly, persist via db_session
# ---------------------------------------------------------------------------

def test_chatmessage_has_new_metadata_fields(db_session: Session) -> None:
    msg = ChatMessage(
        session_id="default",
        role="user",
        text="hola",
        speaker_source="human_local",
        dataset_source="normal_use",
        dataset_eligible=True,
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.speaker_source == "human_local"
    assert msg.dataset_source == "normal_use"
    assert msg.dataset_eligible is True
    assert msg.speaker_id is None
    assert msg.speaker_label is None
    assert msg.speaker_confidence is None
    assert msg.identity_evidence_json is None
    assert msg.dataset_tags_json is None


def test_chatmessage_synthetic_metadata(db_session: Session) -> None:
    tags = json.dumps(["casual_taco"])
    msg = ChatMessage(
        session_id="default",
        role="user",
        text="qué tal el día?",
        speaker_source="synthetic_claude_user",
        dataset_source="synthetic_claude_user",
        dataset_eligible=True,
        dataset_tags_json=tags,
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.speaker_source == "synthetic_claude_user"
    assert msg.dataset_source == "synthetic_claude_user"
    assert msg.dataset_tags_json == tags


def test_chatmessage_created_at_is_set(db_session: Session) -> None:
    msg = ChatMessage(session_id="default", role="user", text="test")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    assert msg.created_at is not None


def test_chatmessage_tone_meta_preserved(db_session: Session) -> None:
    snap = json.dumps({"sarcasm": 0.5, "warmth": 0.4})
    msg = ChatMessage(
        session_id="default",
        role="sity",
        text="Aquí estoy.",
        tone_meta=snap,
        speaker_source="sity_local",
        dataset_source="normal_use",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.tone_meta == snap


def test_chatmessage_nullable_metadata_fields_default_to_none(db_session: Session) -> None:
    """Creating ChatMessage without any metadata fields leaves them NULL."""
    msg = ChatMessage(session_id="default", role="user", text="sin metadata")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.speaker_id is None
    assert msg.speaker_source is None
    assert msg.dataset_source is None
    assert msg.dataset_tags_json is None


# ---------------------------------------------------------------------------
# save_chat_message — integration via routes_chat
# ---------------------------------------------------------------------------

def test_save_chat_message_backward_compat_no_metadata(db_session: Session) -> None:
    """Calling save_chat_message without metadata must not raise."""
    from app.api.routes_chat import save_chat_message

    save_chat_message(db_session, role="user", text="compat check")

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.text == "compat check")
    ).first()
    assert row is not None
    assert row.speaker_source == "human_local"
    assert row.dataset_source == "normal_use"
    assert row.dataset_eligible is True


def test_save_chat_message_with_explicit_metadata(db_session: Session) -> None:
    from app.api.routes_chat import save_chat_message

    meta = MessageMetadata(
        speaker_source="synthetic_claude_user",
        dataset_source="synthetic_claude_user",
        dataset_eligible=True,
        dataset_tags_json=json.dumps(["gender_feminine"]),
    )
    save_chat_message(db_session, role="user", text="metadata test", metadata=meta)

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.text == "metadata test")
    ).first()
    assert row is not None
    assert row.speaker_source == "synthetic_claude_user"
    assert row.dataset_source == "synthetic_claude_user"
    assert row.dataset_tags_json == json.dumps(["gender_feminine"])


def test_save_chat_message_sity_role_defaults(db_session: Session) -> None:
    """Sity role without explicit metadata gets sity_local speaker_source."""
    from app.api.routes_chat import save_chat_message

    tone = json.dumps({"sarcasm": 0.6})
    save_chat_message(db_session, role="sity", text="respuesta Sity", tone_meta=tone)

    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.text == "respuesta Sity")
    ).first()
    assert row is not None
    assert row.tone_meta == tone
    assert row.speaker_source == "sity_local"
    assert row.dataset_eligible is True

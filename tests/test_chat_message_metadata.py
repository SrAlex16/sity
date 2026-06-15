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


# ---------------------------------------------------------------------------
# output_mode and tts_fragments fields
# ---------------------------------------------------------------------------

def test_chatmessage_output_mode_defaults_to_text(db_session: Session) -> None:
    msg = ChatMessage(session_id="default", role="sity", text="hola")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    assert msg.output_mode == "text"
    assert msg.tts_fragments is None


def test_chatmessage_output_mode_voice_persists(db_session: Session) -> None:
    msg = ChatMessage(session_id="default", role="sity", text="audio", output_mode="voice", tts_fragments=1)
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    assert msg.output_mode == "voice"
    assert msg.tts_fragments == 1


def test_chatmessage_tts_fragments_multiple(db_session: Session) -> None:
    msg = ChatMessage(session_id="default", role="sity", text="largo", output_mode="voice", tts_fragments=3)
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    assert msg.tts_fragments == 3


def test_save_chat_message_output_mode_voice(db_session: Session) -> None:
    from app.api.routes_chat import save_chat_message

    save_chat_message(
        db_session, role="sity", text="voz test",
        output_mode="voice", tts_fragments=2,
    )
    row = db_session.exec(select(ChatMessage).where(ChatMessage.text == "voz test")).first()
    assert row is not None
    assert row.output_mode == "voice"
    assert row.tts_fragments == 2


def test_save_chat_message_output_mode_defaults(db_session: Session) -> None:
    """output_mode defaults to 'text', tts_fragments to None when not specified."""
    from app.api.routes_chat import save_chat_message

    save_chat_message(db_session, role="sity", text="default mode test")
    row = db_session.exec(select(ChatMessage).where(ChatMessage.text == "default mode test")).first()
    assert row is not None
    assert row.output_mode == "text"
    assert row.tts_fragments is None


def test_save_chat_message_text_only_no_tts(db_session: Session) -> None:
    """When voice_long_response_action=text_only and response is long, tts_fragments is None."""
    from app.api.routes_chat import save_chat_message

    save_chat_message(
        db_session, role="sity", text="respuesta larga text_only",
        output_mode="voice", tts_fragments=None,
    )
    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.text == "respuesta larga text_only")
    ).first()
    assert row is not None
    assert row.output_mode == "voice"
    assert row.tts_fragments is None


# ---------------------------------------------------------------------------
# _attach_tts_artifacts return value
# ---------------------------------------------------------------------------

def test_attach_tts_returns_none_when_text_only_long() -> None:
    """text_only + long text → None (no TTS)."""
    from unittest.mock import MagicMock, patch
    from app.api.routes_chat import _attach_tts_artifacts
    from app.settings.schemas import VoiceSettings

    result = MagicMock()
    result.artifacts = []
    vs = VoiceSettings(voice_response_mode="always", voice_include_text=True,
                       voice_long_response_action="text_only")

    with patch("app.api.routes_chat._attach_tts_artifacts.__wrapped__", None, create=True):
        with patch("app.audio.synthesizer.load_tts_config") as mock_cfg:
            from app.audio.synthesizer import TtsConfig
            mock_cfg.return_value = TtsConfig(
                piper_bin="piper", model_path="/x.onnx", speaker_id=1, long_response_chars=10
            )
            n = _attach_tts_artifacts(result=result, text="a" * 11, voice_settings=vs, trace_id="t")

    assert n is None
    assert result.artifacts == []


def test_attach_tts_returns_fragment_count() -> None:
    """Single fragment → returns 1."""
    from unittest.mock import MagicMock, patch
    from app.api.routes_chat import _attach_tts_artifacts
    from app.settings.schemas import VoiceSettings
    from app.audio.synthesizer import TtsConfig

    result = MagicMock()
    result.artifacts = []
    vs = VoiceSettings(voice_response_mode="always", voice_include_text=True,
                       voice_long_response_action="text_only")

    fake_cfg = TtsConfig(piper_bin="p", model_path="/m.onnx", speaker_id=None, long_response_chars=500)
    with patch("app.api.routes_chat.load_tts_config" if False else "app.audio.synthesizer.load_tts_config",
               return_value=fake_cfg):
        with patch("app.api.routes_audio.load_tts_config", return_value=fake_cfg):
            with patch("app.api.routes_audio.synthesize_text", return_value=b"RIFF"):
                with patch("app.api.routes_audio._TTS_TMP_DIR") as mock_dir:
                    mock_path = MagicMock()
                    mock_dir.__truediv__ = lambda s, n: mock_path
                    mock_dir.mkdir = MagicMock()
                    with patch("app.audio.synthesizer.load_tts_config", return_value=fake_cfg):
                        n = _attach_tts_artifacts(
                            result=result, text="hola", voice_settings=vs, trace_id="t"
                        )

    assert n == 1


def test_attach_tts_returns_none_on_exception() -> None:
    """If synthesize_to_tmp raises, returns None."""
    from unittest.mock import MagicMock, patch
    from app.api.routes_chat import _attach_tts_artifacts
    from app.settings.schemas import VoiceSettings
    from app.audio.synthesizer import TtsConfig

    result = MagicMock()
    result.artifacts = []
    vs = VoiceSettings(voice_response_mode="always", voice_include_text=True,
                       voice_long_response_action="text_only")

    fake_cfg = TtsConfig(piper_bin="p", model_path="/m.onnx", speaker_id=None, long_response_chars=500)
    with patch("app.audio.synthesizer.load_tts_config", return_value=fake_cfg):
        with patch("app.api.routes_audio.synthesize_to_tmp", side_effect=RuntimeError("boom")):
            n = _attach_tts_artifacts(result=result, text="hola", voice_settings=vs, trace_id="t")

    assert n is None


# ---------------------------------------------------------------------------
# source_channel field
# ---------------------------------------------------------------------------

def test_chatmessage_source_channel_defaults_to_web(db_session: Session) -> None:
    msg = ChatMessage(session_id="default", role="user", text="hola")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    assert msg.source_channel == "web"


def test_chatmessage_source_channel_telegram(db_session: Session) -> None:
    msg = ChatMessage(session_id="default", role="user", text="desde telegram",
                      source_channel="telegram")
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    assert msg.source_channel == "telegram"


def test_save_chat_message_source_channel_web(db_session: Session) -> None:
    from app.api.routes_chat import save_chat_message

    save_chat_message(db_session, role="user", text="web test")
    row = db_session.exec(select(ChatMessage).where(ChatMessage.text == "web test")).first()
    assert row is not None
    assert row.source_channel == "web"


def test_save_chat_message_source_channel_telegram(db_session: Session) -> None:
    from app.api.routes_chat import save_chat_message

    save_chat_message(db_session, role="user", text="telegram test", source_channel="telegram")
    row = db_session.exec(select(ChatMessage).where(ChatMessage.text == "telegram test")).first()
    assert row is not None
    assert row.source_channel == "telegram"


def test_save_chat_message_sity_inherits_source_channel(db_session: Session) -> None:
    """Sity message persisted with source_channel matches the turn channel."""
    from app.api.routes_chat import save_chat_message

    save_chat_message(db_session, role="sity", text="respuesta telegram",
                      source_channel="telegram")
    row = db_session.exec(
        select(ChatMessage).where(ChatMessage.text == "respuesta telegram")
    ).first()
    assert row is not None
    assert row.source_channel == "telegram"


def test_gateway_send_message_includes_telegram_channel() -> None:
    """SityGateway.send_message must include source_channel='telegram' in the body."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.messaging.gateway import SityGateway

    captured_body: dict = {}

    async def fake_post(url, *, json, **kwargs):
        captured_body.update(json)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"ok": True, "text": "ok", "artifacts": []})
        return mock_resp

    gw = SityGateway()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=fake_post)
        mock_client_cls.return_value = mock_client
        asyncio.run(gw.send_message("hola"))

    assert captured_body.get("source_channel") == "telegram"

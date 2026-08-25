"""Tests for TTS in pending_action_runner — regression for the 'confirm action = no audio' bug.

1. test_run_with_voice_always_includes_audio     — voice_response_mode='always' → audio in response
2. test_run_with_voice_never_has_no_audio        — voice_response_mode='never' → no audio
3. test_run_updates_chatmessage_tts_fields       — tts_fragments/audio_filename saved to DB row
4. test_run_tts_error_does_not_block_response   — TTS failure → text response still delivered
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import ChatMessage, utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cm(session_id: str = "user:9901"):
    from app.actions.confirmation_manager import ConfirmationManager
    cm = MagicMock(spec=ConfirmationManager)
    cm._session_id = session_id
    cm.session = MagicMock()  # not used for TTS lookup
    return cm


def _make_ctx(session, trace_id: str = "trc_par_tts_test"):
    from app.chat.local_flow import LocalFlowContext

    saved: list = []

    def _save(*, role, text, trace_id=None):
        with Session(engine) as db:
            db.add(ChatMessage(session_id="user:9901", role=role, text=text, trace_id=trace_id))
            db.commit()

    return LocalFlowContext(
        session=session,
        trace_id=trace_id,
        message="confirmo",
        daily_budget=100_000,
        warnings=[],
        save_message=_save,
        get_usage=lambda s: 0,
    )


def _google_action_payload() -> str:
    return json.dumps({
        "action": "calendar_create_event",
        "title": "Dentista",
        "start_iso": "2026-08-31T10:00:00",
        "end_iso": "2026-08-31T11:00:00",
        "description": "",
    })


def _make_action():
    action = MagicMock()
    action.id = "act_tts_test_001"
    action.action_type = "google"
    action.payload_json = _google_action_payload()
    action.summary = "Crear evento"
    return action


def _add_voice_setting(db: Session, session_id: str, key: str, value: str) -> None:
    import json as _json
    from app.memory.models import Setting
    full_key = f"voice.{key}"
    existing = db.exec(
        select(Setting).where(Setting.key == full_key, Setting.session_id == session_id)
    ).first()
    if existing:
        existing.value_json = _json.dumps(value)
        db.add(existing)
    else:
        db.add(Setting(session_id=session_id, key=full_key, value_json=_json.dumps(value)))
    db.commit()


# ---------------------------------------------------------------------------
# 1 & 2. Voice always → audio present; voice never → no audio
# ---------------------------------------------------------------------------

class TestPendingActionRunnerTTS:
    def _run_with_voice_mode(self, mode: str):
        from app.chat.pending_action_runner import PendingActionRunner

        with Session(engine) as db:
            _add_voice_setting(db, "user:9901", "voice_response_mode", mode)

        fake_creds = MagicMock()
        fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}

        with Session(engine) as session:
            ctx = _make_ctx(session, trace_id="trc_par_tts_voice_test")
            cm = _make_cm("user:9901")
            runner = PendingActionRunner(cm)
            action = _make_action()

            with (
                patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
                patch("googleapiclient.discovery.build") as mock_build,
                patch("app.audio.tts_dispatcher.synthesize_fragment",
                      return_value=("/audio/tmp/out.wav", "out.wav")),
            ):
                mock_service = MagicMock()
                mock_build.return_value = mock_service
                mock_service.events().insert().execute.return_value = fake_event
                cm.mark_executed = MagicMock()

                response = runner.run(action, ctx)

        return response

    def test_run_with_voice_always_includes_audio(self):
        response = self._run_with_voice_mode("always")
        audio_artifacts = [a for a in response.artifacts if a.type == "audio"]
        assert len(audio_artifacts) >= 1, "Expected audio artifact when voice_response_mode='always'"

    def test_run_with_voice_never_has_no_audio(self):
        response = self._run_with_voice_mode("never")
        audio_artifacts = [a for a in response.artifacts if a.type == "audio"]
        assert len(audio_artifacts) == 0, "Expected no audio artifact when voice_response_mode='never'"


# ---------------------------------------------------------------------------
# 3. DB fields tts_fragments / audio_filename updated on the ChatMessage row
# ---------------------------------------------------------------------------

def test_run_updates_chatmessage_tts_fields():
    from app.chat.pending_action_runner import PendingActionRunner

    with Session(engine) as db:
        _add_voice_setting(db, "user:9901", "voice_response_mode", "always")

    fake_creds = MagicMock()
    fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}
    trace_id = "trc_par_tts_db_test"

    with Session(engine) as session:
        ctx = _make_ctx(session, trace_id=trace_id)
        cm = _make_cm("user:9901")
        runner = PendingActionRunner(cm)
        action = _make_action()

        with (
            patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
            patch("app.audio.tts_dispatcher.synthesize_fragment",
                  return_value=("/audio/tmp/out.wav", "persisted_file.wav")),
            patch("app.settings.config_loader.load_default_config",
                  return_value={"audio": {"persist_tts": True, "elevenlabs_daily_char_limit": 0,
                                          "elevenlabs_voice_id": "x"}}),
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event
            cm.mark_executed = MagicMock()
            runner.run(action, ctx)

    with Session(engine) as db:
        msg = db.exec(
            select(ChatMessage).where(
                ChatMessage.trace_id == trace_id,
                ChatMessage.role == "sity",
            )
        ).first()
        assert msg is not None
        assert msg.tts_fragments is not None and msg.tts_fragments >= 1
        assert msg.audio_filename == "persisted_file.wav"


# ---------------------------------------------------------------------------
# 4. TTS failure never blocks the response
# ---------------------------------------------------------------------------

def test_run_tts_error_does_not_block_response():
    from app.chat.pending_action_runner import PendingActionRunner

    with Session(engine) as db:
        _add_voice_setting(db, "user:9901", "voice_response_mode", "always")

    fake_creds = MagicMock()
    fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}

    with Session(engine) as session:
        ctx = _make_ctx(session, trace_id="trc_par_tts_err_test")
        cm = _make_cm("user:9901")
        runner = PendingActionRunner(cm)
        action = _make_action()

        with (
            patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
            patch("app.audio.tts_dispatcher.synthesize_fragment",
                  side_effect=RuntimeError("piper crash")),
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event
            cm.mark_executed = MagicMock()
            response = runner.run(action, ctx)

    assert response.ok is True
    assert "Dentista" in response.text

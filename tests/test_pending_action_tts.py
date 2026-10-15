"""Tests for pending_action_runner — confirmed actions must NOT generate TTS.

Confirmed shell/git/google/etc actions return program output (stdout/stderr).
TTS is intentionally disabled for this path; audio is only generated during
conversational AI responses.
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
    cm.session = MagicMock()
    return cm


def _make_ctx(session, trace_id: str = "trc_par_tts_test"):
    from app.chat.local_flow import LocalFlowContext

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
# 1 & 2. Confirmed actions never produce audio regardless of voice_response_mode
# ---------------------------------------------------------------------------

class TestPendingActionRunnerNoTTS:
    def _run_with_voice_mode(self, mode: str):
        from app.chat.pending_action_runner import PendingActionRunner

        with Session(engine) as db:
            _add_voice_setting(db, "user:9901", "voice_response_mode", mode)

        fake_creds = MagicMock()
        fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}

        with Session(engine) as session:
            ctx = _make_ctx(session, trace_id=f"trc_par_notts_{mode}")
            cm = _make_cm("user:9901")
            runner = PendingActionRunner(cm)
            action = _make_action()

            with (
                patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
                patch("googleapiclient.discovery.build") as mock_build,
            ):
                mock_service = MagicMock()
                mock_build.return_value = mock_service
                mock_service.events().insert().execute.return_value = fake_event
                cm.mark_executed = MagicMock()

                response = runner.run(action, ctx)

        return response

    def test_run_with_voice_always_has_no_audio(self):
        """Confirmed actions skip TTS even when voice_response_mode='always'."""
        response = self._run_with_voice_mode("always")
        audio_artifacts = [a for a in response.artifacts if a.type == "audio"]
        assert len(audio_artifacts) == 0, "Confirmed actions must not generate TTS audio"

    def test_run_with_voice_never_has_no_audio(self):
        response = self._run_with_voice_mode("never")
        audio_artifacts = [a for a in response.artifacts if a.type == "audio"]
        assert len(audio_artifacts) == 0


# ---------------------------------------------------------------------------
# 3. No DB tts fields written for confirmed actions
# ---------------------------------------------------------------------------

def test_run_does_not_write_tts_db_fields():
    from app.chat.pending_action_runner import PendingActionRunner

    with Session(engine) as db:
        _add_voice_setting(db, "user:9901", "voice_response_mode", "always")

    fake_creds = MagicMock()
    fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}
    trace_id = "trc_par_notts_db_test"

    with Session(engine) as session:
        ctx = _make_ctx(session, trace_id=trace_id)
        cm = _make_cm("user:9901")
        runner = PendingActionRunner(cm)
        action = _make_action()

        with (
            patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
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
        assert not msg.tts_fragments
        assert not msg.audio_filename


# ---------------------------------------------------------------------------
# 4. Response always delivered regardless of any TTS state
# ---------------------------------------------------------------------------

def test_run_response_always_delivered():
    from app.chat.pending_action_runner import PendingActionRunner

    with Session(engine) as session:
        ctx = _make_ctx(session, trace_id="trc_par_notts_ok_test")
        cm = _make_cm("user:9901")
        runner = PendingActionRunner(cm)
        action = _make_action()

        fake_creds = MagicMock()
        fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}

        with (
            patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event
            cm.mark_executed = MagicMock()
            response = runner.run(action, ctx)

    assert response.ok is True
    assert "Dentista" in response.text

"""Tests for google_actions.py — per-user credential resolution in pending actions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.actions.google_actions import (
    GoogleActionResult,
    _NOT_CONNECTED_MSG,
    execute_google_action,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_creds():
    creds = MagicMock()
    creds.valid = True
    return creds


def _create_payload(
    action: str = "calendar_create_event",
    title: str = "Test",
    start_iso: str = "2026-08-31T10:00:00",
    end_iso: str = "2026-08-31T11:00:00",
) -> dict:
    return {
        "action": action,
        "title": title,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "description": "",
    }


# ---------------------------------------------------------------------------
# 1. No credentials anywhere → coherent error message
# ---------------------------------------------------------------------------

class TestNoCredentials:
    def test_create_returns_not_connected_message(self):
        with (
            patch("app.actions.google_actions._resolve_creds", return_value=None),
        ):
            result = execute_google_action(_create_payload(), user_id=None, session=None)

        assert result.ok is False
        assert "Conéctalo en Ajustes" in result.text
        assert "scripts/google_auth_setup.py" not in result.text  # old message gone

    def test_edit_returns_not_connected_message(self):
        with patch("app.actions.google_actions._resolve_creds", return_value=None):
            result = execute_google_action(
                {"action": "calendar_edit_event", "event_id": "abc"},
                user_id=None, session=None,
            )
        assert result.ok is False
        assert "Conéctalo en Ajustes" in result.text

    def test_delete_returns_not_connected_message(self):
        with patch("app.actions.google_actions._resolve_creds", return_value=None):
            result = execute_google_action(
                {"action": "calendar_delete_event", "event_id": "abc"},
                user_id=None, session=None,
            )
        assert result.ok is False
        assert "Conéctalo en Ajustes" in result.text


# ---------------------------------------------------------------------------
# 2. Per-user credentials available → used, Google API called, ok=True
# ---------------------------------------------------------------------------

class TestPerUserCredentials:
    def test_create_uses_per_user_creds_when_available(self):
        fake_creds = _make_fake_creds()
        fake_session = MagicMock()
        fake_event = {"htmlLink": "https://calendar.google.com/event/abc"}

        # Patch at source module since _resolve_creds imports lazily
        with (
            patch("app.integrations.google_auth.load_user_credentials", return_value=fake_creds),
            patch("app.integrations.google_auth.load_credentials") as mock_global,
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event

            result = execute_google_action(
                _create_payload(), user_id=1, session=fake_session
            )

        assert result.ok is True
        assert "Test" in result.text
        mock_global.assert_not_called()

    def test_create_falls_back_to_global_when_user_creds_none(self):
        fake_creds = _make_fake_creds()
        fake_session = MagicMock()
        fake_event = {"htmlLink": "https://calendar.google.com/event/xyz"}

        with (
            patch("app.integrations.google_auth.load_user_credentials", return_value=None),
            patch("app.integrations.google_auth.load_credentials", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event

            result = execute_google_action(
                _create_payload(), user_id=1, session=fake_session
            )

        assert result.ok is True

    def test_create_no_user_id_uses_global_directly(self):
        fake_creds = _make_fake_creds()
        fake_event = {"htmlLink": "https://calendar.google.com/event/xyz"}

        with (
            patch("app.integrations.google_auth.load_credentials", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event

            result = execute_google_action(_create_payload(), user_id=None, session=None)

        assert result.ok is True


# ---------------------------------------------------------------------------
# 3. Unknown action type
# ---------------------------------------------------------------------------

def test_unknown_action_returns_error():
    result = execute_google_action({"action": "calendar_fly_to_mars"})
    assert result.ok is False
    assert "desconocida" in result.text


# ---------------------------------------------------------------------------
# 4. PendingActionRunner._run_google extracts user_id from session_id
# ---------------------------------------------------------------------------

class TestPendingActionRunnerGoogleUserExtraction:
    def _make_runner(self, session_id: str):
        from app.actions.confirmation_manager import ConfirmationManager
        from app.chat.pending_action_runner import PendingActionRunner

        mock_session = MagicMock()
        cm = MagicMock(spec=ConfirmationManager)
        cm._session_id = session_id
        cm.session = mock_session
        return PendingActionRunner(cm)

    def _make_action(self) -> MagicMock:
        from app.memory.models import PendingAction, utc_now
        from datetime import timedelta
        import json

        action = MagicMock()
        action.id = "act_test_001"
        action.action_type = "google"
        action.payload_json = json.dumps({
            "action": "calendar_create_event",
            "title": "Dentista",
            "start_iso": "2026-08-31T10:00:00",
            "end_iso": "2026-08-31T11:00:00",
            "description": "",
        })
        action.summary = "Crear evento"
        return action

    def test_user_session_extracts_user_id(self):
        runner = self._make_runner("user:42")
        action = self._make_action()
        fake_creds = _make_fake_creds()
        fake_event = {"htmlLink": "https://calendar.google.com/event/ok"}

        with (
            patch("app.actions.google_actions._resolve_creds", return_value=fake_creds),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events().insert().execute.return_value = fake_event

            result = runner._run_google(action, "trc_test")

        assert "Dentista" in result.text
        runner.cm.mark_executed.assert_called_once()

    def test_guest_session_passes_none_user_id(self):
        runner = self._make_runner("guest:abc")
        action = self._make_action()

        with patch("app.actions.google_actions._resolve_creds", return_value=None):
            result = runner._run_google(action, "trc_test")

        assert "Conéctalo en Ajustes" in result.text
        runner.cm.mark_failed.assert_called_once()

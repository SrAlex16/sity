"""R11-01 — guest language override via ChatMessageRequest.

Tests:
1. ChatMessageRequest accepts language_override field (None by default).
2. build_turn_context uses request.language_override when DB returns 'auto' (guest).
3. build_turn_context does NOT use request hint when DB has an explicit value.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.schemas import ChatHistoryItem, ChatMessageRequest
from app.chat.turn_context import build_turn_context


# ---------------------------------------------------------------------------
# Schema field
# ---------------------------------------------------------------------------

class TestChatMessageRequestLanguageField:

    def test_language_override_defaults_to_none(self) -> None:
        req = ChatMessageRequest(message="hola")
        assert req.language_override is None

    def test_language_override_accepted(self) -> None:
        req = ChatMessageRequest(message="hola", language_override="en-US")
        assert req.language_override == "en-US"

    def test_language_override_auto_accepted(self) -> None:
        req = ChatMessageRequest(message="hola", language_override="auto")
        assert req.language_override == "auto"


# ---------------------------------------------------------------------------
# build_turn_context: request hint used for guests (DB returns 'auto')
# ---------------------------------------------------------------------------

def _make_request(lang: str | None = None) -> ChatMessageRequest:
    return ChatMessageRequest(message="test message", language_override=lang)


def _mock_settings_service(language_override_value: str = "auto"):
    """Return a MagicMock that simulates SettingsService for a guest session."""
    svc = MagicMock()
    svc.get_personality.return_value = {}
    svc.get_comm_prefs.return_value = {}
    svc.get_voice_settings.return_value = MagicMock(
        voice_response_mode="never",
        voice_include_text=True,
        voice_long_response_action="full",
        audio_cleanup_days=7,
        tts_engine="piper",
        elevenlabs_chars_used=0,
        elevenlabs_daily_limit=10000,
        model_upgrade_ttl_hours=4,
    )
    svc.get_language_override.return_value = language_override_value
    svc.get.return_value = MagicMock(enabled=False)
    return svc


def _mock_capture_service():
    svc = MagicMock()
    ctx = MagicMock()
    svc.get.return_value = ctx
    return svc, ctx


@patch("app.chat.turn_context.DatasetCaptureService")
@patch("app.chat.turn_context.SettingsService")
@patch("app.chat.turn_context.load_default_config")
def test_guest_request_hint_used_when_db_auto(
    mock_config, MockSettings, MockCapture
) -> None:
    mock_config.return_value = {"ai": {}, "usage": {}}
    svc = _mock_settings_service(language_override_value="auto")
    MockSettings.return_value = svc
    cap_svc, cap_ctx = _mock_capture_service()
    MockCapture.return_value = cap_svc

    req = _make_request(lang="en-US")
    session = MagicMock()

    ctx = build_turn_context(session, req, None, session_id="guest:abc")

    assert ctx.language_override == "en-US"


@patch("app.chat.turn_context.DatasetCaptureService")
@patch("app.chat.turn_context.SettingsService")
@patch("app.chat.turn_context.load_default_config")
def test_guest_no_hint_stays_auto(
    mock_config, MockSettings, MockCapture
) -> None:
    mock_config.return_value = {"ai": {}, "usage": {}}
    svc = _mock_settings_service(language_override_value="auto")
    MockSettings.return_value = svc
    cap_svc, cap_ctx = _mock_capture_service()
    MockCapture.return_value = cap_svc

    req = _make_request(lang=None)
    session = MagicMock()

    ctx = build_turn_context(session, req, None, session_id="guest:abc")

    assert ctx.language_override == "auto"


@patch("app.chat.turn_context.DatasetCaptureService")
@patch("app.chat.turn_context.SettingsService")
@patch("app.chat.turn_context.load_default_config")
def test_db_explicit_value_not_overridden_by_request(
    mock_config, MockSettings, MockCapture
) -> None:
    """When the user has saved 'es-ES' in DB, request hint must not override it."""
    mock_config.return_value = {"ai": {}, "usage": {}}
    svc = _mock_settings_service(language_override_value="es-ES")
    MockSettings.return_value = svc
    cap_svc, cap_ctx = _mock_capture_service()
    MockCapture.return_value = cap_svc

    req = _make_request(lang="en-US")  # hint says English
    session = MagicMock()

    ctx = build_turn_context(session, req, None, session_id="user:42")

    assert ctx.language_override == "es-ES"

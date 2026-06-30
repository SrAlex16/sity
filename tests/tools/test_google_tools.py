"""Tests para las tools de Google (Gmail, Calendar, Drive).

Todos los tests usan mocks — sin llamadas reales a la API de Google.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tools.registry import ToolContext


def _make_ctx(tool_name: str, tool_input: dict) -> ToolContext:
    executor = MagicMock()
    executor.session = MagicMock()
    return ToolContext(
        tool_name=tool_name,
        tool_input=tool_input,
        trace_id="test-google",
        executor=executor,
    )


# ── not-connected guard ────────────────────────────────────────────────────────

def test_gmail_search_not_connected_returns_clear_message() -> None:
    from app.tools.handlers.google_tools import handle_gmail_search
    ctx = _make_ctx("gmail_search", {"query": "facturas"})
    with patch("app.tools.handlers.google_tools.is_google_connected", return_value=False):
        result = handle_gmail_search(ctx)
    assert result.ok is False
    assert "google_auth_setup" in result.message.lower() or "conectado" in result.message.lower()


def test_calendar_list_events_not_connected_returns_clear_message() -> None:
    from app.tools.handlers.google_tools import handle_calendar_list_events
    ctx = _make_ctx("calendar_list_events", {})
    with patch("app.tools.handlers.google_tools.is_google_connected", return_value=False):
        result = handle_calendar_list_events(ctx)
    assert result.ok is False
    assert "conectado" in result.message.lower()


def test_drive_search_not_connected_returns_clear_message() -> None:
    from app.tools.handlers.google_tools import handle_drive_search
    ctx = _make_ctx("drive_search", {"query": "presupuesto"})
    with patch("app.tools.handlers.google_tools.is_google_connected", return_value=False):
        result = handle_drive_search(ctx)
    assert result.ok is False
    assert "conectado" in result.message.lower()


def test_calendar_create_event_not_connected_returns_clear_message() -> None:
    from app.tools.handlers.google_tools import handle_calendar_create_event
    ctx = _make_ctx("calendar_create_event", {
        "title": "Cita médica",
        "start_iso": "2026-07-01T10:00:00+02:00",
        "end_iso": "2026-07-01T11:00:00+02:00",
    })
    with patch("app.tools.handlers.google_tools.is_google_connected", return_value=False):
        result = handle_calendar_create_event(ctx)
    assert result.ok is False
    assert "conectado" in result.message.lower()


# ── calendar_create_event validation ──────────────────────────────────────────

def test_calendar_create_event_requires_title_start_end() -> None:
    from app.tools.handlers.google_tools import handle_calendar_create_event
    ctx = _make_ctx("calendar_create_event", {"title": "Reunión"})  # missing start/end
    with patch("app.tools.handlers.google_tools.is_google_connected", return_value=True):
        result = handle_calendar_create_event(ctx)
    assert result.ok is False
    assert "obligatorios" in result.message


# ── calendar_create_event creates pending action, not direct execution ─────────

def test_calendar_create_event_creates_pending_action() -> None:
    from app.tools.handlers.google_tools import handle_calendar_create_event

    mock_created = MagicMock()
    mock_created.id = "act_abcd1234"
    mock_created.confirmation_phrase = "confirmo ejecutar act_abcd1234"
    mock_created.summary = "Crear evento en calendario: Reunión (2026-07-01T10:00:00+02:00)"

    ctx = _make_ctx("calendar_create_event", {
        "title": "Reunión",
        "start_iso": "2026-07-01T10:00:00+02:00",
        "end_iso": "2026-07-01T11:00:00+02:00",
    })

    with patch("app.tools.handlers.google_tools.is_google_connected", return_value=True):
        with patch("app.tools.handlers.google_tools.ConfirmationManager") as mock_cm_cls:
            mock_cm = mock_cm_cls.return_value
            mock_cm.find_equivalent_pending_action.return_value = None
            mock_cm.create_pending_action.return_value = mock_created

            result = handle_calendar_create_event(ctx)

    assert result.ok is True
    assert "act_abcd1234" in result.message
    assert "confirmo ejecutar" in result.message
    # Must NOT call Google API — only create pending action
    mock_cm.create_pending_action.assert_called_once()

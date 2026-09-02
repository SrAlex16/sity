"""Tests for ChatLocalFlow._handle_referenced_action_id and
_handle_pending_confirmation — the branches not covered by test_local_flow.py.

All tests use a mocked ConfirmationManager so no DB is needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.schemas import ChatMessageResponse
from app.chat.local_flow import ChatLocalFlow, LocalFlowContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cm() -> MagicMock:
    return MagicMock()


def _flow(cm: MagicMock | None = None) -> ChatLocalFlow:
    return ChatLocalFlow(cm or _cm())


def _ctx(message: str = "confirmo", budget: int = 1000,
         language_override: str = "auto") -> LocalFlowContext:
    return LocalFlowContext(
        session=MagicMock(),
        trace_id="trc_test",
        message=message,
        daily_budget=budget,
        warnings=[],
        save_message=MagicMock(),
        get_usage=MagicMock(return_value=50),
        language_override=language_override,
    )


def _pending_action(
    *,
    status: str = "pending",
    confirmation_phrase: str = "confirmo ejecutar act_001",
    summary: str = "git pull",
    action_id: str = "act_001",
) -> MagicMock:
    action = MagicMock()
    action.id = action_id
    action.status = status
    action.confirmation_phrase = confirmation_phrase
    action.summary = summary
    return action


# ---------------------------------------------------------------------------
# _handle_referenced_action_id
# ---------------------------------------------------------------------------

class TestHandleReferencedActionId:
    def test_no_action_id_in_message_returns_none(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = None
        flow = _flow(cm)
        assert flow._handle_referenced_action_id(_ctx("hola")) is None

    def test_action_found_pending_exact_phrase_returns_none(self):
        """Exact confirmation phrase → let PendingActionRunner handle it."""
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        action = _pending_action(confirmation_phrase="confirmo ejecutar act_001")
        cm.find_action_by_id.return_value = action
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("confirmo ejecutar act_001"))
        assert result is None

    def test_action_found_pending_wrong_phrase_with_prefix_returns_correction(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        action = _pending_action(confirmation_phrase="confirmo ejecutar act_001")
        cm.find_action_by_id.return_value = action
        cm.message_starts_with_confirmation_prefix.return_value = True
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("confirmar act_001 ahora"))
        assert isinstance(result, ChatMessageResponse)
        assert "act_001" in result.text
        assert "confirmo ejecutar act_001" in result.text

    def test_action_found_pending_wrong_phrase_no_prefix_returns_none(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        action = _pending_action(confirmation_phrase="confirmo ejecutar act_001")
        cm.find_action_by_id.return_value = action
        cm.message_starts_with_confirmation_prefix.return_value = False
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("menciono act_001 de pasada"))
        assert result is None

    def test_action_executed_status_returns_response(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        cm.find_action_by_id.return_value = _pending_action(status="executed")
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("act_001"))
        assert isinstance(result, ChatMessageResponse)
        assert "ejecutada" in result.text.lower()

    def test_action_expired_status_returns_response(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        cm.find_action_by_id.return_value = _pending_action(status="expired")
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("act_001"))
        assert isinstance(result, ChatMessageResponse)
        assert "expiró" in result.text.lower() or "expired" in result.text.lower() or "nueva" in result.text.lower()

    def test_action_failed_status_returns_response(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        cm.find_action_by_id.return_value = _pending_action(status="failed")
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("act_001"))
        assert isinstance(result, ChatMessageResponse)
        assert "falló" in result.text.lower() or "failed" in result.text.lower()

    def test_action_cancelled_non_executed_status_returns_generic_text(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_001"
        cm.find_action_by_id.return_value = _pending_action(status="cancelled")
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("act_001"))
        assert isinstance(result, ChatMessageResponse)
        assert "act_001" in result.text

    def test_action_not_found_returns_not_found_response(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_999"
        cm.find_action_by_id.return_value = None
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("act_999"))
        assert isinstance(result, ChatMessageResponse)
        assert "act_999" in result.text


# ---------------------------------------------------------------------------
# _handle_pending_confirmation
# ---------------------------------------------------------------------------

class TestHandlePendingConfirmation:
    def test_exact_confirmation_phrase_match_returns_none(self):
        """find_pending_action_by_confirmation found → runner will handle it."""
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = _pending_action()
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("confirmo ejecutar act_001"))
        assert result is None

    def test_multiple_pending_generic_confirmation_returns_disambiguation(self):
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = True
        cm.is_generic_confirmation_message.return_value = True
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("ok"))
        assert isinstance(result, ChatMessageResponse)
        assert "varias acciones" in result.text.lower()

    def test_context_match_returns_none(self):
        """find_pending_action_by_context found → runner will handle it."""
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = _pending_action()
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("sí, el git pull"))
        assert result is None

    def test_generic_confirmation_with_latest_action_returns_hint(self):
        latest = _pending_action(
            summary="git push origin main",
            confirmation_phrase="confirmo ejecutar act_001",
        )
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = None
        cm.is_generic_confirmation_message.return_value = True
        cm.get_latest_active_pending_action.return_value = latest
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("ok"))
        assert isinstance(result, ChatMessageResponse)
        assert "git push origin main" in result.text
        assert "confirmo ejecutar act_001" in result.text

    def test_generic_confirmation_no_pending_action_returns_none(self):
        """Casual 'ok'/'vale' with no pending actions → fall through to AI."""
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = None
        cm.is_generic_confirmation_message.return_value = True
        cm.get_latest_active_pending_action.return_value = None
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("ok"))
        assert result is None

    def test_non_confirmation_message_returns_none(self):
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = None
        cm.is_generic_confirmation_message.return_value = False
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("¿cuánto es 2+2?"))
        assert result is None

    def test_multiple_pending_non_generic_skips_disambiguation(self):
        """Multiple pending but message isn't a generic confirmation → not intercepted."""
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = True
        cm.is_generic_confirmation_message.return_value = False
        cm.find_pending_action_by_context.return_value = None
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("cuéntame un chiste"))
        assert result is None


# ---------------------------------------------------------------------------
# try_handle — integration: reaches _handle_referenced_action_id and
# _handle_pending_confirmation when there is no active proposal
# ---------------------------------------------------------------------------

class TestTryHandleNoProposal:
    def test_no_proposal_referenced_action_not_found_returns_response(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_404"
        cm.find_action_by_id.return_value = None

        with patch("app.chat.local_flow.get_proposal", return_value=None):
            flow = _flow(cm)
            result = flow.try_handle(_ctx("act_404"))

        assert isinstance(result, ChatMessageResponse)
        assert "act_404" in result.text

    def test_no_proposal_no_action_id_no_confirmation_returns_none(self):
        cm = _cm()
        cm.extract_action_id_from_message.return_value = None
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = None
        cm.is_generic_confirmation_message.return_value = False

        with patch("app.chat.local_flow.get_proposal", return_value=None):
            flow = _flow(cm)
            result = flow.try_handle(_ctx("pregunta normal"))

        assert result is None

    def test_no_proposal_pending_confirmation_handler_returns_response(self):
        """_handle_referenced_action_id → None, _handle_pending_confirmation → response.
        Covers line 70 (return response from _handle_pending_confirmation inside try_handle)."""
        latest = _pending_action(summary="git pull", confirmation_phrase="confirmo ejecutar act_001")
        cm = _cm()
        cm.extract_action_id_from_message.return_value = None
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = None
        cm.is_generic_confirmation_message.return_value = True
        cm.get_latest_active_pending_action.return_value = latest

        with patch("app.chat.local_flow.get_proposal", return_value=None):
            flow = _flow(cm)
            result = flow.try_handle(_ctx("ok"))

        assert isinstance(result, ChatMessageResponse)
        assert "git pull" in result.text


# ---------------------------------------------------------------------------
# Language support
# ---------------------------------------------------------------------------

class TestLocalFlowLanguage:
    def test_action_not_found_english(self):
        """language_override='en-US' → English 'can't find' message."""
        cm = _cm()
        cm.extract_action_id_from_message.return_value = "act_999"
        cm.find_action_by_id.return_value = None
        flow = _flow(cm)
        result = flow._handle_referenced_action_id(_ctx("act_999", language_override="en-US"))
        assert isinstance(result, ChatMessageResponse)
        assert "can't find" in result.text.lower()
        assert "encuentro" not in result.text.lower()

    def test_ambiguous_confirmation_english(self):
        """language_override='en-US' → 'Do you mean' in English."""
        latest = _pending_action(summary="git push", confirmation_phrase="confirmo ejecutar act_001")
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = False
        cm.find_pending_action_by_context.return_value = None
        cm.is_generic_confirmation_message.return_value = True
        cm.get_latest_active_pending_action.return_value = latest
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("ok", language_override="en-US"))
        assert isinstance(result, ChatMessageResponse)
        assert "do you mean" in result.text.lower()
        assert "refieres" not in result.text.lower()

    def test_multiple_pending_english(self):
        """language_override='en-US' → 'multiple pending actions' in English."""
        cm = _cm()
        cm.find_pending_action_by_confirmation.return_value = None
        cm.has_multiple_active_pending_actions.return_value = True
        cm.is_generic_confirmation_message.return_value = True
        flow = _flow(cm)
        result = flow._handle_pending_confirmation(_ctx("ok", language_override="en-US"))
        assert isinstance(result, ChatMessageResponse)
        assert "multiple" in result.text.lower()
        assert "varias" not in result.text.lower()

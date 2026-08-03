"""Tests for app.tools.handlers.pending_action_tools.

Covers handle_cancel_pending_action:
- missing action_id → error (no DB touch)
- action not found → error
- action found but not pending → error
- happy path: status set to cancelled, commit called, write_log called
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tools.handlers.pending_action_tools import handle_cancel_pending_action
from app.tools.registry import ToolContext


def _executor(*, action=None, session_id="sess_test"):
    executor = MagicMock()
    executor.session_id = session_id
    cm = MagicMock()
    cm.find_action_by_id.return_value = action
    return executor, cm


def _ctx(tool_input: dict, executor=None) -> ToolContext:
    if executor is None:
        executor = MagicMock()
        executor.session_id = "sess_test"
    return ToolContext(
        tool_name="cancel_pending_action",
        tool_input=tool_input,
        trace_id="trc_test",
        executor=executor,
    )


def _pending_action(status="pending") -> MagicMock:
    action = MagicMock()
    action.id = "act-001"
    action.status = status
    action.action_type = "git"
    action.summary = "git pull"
    return action


# ---------------------------------------------------------------------------
# missing / empty action_id
# ---------------------------------------------------------------------------

class TestMissingActionId:
    def test_empty_string_returns_error(self):
        result = handle_cancel_pending_action(_ctx({"action_id": ""}))
        assert result.ok is False
        assert "action_id" in result.message.lower() or "falta" in result.message.lower()
        assert result.raw_result["ok"] is False

    def test_missing_key_returns_error(self):
        result = handle_cancel_pending_action(_ctx({}))
        assert result.ok is False

    def test_whitespace_only_returns_error(self):
        result = handle_cancel_pending_action(_ctx({"action_id": "   "}))
        assert result.ok is False

    def test_no_db_access_when_action_id_missing(self):
        executor = MagicMock()
        ctx = _ctx({"action_id": ""}, executor=executor)
        handle_cancel_pending_action(ctx)
        executor.session.add.assert_not_called()
        executor.session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# action not found or not pending
# ---------------------------------------------------------------------------

class TestActionNotFound:
    def test_none_action_returns_error(self):
        with patch("app.tools.handlers.pending_action_tools.ConfirmationManager") as MockCM:
            MockCM.return_value.find_action_by_id.return_value = None
            result = handle_cancel_pending_action(_ctx({"action_id": "act-001"}))
        assert result.ok is False
        assert "cancelar" in result.message.lower() or "pendiente" in result.message.lower()

    def test_executed_action_returns_error(self):
        action = _pending_action(status="executed")
        with patch("app.tools.handlers.pending_action_tools.ConfirmationManager") as MockCM:
            MockCM.return_value.find_action_by_id.return_value = action
            result = handle_cancel_pending_action(_ctx({"action_id": "act-001"}))
        assert result.ok is False

    def test_cancelled_action_returns_error(self):
        action = _pending_action(status="cancelled")
        with patch("app.tools.handlers.pending_action_tools.ConfirmationManager") as MockCM:
            MockCM.return_value.find_action_by_id.return_value = action
            result = handle_cancel_pending_action(_ctx({"action_id": "act-001"}))
        assert result.ok is False

    def test_no_commit_when_not_found(self):
        executor = MagicMock()
        ctx = _ctx({"action_id": "act-999"}, executor=executor)
        with patch("app.tools.handlers.pending_action_tools.ConfirmationManager") as MockCM:
            MockCM.return_value.find_action_by_id.return_value = None
            handle_cancel_pending_action(ctx)
        executor.session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------

class TestCancelSuccess:
    def _run(self, reason: str = ""):
        action = _pending_action(status="pending")
        executor = MagicMock()
        executor.session_id = "sess_test"
        ctx = _ctx({"action_id": "act-001", "reason": reason}, executor=executor)

        with patch("app.tools.handlers.pending_action_tools.ConfirmationManager") as MockCM, \
             patch("app.tools.handlers.pending_action_tools.write_log") as mock_log:
            MockCM.return_value.find_action_by_id.return_value = action
            result = handle_cancel_pending_action(ctx)

        return result, action, executor, mock_log

    def test_returns_ok_true(self):
        result, *_ = self._run()
        assert result.ok is True

    def test_action_status_set_to_cancelled(self):
        _, action, *_ = self._run()
        assert action.status == "cancelled"

    def test_session_add_and_commit_called(self):
        _, action, executor, _ = self._run()
        executor.session.add.assert_called_once_with(action)
        executor.session.commit.assert_called_once()

    def test_write_log_called_with_audit(self):
        _, _, _, mock_log = self._run(reason="ya no quiero")
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("audit") is True
        assert call_kwargs.get("level") == "AUDIT"
        assert call_kwargs["payload"]["reason"] == "ya no quiero"

    def test_result_contains_action_id(self):
        result, *_ = self._run()
        assert result.raw_result["action_id"] == "act-001"
        assert result.raw_result["ok"] is True

    def test_action_id_lowercased(self):
        action = _pending_action(status="pending")
        executor = MagicMock()
        ctx = _ctx({"action_id": "ACT-001"}, executor=executor)
        with patch("app.tools.handlers.pending_action_tools.ConfirmationManager") as MockCM, \
             patch("app.tools.handlers.pending_action_tools.write_log"):
            MockCM.return_value.find_action_by_id.return_value = action
            handle_cancel_pending_action(ctx)
        MockCM.return_value.find_action_by_id.assert_called_once_with("act-001")

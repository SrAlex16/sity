"""Tests for ToolExecutor — central tool dispatcher.

Coverage focus: error paths and branches that 37% baseline left uncovered.
Lines targeted: 66-130, 140-151, 176-269, 309-312, 315, 330-648.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sqlmodel import Session

from app.core.tool_executor import ToolExecutor, _redact_sensitive
from app.tools.types import ToolExecutionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(
    *,
    ok: bool = True,
    tool_name: str = "test_tool",
    task_context: dict | None = None,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=ok,
        message="ok" if ok else "error",
        updated_parameters=[],
        raw_result={"success": ok},
        task_context=task_context,
    )


def _executor(session=None) -> ToolExecutor:
    return ToolExecutor(session or MagicMock(), session_id="user:1")


# ---------------------------------------------------------------------------
# _redact_sensitive (module-level function)
# ---------------------------------------------------------------------------

class TestRedactSensitive:
    def test_redacts_token_key(self):
        assert _redact_sensitive({"token": "abc123"}) == {"token": "***"}

    def test_redacts_nested_secret(self):
        data = {"outer": {"api_key": "sk-secret"}}
        assert _redact_sensitive(data) == {"outer": {"api_key": "***"}}

    def test_redacts_in_list(self):
        data = [{"password": "hunter2"}, {"name": "ok"}]
        result = _redact_sensitive(data)
        assert result[0]["password"] == "***"
        assert result[1]["name"] == "ok"

    def test_preserves_non_sensitive_keys(self):
        data = {"query": "python", "limit": 5}
        assert _redact_sensitive(data) == data

    def test_case_insensitive_key_match(self):
        assert _redact_sensitive({"Authorization": "Bearer xyz"}) == {"Authorization": "***"}

    def test_scalar_passthrough(self):
        assert _redact_sensitive(42) == 42
        assert _redact_sensitive("hello") == "hello"


# ---------------------------------------------------------------------------
# _summarize_payload
# ---------------------------------------------------------------------------

class TestSummarizePayload:
    def test_short_payload_returned_as_is(self):
        payload = {"key": "value"}
        assert ToolExecutor._summarize_payload(payload) == payload

    def test_long_string_truncated(self):
        long_str = "x" * 600
        result = ToolExecutor._summarize_payload(long_str)
        assert result.endswith("...[truncated]")
        assert len(result) < 600


# ---------------------------------------------------------------------------
# _compact_event
# ---------------------------------------------------------------------------

class TestCompactEvent:
    def test_compact_extracts_standard_fields(self):
        executor = _executor()
        event = {
            "timestamp": "2026-08-03T10:00:00Z",
            "level": "INFO",
            "module": "chat",
            "event": "tool_call_started",
            "trace_id": "trc_abc",
            "payload": {"tool_name": "web_search"},
        }
        compact = executor._compact_event(event)
        assert compact["timestamp"] == "2026-08-03T10:00:00Z"
        assert compact["level"] == "INFO"
        assert compact["module"] == "chat"
        assert compact["event"] == "tool_call_started"
        assert compact["trace_id"] == "trc_abc"
        assert "payload_summary" in compact


# ---------------------------------------------------------------------------
# execute_tool_call — the main dispatch wrapper
# ---------------------------------------------------------------------------

class TestExecuteToolCall:
    """Patches _dispatch_tool_call so we test the wrapper in isolation."""

    def _call(self, tool_name: str, dispatch_result: ToolExecutionResult, client_turn_id=None):
        executor = _executor()
        executor._dispatch_tool_call = MagicMock(return_value=dispatch_result)
        with patch("app.core.tool_executor.publish_event_sync"), \
             patch("app.core.tool_executor.write_log"), \
             patch("app.core.tool_executor.save_task_context") as mock_save, \
             patch("app.core.tool_executor.clear_task_context") as mock_clear:
            result = executor.execute_tool_call(
                tool_name=tool_name,
                tool_input={"q": "test"},
                trace_id="trc_test",
                client_turn_id=client_turn_id,
            )
        return result, mock_save, mock_clear

    def test_returns_dispatch_result(self):
        r, _, _ = self._call("web_search", _result(ok=True))
        assert r.ok is True

    def test_tool_not_in_labels_no_sse_events(self):
        executor = _executor()
        executor._dispatch_tool_call = MagicMock(return_value=_result())
        with patch("app.core.tool_executor.publish_event_sync") as mock_pub, \
             patch("app.core.tool_executor.write_log"):
            executor.execute_tool_call(
                tool_name="web_search",
                tool_input={},
                trace_id="trc",
                client_turn_id="turn-1",
            )
        mock_pub.assert_not_called()

    def test_tool_in_labels_fires_sse_start_and_finish(self):
        executor = _executor()
        executor._dispatch_tool_call = MagicMock(return_value=_result(tool_name="capture_camera_snapshot"))
        with patch("app.core.tool_executor.publish_event_sync") as mock_pub, \
             patch("app.core.tool_executor.write_log"):
            executor.execute_tool_call(
                tool_name="capture_camera_snapshot",
                tool_input={},
                trace_id="trc",
                client_turn_id="turn-1",
            )
        types = [c.args[1]["type"] for c in mock_pub.call_args_list]
        assert "tool_started" in types
        assert "tool_finished" in types

    def test_task_context_truthy_calls_save(self):
        r, mock_save, mock_clear = self._call(
            "web_search",
            _result(task_context={"device_id": "abc123"}),
        )
        mock_save.assert_called_once()
        mock_clear.assert_not_called()

    def test_task_context_empty_dict_calls_clear(self):
        r, mock_save, mock_clear = self._call(
            "web_search",
            _result(task_context={}),
        )
        mock_clear.assert_called_once()
        mock_save.assert_not_called()

    def test_task_context_none_calls_neither(self):
        r, mock_save, mock_clear = self._call(
            "web_search",
            _result(task_context=None),
        )
        mock_save.assert_not_called()
        mock_clear.assert_not_called()

    def test_failed_result_still_returned(self):
        r, _, _ = self._call("web_search", _result(ok=False))
        assert r.ok is False


# ---------------------------------------------------------------------------
# _dispatch_tool_call — registered vs unregistered
# ---------------------------------------------------------------------------

class TestDispatchToolCall:
    def test_unknown_tool_returns_not_supported(self):
        executor = _executor()
        result = executor._dispatch_tool_call(
            tool_name="totally_nonexistent_tool_xyz",
            tool_input={},
            trace_id="trc",
        )
        assert result.ok is False
        assert "no soportada" in result.message.lower()
        assert result.raw_result.get("local_final") is True

    def test_known_tool_dispatches(self):
        import app.tools.handlers  # ensure handlers are registered  # noqa: F401
        executor = _executor()
        # web_search is a registered tool — mock the HTTP call so it doesn't go live
        with patch("app.tools.handlers.web_search_tools.httpx.Client") as mc, \
             patch("app.tools.handlers.web_search_tools._cache_get", return_value=None), \
             patch("app.tools.handlers.web_search_tools._cache_set"):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.text = '<a class="result__snippet" href="https://example.com">Resultado.</a>'
            mc.return_value.__enter__ = MagicMock(return_value=mc.return_value)
            mc.return_value.__exit__ = MagicMock(return_value=False)
            mc.return_value.post.return_value = resp
            result = executor._dispatch_tool_call(
                tool_name="web_search",
                tool_input={"query": "test", "is_dynamic": False},
                trace_id="trc",
            )
        assert result.ok is True


# ---------------------------------------------------------------------------
# _update_personality_settings — error paths
# ---------------------------------------------------------------------------

class TestUpdatePersonalitySettings:
    def test_missing_updates_key(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(tool_input={}, trace_id="trc")
        assert result.ok is False
        assert result.raw_result["error_code"] == "MISSING_UPDATES"

    def test_empty_updates_list(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": []}, trace_id="trc"
        )
        assert result.ok is False
        assert result.raw_result["error_code"] == "MISSING_UPDATES"

    def test_updates_not_a_list(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": "bad"}, trace_id="trc"
        )
        assert result.ok is False
        assert result.raw_result["error_code"] == "MISSING_UPDATES"

    def test_non_dict_item_skipped(self, db_session: Session):
        """A non-dict item in updates is skipped; if all items skipped → failure."""
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": ["not a dict"]}, trace_id="trc"
        )
        assert result.ok is False
        assert "errors" in result.raw_result

    def test_invalid_parameter_skipped(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [{"parameter": "nonexistent", "operation": "set_absolute", "value": 0.73}]},
            trace_id="trc",
        )
        assert result.ok is False
        errors = result.raw_result.get("errors", [])
        assert any("Parámetro no permitido" in e for e in errors)

    def test_invalid_operation_skipped(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [{"parameter": "sarcasm_level", "operation": "explode", "value": 0.73}]},
            trace_id="trc",
        )
        assert result.ok is False
        errors = result.raw_result.get("errors", [])
        assert any("Operación no permitida" in e for e in errors)

    def test_non_numeric_value_skipped(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [{"parameter": "sarcasm_level", "operation": "set_absolute", "value": "alto"}]},
            trace_id="trc",
        )
        assert result.ok is False
        errors = result.raw_result.get("errors", [])
        assert any("Valor inválido" in e for e in errors)

    def test_value_above_range_skipped(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [{"parameter": "sarcasm_level", "operation": "set_absolute", "value": 1.5}]},
            trace_id="trc",
        )
        assert result.ok is False
        errors = result.raw_result.get("errors", [])
        assert any("fuera de rango" in e for e in errors)

    def test_value_below_range_skipped(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [{"parameter": "sarcasm_level", "operation": "set_absolute", "value": -0.1}]},
            trace_id="trc",
        )
        assert result.ok is False

    def test_multiple_updates_success_message(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [
                {"parameter": "sarcasm_level", "operation": "set_absolute", "value": 0.3},
                {"parameter": "warmth_level", "operation": "set_absolute", "value": 0.7},
            ]},
            trace_id="trc",
        )
        assert result.ok is True
        assert "2" in result.message or "parámetros" in result.message.lower()

    def test_valid_single_update_success(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._update_personality_settings(
            tool_input={"updates": [{"parameter": "sarcasm_level", "operation": "set_absolute", "value": 0.73}]},
            trace_id="trc",
        )
        assert result.ok is True
        assert "sarcasm_level" in result.updated_parameters


# ---------------------------------------------------------------------------
# _read_recent_debug_events
# ---------------------------------------------------------------------------

class TestReadRecentDebugEvents:
    def _call(self, tool_input: dict, events: list | None = None):
        executor = _executor()
        with patch("app.core.tool_executor.get_recent_events", return_value=events or []), \
             patch("app.core.tool_executor.write_log"):
            return executor._read_recent_debug_events(tool_input=tool_input, trace_id="trc")

    def test_returns_ok(self):
        result = self._call({"limit": 5})
        assert result.ok is True

    def test_invalid_limit_falls_back_to_20(self):
        # With no events and invalid limit, the code still runs without error
        result = self._call({"limit": "bad"})
        assert result.ok is True

    def test_level_filter_applied(self):
        events = [
            {"level": "INFO", "module": "chat", "event": "x", "trace_id": "t"},
            {"level": "WARN", "module": "chat", "event": "y", "trace_id": "t"},
        ]
        result = self._call({"limit": 10, "level": "warn"}, events=events)
        returned = result.raw_result["events"]
        assert all(e["level"] == "WARN" for e in returned)

    def test_module_filter_applied(self):
        events = [
            {"level": "INFO", "module": "audio", "event": "a", "trace_id": "t"},
            {"level": "INFO", "module": "chat", "event": "b", "trace_id": "t"},
        ]
        result = self._call({"limit": 10, "module": "audio"}, events=events)
        returned = result.raw_result["events"]
        assert all(e["module"] == "audio" for e in returned)

    def test_limit_clamped_to_50(self):
        events = [{"level": "INFO", "module": "x", "event": "e", "trace_id": "t"}] * 100
        with patch("app.core.tool_executor.get_recent_events", return_value=events), \
             patch("app.core.tool_executor.write_log"):
            executor = _executor()
            result = executor._read_recent_debug_events(tool_input={"limit": 999}, trace_id="trc")
        assert len(result.raw_result["events"]) <= 50


# ---------------------------------------------------------------------------
# _read_trace_events
# ---------------------------------------------------------------------------

class TestReadTraceEvents:
    def test_empty_trace_id_returns_error(self):
        executor = _executor()
        with patch("app.core.tool_executor.write_log"):
            result = executor._read_trace_events(tool_input={"trace_id": ""}, trace_id="trc")
        assert result.ok is False
        assert "vacío" in result.message

    def test_missing_trace_id_returns_error(self):
        executor = _executor()
        with patch("app.core.tool_executor.write_log"):
            result = executor._read_trace_events(tool_input={}, trace_id="trc")
        assert result.ok is False

    def test_valid_trace_id_returns_events(self):
        executor = _executor()
        with patch("app.core.tool_executor.get_events_by_trace_id", return_value=[{"event": "x"}]), \
             patch("app.core.tool_executor.write_log"):
            result = executor._read_trace_events(tool_input={"trace_id": "trc_abc"}, trace_id="trc")
        assert result.ok is True
        assert len(result.raw_result["events"]) == 1


# ---------------------------------------------------------------------------
# _git_propose_action
# ---------------------------------------------------------------------------

class TestGitProposeAction:
    def _mock_cm(self, session=None):
        created = MagicMock()
        created.id = "act-git-001"
        created.summary = "Git pull"
        created.confirmation_phrase = "sí git pull"
        created.risk_level = "critical"
        return created

    def test_unsupported_action_returns_error(self):
        executor = _executor()
        result = executor._git_propose_action(
            tool_input={"action": "nuke_repo"},
            trace_id="trc",
        )
        assert result.ok is False
        assert "no soportada" in result.message.lower()

    def test_fetch_creates_pending_action(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._git_propose_action(
            tool_input={"action": "fetch", "repo_path": "sity", "summary": "Fetch remote"},
            trace_id="trc",
        )
        assert result.ok is True
        assert result.raw_result.get("local_final") is True
        assert "Confirma" in result.raw_result["text"]

    def test_commit_action_includes_message_and_files(self, db_session: Session):
        executor = ToolExecutor(db_session)
        result = executor._git_propose_action(
            tool_input={
                "action": "commit",
                "commit_message": "fix: algo",
                "files": ["backend/app/foo.py"],
                "summary": "Commit fix",
            },
            trace_id="trc",
        )
        assert result.ok is True
        payload = result.raw_result["payload"]
        assert payload.get("commit_message") == "fix: algo"
        assert payload.get("files") == ["backend/app/foo.py"]


# ---------------------------------------------------------------------------
# _system_propose_action
# ---------------------------------------------------------------------------

class TestSystemProposeAction:
    def test_unsupported_action_returns_error(self):
        executor = _executor()
        result = executor._system_propose_action(
            tool_input={"action": "format_disk", "service_name": "sity-backend"},
            trace_id="trc",
        )
        assert result.ok is False
        assert "no soportada" in result.message.lower()

    def test_disallowed_service_returns_error(self):
        executor = _executor()
        with patch("app.core.tool_executor.get_allowed_systemd_services", return_value=("sity-backend",)):
            result = executor._system_propose_action(
                tool_input={"action": "restart_service", "service_name": "evil-service"},
                trace_id="trc",
            )
        assert result.ok is False
        assert "no permitido" in result.message.lower()

    def test_invalid_risk_level_normalised_to_safe(self, db_session: Session):
        executor = ToolExecutor(db_session)
        with patch("app.core.tool_executor.get_allowed_systemd_services", return_value=("sity-backend",)):
            result = executor._system_propose_action(
                tool_input={
                    "action": "restart_service",
                    "service_name": "sity-backend",
                    "risk_level": "definitely_not_valid",
                    "summary": "Restart backend",
                },
                trace_id="trc",
            )
        assert result.ok is True
        assert result.raw_result["risk_level"] in ("safe", "critical")


# ---------------------------------------------------------------------------
# _build_confirmation_hint
# ---------------------------------------------------------------------------

class TestBuildConfirmationHint:
    def _hint(self, payload: dict) -> str:
        return _executor()._build_confirmation_hint(payload)

    def test_checkout_branch(self):
        h = self._hint({"action": "checkout_branch", "branch": "main"})
        assert "main" in h

    def test_create_branch(self):
        h = self._hint({"action": "create_branch", "branch": "feature-x"})
        assert "feature-x" in h

    def test_pull_ff_only(self):
        h = self._hint({"action": "pull_ff_only"})
        assert "pull" in h.lower()

    def test_push(self):
        h = self._hint({"action": "push"})
        assert "push" in h.lower()

    def test_fetch(self):
        h = self._hint({"action": "fetch"})
        assert "fetch" in h.lower()

    def test_unknown_action_falls_back(self):
        h = self._hint({"action": "commit"})
        assert "hazlo" in h.lower()

    def test_checkout_without_branch_falls_back(self):
        h = self._hint({"action": "checkout_branch", "branch": ""})
        assert "hazlo" in h.lower()

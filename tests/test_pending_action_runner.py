"""Tests for PendingActionRunner — covers the confirmation→execution pipeline.

Priority: failure paths (ok=False and exceptions) over happy paths, because
the happy path runs in production daily while failure handling has never been
exercised by the test suite.

Patching strategy: patch execute_* and parse_* at the site where they are
imported (app.chat.pending_action_runner.*), not at their original modules.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.actions.ha_actions import HaActionResult
from app.api.schemas import ChatMessageResponse
from app.chat.local_flow import LocalFlowContext
from app.chat.pending_action_runner import PendingActionRunner
from app.memory.models import PendingAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPIRES = datetime(2099, 1, 1, tzinfo=timezone.utc)


def _action(action_type: str, payload: dict | None = None, *, summary: str = "Test action") -> PendingAction:
    return PendingAction(
        id="act-001",
        action_type=action_type,
        risk_level="medium",
        summary=summary,
        payload_json=json.dumps(payload or {}),
        confirmation_phrase="confirmar",
        expires_at=_EXPIRES,
    )


def _ctx(*, budget: int = 1000) -> LocalFlowContext:
    return LocalFlowContext(
        session=MagicMock(),
        trace_id="trc_test",
        message="sí",
        daily_budget=budget,
        warnings=[],
        save_message=MagicMock(),
        get_usage=MagicMock(return_value=42),
    )


def _runner() -> tuple[PendingActionRunner, MagicMock]:
    cm = MagicMock()
    return PendingActionRunner(cm), cm


# ---------------------------------------------------------------------------
# run() wrapper — outer envelope behaviour
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_saves_user_and_sity_messages(self):
        runner, _ = _runner()
        ctx = _ctx()
        action = _action("git")
        with patch("app.chat.pending_action_runner.parse_git_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_git_action", return_value={"ok": True, "command": [], "stdout": "ok"}):
            resp = runner.run(action, ctx)

        assert ctx.save_message.call_count == 2
        calls = ctx.save_message.call_args_list
        assert calls[0].kwargs["role"] == "user"
        assert calls[1].kwargs["role"] == "sity"

    def test_run_returns_chat_message_response(self):
        runner, _ = _runner()
        ctx = _ctx()
        action = _action("git")
        with patch("app.chat.pending_action_runner.parse_git_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_git_action", return_value={"ok": True, "command": [], "stdout": ""}):
            resp = runner.run(action, ctx)

        assert isinstance(resp, ChatMessageResponse)
        assert resp.ok is True
        assert resp.provider == "local"
        assert resp.model == "confirmation-manager"

    def test_run_daily_ratio_zero_budget(self):
        """daily_ratio must not divide by zero when budget is 0."""
        runner, _ = _runner()
        ctx = _ctx(budget=0)
        action = _action("git")
        with patch("app.chat.pending_action_runner.parse_git_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_git_action", return_value={"ok": True, "command": [], "stdout": ""}):
            resp = runner.run(action, ctx)

        assert resp.usage.daily_ratio == 0.0

    def test_run_unknown_action_type_does_not_crash(self):
        runner, cm = _runner()
        ctx = _ctx()
        action = _action("nonexistent_type")
        resp = runner.run(action, ctx)

        assert resp.ok is True
        assert "desconocido" in resp.text.lower()
        cm.mark_executed.assert_not_called()
        cm.mark_failed.assert_not_called()


# ---------------------------------------------------------------------------
# Git actions
# ---------------------------------------------------------------------------

class TestRunGit:
    def test_success_marks_executed(self):
        runner, cm = _runner()
        result = {"ok": True, "command": ["git", "pull"], "stdout": "Already up to date."}
        with patch("app.chat.pending_action_runner.parse_git_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_git_action", return_value=result):
            r = runner._run_git(_action("git", summary="git pull"), "trc")

        cm.mark_executed.assert_called_once()
        cm.mark_failed.assert_not_called()
        assert "git pull" in r.text

    def test_success_includes_pre_command_output(self):
        runner, cm = _runner()
        result = {
            "ok": True,
            "command": ["git", "push"],
            "stdout": "",
            "pre_command": ["git", "fetch"],
            "pre_stdout": "From origin",
        }
        with patch("app.chat.pending_action_runner.parse_git_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_git_action", return_value=result):
            r = runner._run_git(_action("git"), "trc")

        assert "Preparación" in r.text
        assert "From origin" in r.text

    def test_failure_marks_failed_with_stderr(self):
        runner, cm = _runner()
        result = {"ok": False, "stderr": "Permission denied"}
        with patch("app.chat.pending_action_runner.parse_git_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_git_action", return_value=result):
            r = runner._run_git(_action("git"), "trc")

        cm.mark_failed.assert_called_once()
        assert "Permission denied" in r.text
        cm.mark_executed.assert_not_called()

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_git_payload", side_effect=ValueError("bad json")):
            r = runner._run_git(_action("git"), "trc")

        cm.mark_failed.assert_called_once()
        assert "bad json" in r.text
        cm.mark_executed.assert_not_called()


# ---------------------------------------------------------------------------
# System actions
# ---------------------------------------------------------------------------

class TestRunSystem:
    def test_success_with_post_status(self):
        runner, cm = _runner()
        result = {"ok": True, "command": ["systemctl", "restart", "sity-backend"], "stdout": "", "post_status": "active"}
        with patch("app.chat.pending_action_runner.parse_system_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_system_action", return_value=result):
            r = runner._run_system(_action("system"), "trc")

        cm.mark_executed.assert_called_once()
        assert "active" in r.text

    def test_failure_with_stderr(self):
        runner, cm = _runner()
        result = {"ok": False, "stderr": "Unit not found"}
        with patch("app.chat.pending_action_runner.parse_system_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_system_action", return_value=result):
            r = runner._run_system(_action("system"), "trc")

        cm.mark_failed.assert_called_once()
        assert "Unit not found" in r.text

    def test_failure_fallback_to_post_status_when_no_stderr(self):
        """If stderr and stdout are both empty, error text mentions post_status."""
        runner, cm = _runner()
        result = {"ok": False, "stderr": "", "stdout": "", "post_status": "failed"}
        with patch("app.chat.pending_action_runner.parse_system_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_system_action", return_value=result):
            r = runner._run_system(_action("system"), "trc")

        cm.mark_failed.assert_called_once()
        assert "failed" in r.text

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_system_payload", side_effect=RuntimeError("oops")):
            r = runner._run_system(_action("system"), "trc")

        cm.mark_failed.assert_called_once()
        assert "oops" in r.text


# ---------------------------------------------------------------------------
# System config actions
# ---------------------------------------------------------------------------

class TestRunSystemConfig:
    def test_success(self):
        runner, cm = _runner()
        result = {"ok": True, "message": "Config updated."}
        with patch("app.chat.pending_action_runner.parse_system_config_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_system_config_action", return_value=result):
            r = runner._run_system_config(_action("system_config"), "trc")

        cm.mark_executed.assert_called_once()
        assert "Config updated." in r.text

    def test_failure(self):
        runner, cm = _runner()
        result = {"ok": False, "stderr": "Config key unknown"}
        with patch("app.chat.pending_action_runner.parse_system_config_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_system_config_action", return_value=result):
            r = runner._run_system_config(_action("system_config"), "trc")

        cm.mark_failed.assert_called_once()
        assert "Config key unknown" in r.text

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_system_config_payload", side_effect=KeyError("missing")):
            r = runner._run_system_config(_action("system_config"), "trc")

        cm.mark_failed.assert_called_once()


# ---------------------------------------------------------------------------
# File actions
# ---------------------------------------------------------------------------

class TestRunFile:
    def _patch_file(self, result: dict):
        return patch("app.chat.pending_action_runner.execute_file_action", return_value=result)

    def test_write_file_created(self):
        runner, cm = _runner()
        action = _action("file", {"action": "write_file"})
        result = {"ok": True, "path": "/tmp/foo.txt", "created": True}
        with self._patch_file(result):
            r = runner._run_file(action, "trc")
        cm.mark_executed.assert_called_once()
        assert "creado" in r.text

    def test_write_file_overwritten(self):
        runner, cm = _runner()
        action = _action("file", {"action": "write_file"})
        result = {"ok": True, "path": "/tmp/foo.txt", "created": False}
        with self._patch_file(result):
            r = runner._run_file(action, "trc")
        assert "sobreescrito" in r.text

    def test_apply_unified_diff_success(self):
        runner, cm = _runner()
        action = _action("file", {"action": "apply_unified_diff"})
        result = {"ok": True, "path": "/tmp/foo.txt"}
        with self._patch_file(result):
            r = runner._run_file(action, "trc")
        assert "Unified diff aplicado" in r.text

    def test_rollback_success(self):
        runner, cm = _runner()
        action = _action("file", {"action": "rollback_file_change"})
        result = {"ok": True, "path": "/tmp/foo.txt", "restored_from_backup_path": "/tmp/foo.bak"}
        with self._patch_file(result):
            r = runner._run_file(action, "trc")
        assert "Rollback" in r.text
        assert "/tmp/foo.bak" in r.text

    def test_apply_unified_diff_failure(self):
        runner, cm = _runner()
        action = _action("file", {"action": "apply_unified_diff"})
        result = {"ok": False, "error": "Hunk mismatch"}
        with self._patch_file(result):
            r = runner._run_file(action, "trc")
        cm.mark_failed.assert_called_once()
        assert "unified diff" in r.text.lower()
        assert "Hunk mismatch" in r.text

    def test_rollback_failure(self):
        runner, cm = _runner()
        action = _action("file", {"action": "rollback_file_change"})
        result = {"ok": False, "error": "Backup not found"}
        with self._patch_file(result):
            r = runner._run_file(action, "trc")
        assert "rollback" in r.text.lower()

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        action = _action("file", {"action": "write_file"})
        with patch("app.chat.pending_action_runner.execute_file_action", side_effect=OSError("disk full")):
            r = runner._run_file(action, "trc")
        cm.mark_failed.assert_called_once()
        assert "disk full" in r.text

    def test_invalid_json_payload_marks_failed(self):
        """json.loads is inside the try/except, so bad JSON is caught and mark_failed called."""
        runner, cm = _runner()
        action = _action("file")
        action.payload_json = "not-valid-json{"
        r = runner._run_file(action, "trc")
        cm.mark_failed.assert_called_once()
        assert "Falló" in r.text


# ---------------------------------------------------------------------------
# HA actions
# ---------------------------------------------------------------------------

class TestRunHA:
    def test_success(self):
        runner, cm = _runner()
        ha_result = HaActionResult(ok=True, text="Luz encendida.")
        with patch("app.chat.pending_action_runner.parse_ha_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_ha_action", return_value=ha_result):
            r = runner._run_ha(_action("ha"), "trc")

        cm.mark_executed.assert_called_once()
        assert r.text == "Luz encendida."

    def test_failure(self):
        runner, cm = _runner()
        ha_result = HaActionResult(ok=False, text="Entity not found")
        with patch("app.chat.pending_action_runner.parse_ha_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_ha_action", return_value=ha_result):
            r = runner._run_ha(_action("ha"), "trc")

        cm.mark_failed.assert_called_once()
        assert "Entity not found" in r.text

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_ha_payload", side_effect=ConnectionError("HA offline")):
            r = runner._run_ha(_action("ha"), "trc")

        cm.mark_failed.assert_called_once()
        assert "HA offline" in r.text


# ---------------------------------------------------------------------------
# Google actions (treated as difícil de testear in production, but the
# runner's own error handling IS testable with a stubbed result)
# ---------------------------------------------------------------------------

class TestRunGoogle:
    def _google_result(self, ok: bool, text: str):
        r = MagicMock()
        r.ok = ok
        r.text = text
        return r

    def test_success(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_google_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_google_action", return_value=self._google_result(True, "Evento creado.")):
            r = runner._run_google(_action("google"), "trc")

        cm.mark_executed.assert_called_once()
        assert r.text == "Evento creado."

    def test_failure(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_google_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_google_action", return_value=self._google_result(False, "Token expired")):
            r = runner._run_google(_action("google"), "trc")

        cm.mark_failed.assert_called_once()
        assert "Token expired" in r.text

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_google_payload", side_effect=TimeoutError("timeout")):
            r = runner._run_google(_action("google"), "trc")

        cm.mark_failed.assert_called_once()
        assert "timeout" in r.text


# ---------------------------------------------------------------------------
# Sense actions
# ---------------------------------------------------------------------------

class TestRunSense:
    def test_success_no_artifact(self):
        runner, cm = _runner()
        result = {"ok": True, "path": ""}
        with patch("app.chat.pending_action_runner.parse_sense_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_sense_action", return_value=result), \
             patch("app.chat.pending_action_runner.capture_artifact_from_path", return_value=None):
            r = runner._run_sense(_action("sense", summary="Foto tomada"), "trc")

        cm.mark_executed.assert_called_once()
        assert r.artifact is None

    def test_failure(self):
        runner, cm = _runner()
        result = {"ok": False, "stderr": "Camera unavailable"}
        with patch("app.chat.pending_action_runner.parse_sense_payload", return_value={}), \
             patch("app.chat.pending_action_runner.execute_sense_action", return_value=result):
            r = runner._run_sense(_action("sense"), "trc")

        cm.mark_failed.assert_called_once()
        assert "Camera unavailable" in r.text

    def test_exception_marks_failed(self):
        runner, cm = _runner()
        with patch("app.chat.pending_action_runner.parse_sense_payload", side_effect=RuntimeError("sensor error")):
            r = runner._run_sense(_action("sense"), "trc")

        cm.mark_failed.assert_called_once()
        assert "sensor error" in r.text

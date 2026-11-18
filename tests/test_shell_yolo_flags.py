"""Tests for shell_tools_enabled and yolo_mode_enabled feature flags.

Default state (both False):
  - execute_shell and set_yolo_mode are absent from SYSTEM_TOOLSET
  - both handlers reject with a clear Spanish error
  - ConfirmationManager never reads User.yolo_mode (always False)
  - _run_shell in PendingActionRunner rejects immediately

With flags enabled (patch app.core.runtime_config.get_runtime_config):
  - handlers proceed normally (existing behaviour)
  - ConfirmationManager reads User.yolo_mode as before
"""
from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.runtime_config import RuntimeConfig, get_runtime_config
from app.tools.registry import ToolContext


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _config_with(**kwargs) -> RuntimeConfig:
    return replace(get_runtime_config(), **kwargs)


_PATCH_CFG = "app.core.runtime_config.get_runtime_config"


def _make_ctx(tool_name: str, tool_input: dict) -> ToolContext:
    executor = MagicMock()
    executor.session = MagicMock()
    executor.session_id = "user:1"
    executor.is_admin = True
    return ToolContext(
        tool_name=tool_name,
        tool_input=tool_input,
        trace_id="test-flags",
        executor=executor,
    )


def _make_in_memory_session() -> Session:
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _make_user(session: Session, email: str, yolo: bool = False):
    from app.memory.models import User
    user = User(email=email, password_hash="x")
    user.yolo_mode = yolo
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 1. SYSTEM_TOOLSET does not contain execute_shell / set_yolo_mode by default
# ---------------------------------------------------------------------------

class TestSystemToolsetDefaults:
    def _toolset_names(self) -> set[str]:
        from app.cortex.tool_schemas.system import SYSTEM_TOOLSET
        return {t["name"] for t in SYSTEM_TOOLSET}

    def test_execute_shell_absent_by_default(self):
        assert "execute_shell" not in self._toolset_names()

    def test_set_yolo_mode_absent_by_default(self):
        assert "set_yolo_mode" not in self._toolset_names()

    def test_essential_tools_still_present(self):
        names = self._toolset_names()
        for expected in ("read_system_status", "read_disk_usage", "read_service_status"):
            assert expected in names


class TestSystemToolsetWithFlagsEnabled:
    def test_execute_shell_present_when_enabled(self):
        from app.cortex.tool_schemas.system import build_system_toolset
        cfg = _config_with(shell_tools_enabled=True, yolo_mode_enabled=False)
        with patch(_PATCH_CFG, return_value=cfg):
            names = {t["name"] for t in build_system_toolset()}
        assert "execute_shell" in names
        assert "set_yolo_mode" not in names

    def test_set_yolo_mode_present_when_enabled(self):
        from app.cortex.tool_schemas.system import build_system_toolset
        cfg = _config_with(shell_tools_enabled=False, yolo_mode_enabled=True)
        with patch(_PATCH_CFG, return_value=cfg):
            names = {t["name"] for t in build_system_toolset()}
        assert "set_yolo_mode" in names
        assert "execute_shell" not in names

    def test_both_tools_present_when_both_enabled(self):
        from app.cortex.tool_schemas.system import build_system_toolset
        cfg = _config_with(shell_tools_enabled=True, yolo_mode_enabled=True)
        with patch(_PATCH_CFG, return_value=cfg):
            names = {t["name"] for t in build_system_toolset()}
        assert "execute_shell" in names
        assert "set_yolo_mode" in names


# ---------------------------------------------------------------------------
# 2. handle_execute_shell rejects when shell_tools_enabled=False
# ---------------------------------------------------------------------------

class TestExecuteShellHandler:
    def test_rejects_when_disabled(self):
        from app.tools.handlers.system_read_tools import handle_execute_shell
        ctx = _make_ctx("execute_shell", {"command": "ls /"})
        cfg = _config_with(shell_tools_enabled=False)
        with patch(_PATCH_CFG, return_value=cfg):
            result = handle_execute_shell(ctx)
        assert result.ok is False
        assert result.raw_result.get("local_final") is True
        assert "desactivada" in result.message.lower() or "desactivado" in result.message.lower()

    def test_proceeds_when_enabled(self):
        from app.tools.handlers.system_read_tools import handle_execute_shell
        ctx = _make_ctx("execute_shell", {"command": "echo hola"})
        cfg = _config_with(shell_tools_enabled=True)
        fake_result = {"ok": True, "stdout": "hola\n", "returncode": 0, "stderr": ""}
        with (
            patch(_PATCH_CFG, return_value=cfg),
            patch("app.actions.shell_actions.classify_command", return_value="read"),
            patch("app.actions.shell_actions.execute_shell_action", return_value=fake_result),
        ):
            result = handle_execute_shell(ctx)
        # Executor is a MagicMock — _simple_read_tool returns a MagicMock result.
        # The important check is that the handler did NOT return an early rejection.
        assert result.raw_result.get("local_final") is not True


# ---------------------------------------------------------------------------
# 3. handle_set_yolo_mode rejects when yolo_mode_enabled=False
# ---------------------------------------------------------------------------

class TestSetYoloModeHandler:
    def test_rejects_when_disabled(self):
        from app.tools.handlers.system_read_tools import handle_set_yolo_mode
        ctx = _make_ctx("set_yolo_mode", {"enabled": True})
        cfg = _config_with(yolo_mode_enabled=False)
        with patch(_PATCH_CFG, return_value=cfg):
            result = handle_set_yolo_mode(ctx)
        assert result.ok is False
        assert "desactivado" in result.message.lower()
        assert result.raw_result.get("local_final") is True

    def test_proceeds_when_enabled(self):
        from app.tools.handlers.system_read_tools import handle_set_yolo_mode
        session = _make_in_memory_session()
        user = _make_user(session, "yolo_handler@test.com", yolo=True)

        executor = MagicMock()
        executor.session = session
        executor.session_id = f"user:{user.id}"
        executor.is_admin = True
        ctx = ToolContext(
            tool_name="set_yolo_mode",
            tool_input={"enabled": False},
            trace_id="test-yolo-enabled",
            executor=executor,
        )
        cfg = _config_with(yolo_mode_enabled=True)
        with patch(_PATCH_CFG, return_value=cfg):
            result = handle_set_yolo_mode(ctx)
        assert result.ok is True


# ---------------------------------------------------------------------------
# 4. ConfirmationManager._load_yolo_mode always False when flag is off
# ---------------------------------------------------------------------------

class TestConfirmationManagerYoloFlag:
    def test_yolo_mode_false_when_flag_off(self):
        from app.actions.confirmation_manager import ConfirmationManager
        session = _make_in_memory_session()
        user = _make_user(session, "yolo_a@test.com", yolo=True)

        cfg = _config_with(yolo_mode_enabled=False)
        with patch(_PATCH_CFG, return_value=cfg):
            cm = ConfirmationManager(session, f"user:{user.id}")
        assert cm.yolo_mode is False

    def test_yolo_mode_reads_db_when_flag_on(self):
        from app.actions.confirmation_manager import ConfirmationManager
        session = _make_in_memory_session()
        user = _make_user(session, "yolo_b@test.com", yolo=True)

        cfg = _config_with(yolo_mode_enabled=True)
        with patch(_PATCH_CFG, return_value=cfg):
            cm = ConfirmationManager(session, f"user:{user.id}")
        assert cm.yolo_mode is True

    def test_create_pending_action_no_yolo_even_if_db_true(self):
        """With yolo flag off, create_pending_action must not auto-execute."""
        from app.actions.confirmation_manager import ConfirmationManager
        session = _make_in_memory_session()
        user = _make_user(session, "yolo_c@test.com", yolo=True)

        cfg = _config_with(yolo_mode_enabled=False)
        with patch(_PATCH_CFG, return_value=cfg):
            cm = ConfirmationManager(session, f"user:{user.id}")
            created = cm.create_pending_action(
                action_type="file",
                risk_level="critical",
                summary="Test sin yolo",
                payload={"action": "write_file", "path": "x.txt", "content": "hi"},
                trace_id="trc_no_yolo",
            )
        assert created.executed is False


# ---------------------------------------------------------------------------
# 5. PendingActionRunner._run_shell rejects when shell flag is off
# ---------------------------------------------------------------------------

class TestPendingActionRunnerShellFlag:
    def _make_shell_action(self, action_id: str = "act_shell_test"):
        from app.memory.models import PendingAction
        action = MagicMock(spec=PendingAction)
        action.id = action_id
        action.action_type = "shell"
        action.payload_json = json.dumps({"command": "ls /"})
        action.summary = "ls /"
        return action

    def test_run_shell_rejects_when_disabled(self):
        from app.chat.pending_action_runner import PendingActionRunner

        cm = MagicMock()
        cm._session_id = "user:1"
        runner = PendingActionRunner(cm)

        cfg = _config_with(shell_tools_enabled=False)
        with patch(_PATCH_CFG, return_value=cfg):
            result = runner._run_shell(self._make_shell_action(), "trc_shell_off", "es")

        assert result.was_executed is False
        assert "desactivado" in result.text.lower()
        cm.mark_failed.assert_called_once()

    def test_run_shell_proceeds_when_enabled(self):
        from app.chat.pending_action_runner import PendingActionRunner

        cm = MagicMock()
        cm._session_id = "user:1"
        runner = PendingActionRunner(cm)

        fake_shell_result = {
            "ok": True, "command": "ls /",
            "returncode": 0, "stdout": "bin\netc\n", "stderr": "", "truncated": False,
        }
        cfg = _config_with(shell_tools_enabled=True)
        with (
            patch(_PATCH_CFG, return_value=cfg),
            patch("app.actions.shell_actions.execute_shell_action", return_value=fake_shell_result),
        ):
            result = runner._run_shell(self._make_shell_action("act_shell_on"), "trc_shell_on", "es")

        assert result.was_executed is True
        assert "bin" in result.text

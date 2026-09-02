"""Tests for app.actions.system_actions.

Mocking strategy:
- get_allowed_systemd_services  → patched at import site
- run_read_command              → patched at import site
- subprocess.Popen              → patched at import site
- time.monotonic / time.sleep   → patched on the module for loop control

Focus: validation-error branches and all post-status / wait branches first.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from app.actions.system_actions import (
    execute_system_action,
    is_allowed_service,
    parse_payload,
    wait_for_service_state,
)

_ALLOWED = ("sity-backend", "nginx")

_RUN_OK = {"ok": True, "stdout": "", "stderr": "", "command": ["sudo", "systemctl"]}
_RUN_FAIL = {"ok": False, "stdout": "", "stderr": "failed", "command": []}


# ---------------------------------------------------------------------------
# parse_payload
# ---------------------------------------------------------------------------

class TestParsePayload:
    def test_valid_json(self):
        data = {"action": "restart_service", "service_name": "nginx"}
        assert parse_payload(json.dumps(data)) == data

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_payload("{bad json")


# ---------------------------------------------------------------------------
# is_allowed_service
# ---------------------------------------------------------------------------

class TestIsAllowedService:
    def test_allowed_service_returns_true(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED):
            assert is_allowed_service("sity-backend") is True

    def test_unknown_service_returns_false(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED):
            assert is_allowed_service("sshd") is False

    def test_empty_allowed_list(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=()):
            assert is_allowed_service("nginx") is False


# ---------------------------------------------------------------------------
# wait_for_service_state
# ---------------------------------------------------------------------------

class TestWaitForServiceState:
    def test_state_found_on_first_check(self):
        with patch("app.actions.system_actions.run_read_command", return_value={"stdout": "active"}), \
             patch("app.actions.system_actions.time.sleep"), \
             patch("app.actions.system_actions.time.monotonic", side_effect=[0.0, 5.0, 999.0]):
            result = wait_for_service_state("nginx", expected_states={"active"}, timeout_seconds=10)
        assert result["ok"] is True
        assert result["status"] == "active"

    def test_timeout_returns_ok_false(self):
        # monotonic starts past deadline immediately → loop body never executes
        with patch("app.actions.system_actions.time.monotonic", side_effect=[0.0, 999.0]):
            result = wait_for_service_state("nginx", expected_states={"active"}, timeout_seconds=10)
        assert result["ok"] is False
        assert result["status"] == "unknown"

    def test_timeout_preserves_last_status(self):
        # First iteration returns inactive (not expected), second call to monotonic exceeds deadline
        call_count = {"n": 0}

        def fake_monotonic():
            call_count["n"] += 1
            # deadline = 0.0 + 10 = 10.0
            # first call (check): return 5.0 (inside window)
            # second call (check): return 15.0 (past deadline)
            return [0.0, 5.0, 15.0][min(call_count["n"] - 1, 2)]

        with patch("app.actions.system_actions.run_read_command", return_value={"stdout": "inactive\n"}), \
             patch("app.actions.system_actions.time.sleep"), \
             patch("app.actions.system_actions.time.monotonic", side_effect=fake_monotonic):
            result = wait_for_service_state("nginx", expected_states={"active"}, timeout_seconds=10)
        assert result["ok"] is False
        assert result["status"] == "inactive"

    def test_multiple_expected_states(self):
        with patch("app.actions.system_actions.run_read_command", return_value={"stdout": "failed"}), \
             patch("app.actions.system_actions.time.sleep"), \
             patch("app.actions.system_actions.time.monotonic", side_effect=[0.0, 5.0, 999.0]):
            result = wait_for_service_state("nginx", expected_states={"inactive", "failed"}, timeout_seconds=10)
        assert result["ok"] is True
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# execute_system_action — validation errors
# ---------------------------------------------------------------------------

class TestExecuteSystemActionValidation:
    def test_unsupported_action_returns_error(self):
        result = execute_system_action({"action": "reboot", "service_name": "nginx"})
        assert result["ok"] is False
        assert "reboot" in result["stderr"]

    def test_missing_action_returns_error(self):
        result = execute_system_action({"service_name": "nginx"})
        assert result["ok"] is False

    def test_missing_service_name_returns_error(self):
        result = execute_system_action({"action": "start_service"})
        assert result["ok"] is False
        assert "service_name" in result["stderr"]

    def test_disallowed_service_returns_error(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED):
            result = execute_system_action({"action": "start_service", "service_name": "sshd"})
        assert result["ok"] is False
        assert "sshd" in result["stderr"]


# ---------------------------------------------------------------------------
# execute_system_action — sity-backend restart (special async path)
# ---------------------------------------------------------------------------

class TestRestartSityBackend:
    def test_popen_called_with_detached_command(self):
        mock_popen = MagicMock()
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.subprocess.Popen", return_value=mock_popen) as popen_mock:
            result = execute_system_action({"action": "restart_service", "service_name": "sity-backend"})

        popen_mock.assert_called_once()
        args = popen_mock.call_args
        assert "sleep" in args[0][0][3]  # shell command contains sleep
        assert result["ok"] is True
        assert result["post_status"] == "scheduled"

    def test_popen_uses_start_new_session(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.subprocess.Popen") as popen_mock:
            execute_system_action({"action": "restart_service", "service_name": "sity-backend"})
        assert popen_mock.call_args.kwargs.get("start_new_session") is True


# ---------------------------------------------------------------------------
# execute_system_action — start_service (wait succeeds)
# ---------------------------------------------------------------------------

class TestStartService:
    def test_start_service_post_status_active(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value={**_RUN_OK}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": True, "status": "active"}):
            result = execute_system_action({"action": "start_service", "service_name": "nginx"})
        assert result["ok"] is True
        assert result["post_status"] == "active"
        assert result["post_status_ok"] is True

    def test_start_service_wait_timeout_inherits_run_ok(self):
        run_result = {**_RUN_OK, "ok": True}
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value=run_result), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": False, "status": "activating"}):
            result = execute_system_action({"action": "start_service", "service_name": "nginx"})
        assert result["post_status"] == "activating"
        assert result["post_status_ok"] is False

    def test_start_service_stdout_added_when_empty(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value={**_RUN_OK, "stdout": ""}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": True, "status": "active"}):
            result = execute_system_action({"action": "start_service", "service_name": "nginx"})
        assert "active" in result["stdout"]

    def test_start_service_existing_stdout_preserved(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command",
                   return_value={**_RUN_OK, "stdout": "already active"}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": True, "status": "active"}):
            result = execute_system_action({"action": "start_service", "service_name": "nginx"})
        assert result["stdout"] == "already active"


# ---------------------------------------------------------------------------
# execute_system_action — restart_service (non-sity-backend, uses wait)
# ---------------------------------------------------------------------------

class TestRestartServiceGeneric:
    def test_restart_other_service_waits_for_active(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value={**_RUN_OK}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": True, "status": "active"}) as mock_wait:
            result = execute_system_action({"action": "restart_service", "service_name": "nginx"})
        mock_wait.assert_called_once_with("nginx", expected_states={"active"}, timeout_seconds=12)
        assert result["ok"] is True
        assert result["post_status"] == "active"


# ---------------------------------------------------------------------------
# execute_system_action — stop_service
# ---------------------------------------------------------------------------

class TestStopService:
    def test_stop_service_waits_for_inactive_or_failed(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value={**_RUN_OK}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": True, "status": "inactive"}) as mock_wait:
            result = execute_system_action({"action": "stop_service", "service_name": "nginx"})
        mock_wait.assert_called_once_with("nginx", expected_states={"inactive", "failed"}, timeout_seconds=12)
        assert result["ok"] is True
        assert result["post_status"] == "inactive"

    def test_stop_service_stdout_added_when_empty(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value={**_RUN_OK, "stdout": ""}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": True, "status": "inactive"}):
            result = execute_system_action({"action": "stop_service", "service_name": "nginx"})
        assert "inactive" in result["stdout"]

    def test_stop_service_wait_timeout(self):
        with patch("app.actions.system_actions.get_allowed_systemd_services", return_value=_ALLOWED), \
             patch("app.actions.system_actions.run_read_command", return_value={**_RUN_OK}), \
             patch("app.actions.system_actions.wait_for_service_state",
                   return_value={"ok": False, "status": "deactivating"}):
            result = execute_system_action({"action": "stop_service", "service_name": "nginx"})
        assert result["post_status"] == "deactivating"
        assert result["post_status_ok"] is False

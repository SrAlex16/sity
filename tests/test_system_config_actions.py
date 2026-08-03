"""Tests for app.actions.system_config_actions.

Mocking strategy:
- load_system_access_config → patched at import site (returns in-memory dict)
- _write_config             → patched to avoid touching config/system_access.yaml
Focus: all validation-error branches, add/remove happy paths,
idempotent (already-present / already-absent) cases, and helpers.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from app.actions.system_config_actions import (
    _is_safe_service_name,
    execute_system_config_action,
    list_allowed_services,
    parse_payload,
)


def _config(read_services=None, action_services=None) -> dict:
    return {
        "system_access": {
            "read": {"allowed_services": list(read_services or [])},
            "safe_actions": {"allowed_services": list(action_services or [])},
        }
    }


def _run(payload: dict, config: dict | None = None):
    cfg = config if config is not None else _config()
    with patch("app.actions.system_config_actions.load_system_access_config", return_value=cfg), \
         patch("app.actions.system_config_actions._write_config"):
        return execute_system_config_action(payload)


# ---------------------------------------------------------------------------
# parse_payload
# ---------------------------------------------------------------------------

class TestParsePayload:
    def test_valid_json(self):
        data = {"action": "add_allowed_service", "service_name": "sity-telegram"}
        assert parse_payload(json.dumps(data)) == data

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_payload("{bad")


# ---------------------------------------------------------------------------
# _is_safe_service_name
# ---------------------------------------------------------------------------

class TestIsSafeServiceName:
    def test_valid_names(self):
        for name in ("nginx", "sity-backend", "sity.service", "app@1", "My_App"):
            assert _is_safe_service_name(name) is True, name

    def test_empty_string_is_invalid(self):
        assert _is_safe_service_name("") is False

    def test_shell_injection_chars_invalid(self):
        for name in ("svc;rm -rf", "svc$(id)", "svc|cat", "svc/../../etc"):
            assert _is_safe_service_name(name) is False, name

    def test_space_is_invalid(self):
        assert _is_safe_service_name("my service") is False


# ---------------------------------------------------------------------------
# list_allowed_services
# ---------------------------------------------------------------------------

class TestListAllowedServices:
    def test_returns_both_service_lists(self):
        cfg = _config(read_services=["nginx"], action_services=["sity-backend"])
        with patch("app.actions.system_config_actions.load_system_access_config", return_value=cfg):
            result = list_allowed_services()
        assert result["ok"] is True
        assert result["read_allowed_services"] == ["nginx"]
        assert result["action_allowed_services"] == ["sity-backend"]

    def test_empty_config_returns_empty_lists(self):
        with patch("app.actions.system_config_actions.load_system_access_config", return_value={}):
            result = list_allowed_services()
        assert result["ok"] is True
        assert result["read_allowed_services"] == []
        assert result["action_allowed_services"] == []


# ---------------------------------------------------------------------------
# execute_system_config_action — validation errors
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_unsupported_action_returns_error(self):
        result = _run({"action": "purge_service", "service_name": "nginx"})
        assert result["ok"] is False
        assert "purge_service" in result["stderr"]

    def test_missing_action_returns_error(self):
        result = _run({"service_name": "nginx"})
        assert result["ok"] is False

    def test_missing_service_name_returns_error(self):
        result = _run({"action": "add_allowed_service"})
        assert result["ok"] is False
        assert "service_name" in result["stderr"]

    def test_unsafe_service_name_returns_error(self):
        result = _run({"action": "add_allowed_service", "service_name": "bad;name"})
        assert result["ok"] is False
        assert "Invalid service name" in result["stderr"]


# ---------------------------------------------------------------------------
# execute_system_config_action — add_allowed_service
# ---------------------------------------------------------------------------

class TestAddAllowedService:
    def test_adds_new_service_to_both_lists(self):
        cfg = _config(read_services=["nginx"], action_services=["nginx"])
        result = _run({"action": "add_allowed_service", "service_name": "sity-telegram"}, cfg)
        assert result["ok"] is True
        assert result["changed"] is True
        assert "sity-telegram" in result["message"]

    def test_idempotent_when_already_present(self):
        cfg = _config(read_services=["nginx"], action_services=["nginx"])
        result = _run({"action": "add_allowed_service", "service_name": "nginx"}, cfg)
        assert result["ok"] is True
        assert result["changed"] is False

    def test_write_config_called(self):
        cfg = _config()
        with patch("app.actions.system_config_actions.load_system_access_config", return_value=cfg), \
             patch("app.actions.system_config_actions._write_config") as mock_write:
            execute_system_config_action({"action": "add_allowed_service", "service_name": "nginx"})
        mock_write.assert_called_once_with(cfg)

    def test_partial_add_when_in_read_but_not_action(self):
        cfg = _config(read_services=["nginx"], action_services=[])
        result = _run({"action": "add_allowed_service", "service_name": "nginx"}, cfg)
        assert result["ok"] is True
        assert result["changed"] is True  # was missing from action_services


# ---------------------------------------------------------------------------
# execute_system_config_action — remove_allowed_service
# ---------------------------------------------------------------------------

class TestRemoveAllowedService:
    def test_removes_existing_service(self):
        cfg = _config(read_services=["nginx", "sshd"], action_services=["nginx"])
        result = _run({"action": "remove_allowed_service", "service_name": "nginx"}, cfg)
        assert result["ok"] is True
        assert result["changed"] is True
        assert "nginx" in result["message"]

    def test_idempotent_when_not_present(self):
        cfg = _config(read_services=["nginx"], action_services=["nginx"])
        result = _run({"action": "remove_allowed_service", "service_name": "sshd"}, cfg)
        assert result["ok"] is True
        assert result["changed"] is False

    def test_write_config_called_on_remove(self):
        cfg = _config(read_services=["nginx"], action_services=["nginx"])
        with patch("app.actions.system_config_actions.load_system_access_config", return_value=cfg), \
             patch("app.actions.system_config_actions._write_config") as mock_write:
            execute_system_config_action({"action": "remove_allowed_service", "service_name": "nginx"})
        mock_write.assert_called_once()

    def test_remove_only_from_action_list_counts_as_changed(self):
        cfg = _config(read_services=[], action_services=["nginx"])
        result = _run({"action": "remove_allowed_service", "service_name": "nginx"}, cfg)
        assert result["changed"] is True

    def test_returns_service_name_and_action_in_result(self):
        cfg = _config(read_services=["nginx"], action_services=["nginx"])
        result = _run({"action": "remove_allowed_service", "service_name": "nginx"}, cfg)
        assert result["service_name"] == "nginx"
        assert result["action"] == "remove_allowed_service"


# ---------------------------------------------------------------------------
# _write_config (integration: verify yaml.safe_dump is called)
# ---------------------------------------------------------------------------

class TestWriteConfig:
    def test_write_config_opens_correct_file(self):
        from app.actions.system_config_actions import _write_config, SYSTEM_ACCESS_CONFIG
        import yaml

        config_data = {"system_access": {}}
        m = mock_open()
        with patch("builtins.open", m), \
             patch("app.actions.system_config_actions.yaml.safe_dump") as mock_dump:
            _write_config(config_data)

        mock_dump.assert_called_once()
        dumped_args = mock_dump.call_args[0]
        assert dumped_args[0] == config_data

"""Tests para las tools de Home Assistant.

Todos los tests usan mocks — sin llamadas reales a la API de HA.
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
        trace_id="test-ha",
        executor=executor,
    )


def _entity(entity_id: str, state: str, friendly: str = "") -> dict:
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": {"friendly_name": friendly or entity_id},
        "area_id": "",
    }


# ── ha_list_entities ──────────────────────────────────────────────────────────

def test_ha_list_entities_returns_controllable_entities() -> None:
    from app.tools.handlers.ha_tools import handle_ha_list_entities

    states = [
        _entity("switch.tapo_p100", "on", "Enchufe dormitorio"),
        _entity("light.salon", "off", "Luz salón"),
        _entity("sensor.temperatura", "22.5"),  # sensor → filtered out
    ]
    ctx = _make_ctx("ha_list_entities", {})
    with patch("app.tools.handlers.ha_tools._ha_get", return_value=states):
        result = handle_ha_list_entities(ctx)

    assert result.ok is True
    assert "switch.tapo_p100" in result.message
    assert "light.salon" in result.message
    assert "sensor.temperatura" not in result.message


def test_ha_list_entities_filters_by_keyword() -> None:
    from app.tools.handlers.ha_tools import handle_ha_list_entities

    states = [
        _entity("switch.tapo_p100", "on", "Enchufe dormitorio"),
        _entity("switch.salon", "off", "Enchufe salón"),
    ]
    ctx = _make_ctx("ha_list_entities", {"keyword": "dormitorio"})
    with patch("app.tools.handlers.ha_tools._ha_get", return_value=states):
        result = handle_ha_list_entities(ctx)

    assert result.ok is True
    assert "switch.tapo_p100" in result.message
    assert "switch.salon" not in result.message


def test_ha_list_entities_no_results() -> None:
    from app.tools.handlers.ha_tools import handle_ha_list_entities

    ctx = _make_ctx("ha_list_entities", {"keyword": "cocina"})
    with patch("app.tools.handlers.ha_tools._ha_get", return_value=[]):
        result = handle_ha_list_entities(ctx)

    assert result.ok is True
    assert "cocina" in result.message


def test_ha_list_entities_connection_error() -> None:
    from app.tools.handlers.ha_tools import handle_ha_list_entities

    ctx = _make_ctx("ha_list_entities", {})
    with patch("app.tools.handlers.ha_tools._ha_get", side_effect=Exception("timeout")):
        result = handle_ha_list_entities(ctx)

    assert result.ok is False
    assert "Home Assistant" in result.message


# ── ha_get_state ──────────────────────────────────────────────────────────────

def test_ha_get_state_returns_formatted_state() -> None:
    from app.tools.handlers.ha_tools import handle_ha_get_state

    entity = {
        "entity_id": "switch.tapo_p100",
        "state": "on",
        "attributes": {"friendly_name": "Enchufe dormitorio", "voltage": 230},
    }
    ctx = _make_ctx("ha_get_state", {"entity_id": "switch.tapo_p100"})
    with patch("app.tools.handlers.ha_tools._ha_get", return_value=entity):
        result = handle_ha_get_state(ctx)

    assert result.ok is True
    assert "Enchufe dormitorio" in result.message
    assert "on" in result.message
    assert "voltage: 230" in result.message


def test_ha_get_state_missing_entity_id() -> None:
    from app.tools.handlers.ha_tools import handle_ha_get_state

    ctx = _make_ctx("ha_get_state", {})
    result = handle_ha_get_state(ctx)

    assert result.ok is False
    assert "entity_id" in result.message.lower()


# ── ha_call_service ───────────────────────────────────────────────────────────

def test_ha_call_service_executes_turn_on_directly() -> None:
    from app.tools.handlers.ha_tools import handle_ha_call_service

    ctx = _make_ctx("ha_call_service", {
        "entity_id": "switch.tapo_p100",
        "service": "turn_on",
    })
    mock_post = MagicMock(return_value=[{"entity_id": "switch.tapo_p100"}])
    with patch("app.tools.handlers.ha_tools._ha_post", mock_post):
        result = handle_ha_call_service(ctx)

    assert result.ok is True
    assert "switch.turn_on" in result.message or "turn_on" in result.message
    mock_post.assert_called_once()


def test_ha_call_service_toggle_executes_directly() -> None:
    from app.tools.handlers.ha_tools import handle_ha_call_service

    ctx = _make_ctx("ha_call_service", {
        "entity_id": "light.salon",
        "service": "toggle",
    })
    mock_post = MagicMock(return_value=[])
    with patch("app.tools.handlers.ha_tools._ha_post", mock_post):
        result = handle_ha_call_service(ctx)

    assert result.ok is True
    mock_post.assert_called_once()


def test_ha_call_service_lock_requires_pending_action() -> None:
    from app.tools.handlers.ha_tools import handle_ha_call_service

    ctx = _make_ctx("ha_call_service", {
        "entity_id": "lock.puerta_principal",
        "service": "lock",
    })
    mock_manager = MagicMock()
    mock_manager.find_equivalent_pending_action.return_value = None
    created = MagicMock()
    created.id = "act_abc12345"
    created.confirmation_phrase = "confirmar acción abc"
    created.summary = "HA: lock.lock en lock.puerta_principal"
    mock_manager.create_pending_action.return_value = created

    with patch("app.tools.handlers.ha_tools.ConfirmationManager", return_value=mock_manager):
        result = handle_ha_call_service(ctx)

    assert result.ok is True
    assert "confirmar acción abc" in result.message
    assert result.raw_result.get("local_final") is True
    mock_manager.create_pending_action.assert_called_once()


def test_ha_call_service_missing_params() -> None:
    from app.tools.handlers.ha_tools import handle_ha_call_service

    ctx = _make_ctx("ha_call_service", {"entity_id": "switch.tapo_p100"})
    result = handle_ha_call_service(ctx)

    assert result.ok is False
    assert "service" in result.message.lower()


def test_ha_call_service_api_error_returns_error() -> None:
    from app.tools.handlers.ha_tools import handle_ha_call_service

    ctx = _make_ctx("ha_call_service", {
        "entity_id": "switch.tapo_p100",
        "service": "turn_on",
    })
    with patch("app.tools.handlers.ha_tools._ha_post", side_effect=Exception("connection refused")):
        result = handle_ha_call_service(ctx)

    assert result.ok is False
    assert "Error" in result.message

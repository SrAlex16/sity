from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select

from app.core.tool_executor import ToolExecutor
from app.memory.models import PendingAction
from app.tools.registry import ToolContext, dispatch_tool, has_handler

TRACE_ID = "trc_service_config_registry_local_test"


def _latest_action(session: Session) -> PendingAction:
    action = session.exec(
        select(PendingAction)
        .where(PendingAction.trace_id == TRACE_ID)
        .order_by(PendingAction.created_at.desc())
    ).first()
    assert action is not None, "No pending action found for test trace_id"
    return action


def _expire_trace_actions(session: Session) -> None:
    for action in session.exec(
        select(PendingAction).where(PendingAction.trace_id == TRACE_ID)
    ):
        action.status = "expired"
        session.add(action)
    session.commit()


@pytest.mark.parametrize("tool_name", ["add_allowed_service", "remove_allowed_service"])
def test_service_config_handlers_registered(tool_name: str) -> None:
    assert has_handler(tool_name), f"{tool_name} not registered"


@pytest.mark.parametrize("tool_name", ["add_allowed_service", "remove_allowed_service"])
def test_service_config_creates_pending_action(db_session: Session, tool_name: str) -> None:
    _expire_trace_actions(db_session)
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name=tool_name,
        tool_input={"service_name": "sity-test"},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, f"{tool_name}: {result}"
    assert "Acción pendiente creada" in result.message, result.message

    action = _latest_action(db_session)
    assert action.status == "pending"
    assert action.action_type == "system_config"
    assert action.risk_level == "critical"

    payload = json.loads(action.payload_json)
    assert payload == {"action": tool_name, "service_name": "sity-test"}, payload

    action.status = "expired"
    db_session.add(action)
    db_session.commit()


@pytest.mark.parametrize("bad_name", ["../../bad", "bad service", "", "bad/path"])
def test_invalid_service_names_rejected(db_session: Session, bad_name: str) -> None:
    _expire_trace_actions(db_session)
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="add_allowed_service",
        tool_input={"service_name": bad_name},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is False, f"Expected rejection for {bad_name!r}, got ok=True"
    assert result.raw_result.get("local_model") == "tool-policy", result.raw_result


@pytest.mark.parametrize("valid_name", [
    "sity-backend", "my.service", "service_v2", "svc@host",
])
def test_valid_edge_case_service_names_accepted(db_session: Session, valid_name: str) -> None:
    _expire_trace_actions(db_session)
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="add_allowed_service",
        tool_input={"service_name": valid_name},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, f"Expected ok for {valid_name!r}: {result}"
    _expire_trace_actions(db_session)

from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select

from app.core.tool_executor import ToolExecutor
from app.memory.models import PendingAction
from app.tools.registry import ToolContext, dispatch_tool, has_handler

TRACE_ID = "trc_file_write_registry_local_test"


def _latest_action(session: Session) -> PendingAction:
    action = session.exec(
        select(PendingAction)
        .where(PendingAction.trace_id == TRACE_ID)
        .order_by(PendingAction.created_at.desc())
    ).first()
    assert action is not None
    return action


def test_write_file_handler_registered() -> None:
    assert has_handler("write_file"), "write_file is not registered"


def test_write_file_creates_pending_action(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="write_file",
        tool_input={
            "path": "config/test-write-registry-local.txt",
            "content": "ok registry local",
            "create_parent_dirs": False,
        },
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, result
    assert "Acción pendiente creada" in result.message, result.message

    action = _latest_action(db_session)
    assert action.status == "pending"
    assert action.action_type == "file"
    assert action.risk_level in {"safe", "critical"}

    payload = json.loads(action.payload_json)
    assert payload["action"] == "write_file", payload
    assert payload["path"] == "config/test-write-registry-local.txt", payload
    assert payload["content"] == "ok registry local", payload
    assert payload["create_parent_dirs"] is False, payload


def test_write_file_blocked_outside_allowlist(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="write_file",
        tool_input={"path": "/etc/sity-registry-blocked.txt", "content": "no"},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is False
    assert result.raw_result.get("local_model") == "tool-policy"

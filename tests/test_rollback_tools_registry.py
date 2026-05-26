from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.actions.file_actions import execute_file_action
from app.core.tool_executor import ToolExecutor
from app.memory.models import PendingAction
from app.tools.registry import ToolContext, dispatch_tool, has_handler

ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "trc_rollback_registry_local_test"
TEST_PATH = "config/test-rollback-registry-local.txt"
_TARGET = ROOT / TEST_PATH


def _latest_action(session: Session) -> PendingAction:
    action = session.exec(
        select(PendingAction)
        .where(PendingAction.trace_id == TRACE_ID)
        .order_by(PendingAction.created_at.desc())
    ).first()
    assert action is not None
    return action


def _make_reversible_change() -> str:
    """Write a real file via file_actions so audit+backup are created."""
    _TARGET.write_text("contenido original\n", encoding="utf-8")
    result = execute_file_action({
        "action": "write_file",
        "path": TEST_PATH,
        "content": "contenido modificado\n",
        "trace_id": TRACE_ID,
    })
    assert result.get("ok"), f"write_file to generate backup failed: {result}"
    backup_path = (result.get("backup") or {}).get("backup_path", "")
    assert backup_path, f"write_file did not generate backup_path: {result}"
    return backup_path


@pytest.fixture(autouse=True)
def cleanup_test_file():
    yield
    _TARGET.unlink(missing_ok=True)


@pytest.mark.parametrize("tool_name", ["rollback_latest_file_change", "rollback_file_change"])
def test_rollback_handlers_registered(tool_name: str) -> None:
    assert has_handler(tool_name), f"{tool_name} is not registered"


def test_rollback_latest_creates_pending_action_without_modifying_file(
    db_session: Session,
) -> None:
    backup_path = _make_reversible_change()
    assert _TARGET.read_text(encoding="utf-8") == "contenido modificado\n"

    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="rollback_latest_file_change",
        tool_input={"include_rollbacks": False},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, f"rollback_latest_file_change failed: {result}"
    assert "Acción pendiente creada" in result.message, result.message

    # file must NOT have changed yet
    assert _TARGET.read_text(encoding="utf-8") == "contenido modificado\n", (
        "rollback_latest_file_change modified file before confirmation"
    )

    action = _latest_action(db_session)
    assert action.status == "pending"
    assert action.action_type == "file"
    assert action.risk_level == "critical"

    payload = json.loads(action.payload_json)
    assert payload["action"] == "rollback_file_change", payload
    assert "backup_path" in payload, payload


def test_rollback_specific_creates_pending_action_without_modifying_file(
    db_session: Session,
) -> None:
    backup_path = _make_reversible_change()

    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="rollback_file_change",
        tool_input={"backup_path": backup_path},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, f"rollback_file_change failed: {result}"
    assert "Acción pendiente creada" in result.message, result.message

    assert _TARGET.read_text(encoding="utf-8") == "contenido modificado\n", (
        "rollback_file_change modified file before confirmation"
    )

    action = _latest_action(db_session)
    assert action.status == "pending"
    assert action.action_type == "file"

    payload = json.loads(action.payload_json)
    assert payload["action"] == "rollback_file_change", payload
    assert payload["backup_path"] == backup_path, payload


def test_rollback_file_change_rejects_unknown_backup_path(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="rollback_file_change",
        tool_input={"backup_path": "backups/no-existe-nunca.bak"},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is False, f"expected rejection of unknown backup_path, got ok=True: {result}"

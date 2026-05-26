from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.tool_executor import ToolExecutor
from app.memory.models import PendingAction
from app.tools.registry import ToolContext, dispatch_tool, has_handler

ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "trc_apply_unified_diff_registry_local_test"
TEST_PATH = "config/test-apply-unified-diff-registry-local.txt"
_TARGET = ROOT / TEST_PATH

_DIFF = f"""--- a/{TEST_PATH}
+++ b/{TEST_PATH}
@@ -1,3 +1,3 @@
 uno
-dos
+DOS
 tres
"""


def _latest_action(session: Session) -> PendingAction:
    action = session.exec(
        select(PendingAction)
        .where(PendingAction.trace_id == TRACE_ID)
        .order_by(PendingAction.created_at.desc())
    ).first()
    assert action is not None
    return action


@pytest.fixture(autouse=True)
def manage_test_file():
    _TARGET.write_text("uno\ndos\ntres\n", encoding="utf-8")
    yield
    _TARGET.unlink(missing_ok=True)


def test_apply_unified_diff_handler_registered() -> None:
    assert has_handler("apply_unified_diff"), "apply_unified_diff is not registered"


def test_apply_unified_diff_creates_pending_action(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="apply_unified_diff",
        tool_input={"diff": _DIFF},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, result
    assert "Acción pendiente creada" in result.message, result.message


def test_apply_unified_diff_does_not_modify_file_before_confirmation(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    dispatch_tool(ToolContext(
        tool_name="apply_unified_diff",
        tool_input={"diff": _DIFF},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert _TARGET.read_text(encoding="utf-8") == "uno\ndos\ntres\n", (
        "apply_unified_diff modified file before confirmation"
    )


def test_apply_unified_diff_pending_action_payload(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="apply_unified_diff",
        tool_input={"diff": _DIFF},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    action = _latest_action(db_session)
    assert action.status == "pending"
    assert action.action_type == "file"
    assert action.risk_level in {"safe", "critical"}

    payload = json.loads(action.payload_json)
    assert payload["action"] == "apply_unified_diff", payload
    assert "diff" in payload, payload
    assert "diff" in result.raw_result, result.raw_result


def test_apply_unified_diff_rejects_invalid_diff(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="apply_unified_diff",
        tool_input={"diff": "esto no es un diff válido"},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is False, f"expected rejection of invalid diff, got ok=True: {result}"

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.tool_executor import ToolExecutor
from app.memory.models import PendingAction
from app.tools.registry import ToolContext, dispatch_tool, has_handler

ROOT = Path(__file__).resolve().parents[1]
TRACE_ID = "trc_apply_multi_file_diff_registry_local_test"
TEST_A = "config/test-multi-diff-a.txt"
TEST_B = "config/test-multi-diff-b.txt"
_TARGET_A = ROOT / TEST_A
_TARGET_B = ROOT / TEST_B

_COMBINED_DIFF = f"""--- a/{TEST_A}
+++ b/{TEST_A}
@@ -1,3 +1,3 @@
 a uno
-a dos
+A DOS
 a tres
--- a/{TEST_B}
+++ b/{TEST_B}
@@ -1,3 +1,3 @@
 b uno
-b dos
+B DOS
 b tres
"""


def _pending_for_trace(session: Session) -> list[PendingAction]:
    return list(
        session.exec(
            select(PendingAction)
            .where(PendingAction.trace_id == TRACE_ID)
            .where(PendingAction.status == "pending")
            .order_by(PendingAction.created_at.asc())
        )
    )


@pytest.fixture(autouse=True)
def manage_test_files():
    _TARGET_A.write_text("a uno\na dos\na tres\n", encoding="utf-8")
    _TARGET_B.write_text("b uno\nb dos\nb tres\n", encoding="utf-8")
    yield
    _TARGET_A.unlink(missing_ok=True)
    _TARGET_B.unlink(missing_ok=True)


def test_multi_file_diff_handler_registered() -> None:
    assert has_handler("apply_multi_file_unified_diff_plan"), (
        "apply_multi_file_unified_diff_plan is not registered"
    )


def test_multi_file_diff_creates_two_pending_actions(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="apply_multi_file_unified_diff_plan",
        tool_input={"diff": _COMBINED_DIFF},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is True, result
    msg_lower = result.message.lower()
    assert "acción" in msg_lower or "acciones" in msg_lower, (
        f"Unexpected message: {result.message}"
    )

    actions = _pending_for_trace(db_session)
    assert len(actions) == 2, f"Expected 2 actions, got {len(actions)}"

    for action in actions:
        assert action.status == "pending"
        assert action.action_type == "file"
        payload = json.loads(action.payload_json)
        assert payload.get("action") == "apply_unified_diff", payload


def test_multi_file_diff_does_not_modify_files_before_confirmation(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    dispatch_tool(ToolContext(
        tool_name="apply_multi_file_unified_diff_plan",
        tool_input={"diff": _COMBINED_DIFF},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert _TARGET_A.read_text(encoding="utf-8") == "a uno\na dos\na tres\n", (
        "file A modified before confirmation"
    )
    assert _TARGET_B.read_text(encoding="utf-8") == "b uno\nb dos\nb tres\n", (
        "file B modified before confirmation"
    )


def test_multi_file_diff_rejects_invalid_diff(db_session: Session) -> None:
    executor = ToolExecutor(db_session)

    result = dispatch_tool(ToolContext(
        tool_name="apply_multi_file_unified_diff_plan",
        tool_input={"diff": "esto no es un diff válido"},
        trace_id=TRACE_ID,
        executor=executor,
    ))

    assert result.ok is False, f"expected rejection, got ok=True: {result}"

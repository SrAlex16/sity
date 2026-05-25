from __future__ import annotations

from app.actions.confirmation_manager import ConfirmationManager
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult
from app.trace.logger import write_log


@tool_handler("cancel_pending_action")
def handle_cancel_pending_action(ctx: ToolContext) -> ToolExecutionResult:
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id
    executor = ctx.executor

    action_id = str(tool_input.get("action_id", "")).strip().lower()
    reason = str(tool_input.get("reason", "")).strip()

    if not action_id:
        msg = "Falta action_id para cancelar una acción pendiente."
        result = {
            "ok": False, "message": msg,
            "local_final": True, "text": msg, "local_model": "tool-policy",
        }
        return ToolExecutionResult(
            tool_name="cancel_pending_action",
            ok=False,
            message=msg,
            updated_parameters=[],
            raw_result=result,
        )

    manager = ConfirmationManager(executor.session)
    action = manager.find_action_by_id(action_id)

    if not action or action.status != "pending":
        msg = "No encontré ninguna acción pendiente activa para cancelar."
        result = {
            "ok": False, "message": msg,
            "local_final": True, "text": msg, "local_model": "tool-policy",
        }
        return ToolExecutionResult(
            tool_name="cancel_pending_action",
            ok=False,
            message=msg,
            updated_parameters=[],
            raw_result=result,
        )

    action.status = "cancelled"
    executor.session.add(action)
    executor.session.commit()

    write_log(
        level="AUDIT",
        module="tools",
        event="pending_action_cancelled",
        trace_id=trace_id,
        payload={
            "action_id": action.id,
            "action_type": action.action_type,
            "reason": reason,
        },
        audit=True,
    )

    cancel_text = f"Acción {action.id} cancelada."
    result = {
        "ok": True,
        "message": cancel_text,
        "action_id": action.id,
        "summary": action.summary,
        "local_final": True,
        "text": cancel_text,
        "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name="cancel_pending_action",
        ok=True,
        message=cancel_text,
        updated_parameters=[],
        raw_result=result,
    )

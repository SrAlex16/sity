from __future__ import annotations

from app.actions.confirmation_manager import ConfirmationManager
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


def _handle_allowed_service_change(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    service_name = str(ctx.tool_input.get("service_name", "")).strip()

    if not service_name or not all(c.isalnum() or c in "@_.-" for c in service_name):
        msg = f"Nombre de servicio inválido: {service_name!r}"
        return ToolExecutionResult(
            tool_name=tool_name,
            ok=False,
            message=msg,
            updated_parameters=[],
            raw_result={
                "success": False,
                "message": msg,
                "local_final": True,
                "text": msg,
                "local_model": "tool-policy",
            },
        )

    verb = "Añadir" if tool_name == "add_allowed_service" else "Quitar"
    preposition = "a" if tool_name == "add_allowed_service" else "de"

    created = ConfirmationManager(ctx.executor.session).create_pending_action(
        action_type="system_config",
        risk_level="critical",
        summary=f"{verb} {service_name} {preposition} servicios permitidos",
        payload={"action": tool_name, "service_name": service_name},
        trace_id=ctx.trace_id,
    )

    local_text = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True,
        "message": local_text,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True,
        "text": local_text,
        "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=tool_name,
        ok=True,
        message=local_text,
        updated_parameters=[],
        raw_result=result,
    )


@tool_handler("add_allowed_service")
def handle_add_allowed_service(ctx: ToolContext) -> ToolExecutionResult:
    return _handle_allowed_service_change(ctx)


@tool_handler("remove_allowed_service")
def handle_remove_allowed_service(ctx: ToolContext) -> ToolExecutionResult:
    return _handle_allowed_service_change(ctx)

from __future__ import annotations

from app.actions.confirmation_manager import ConfirmationManager
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


@tool_handler("write_file")
def handle_write_file(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    path = str(tool_input.get("path", ""))
    content = str(tool_input.get("content", ""))
    create_parent_dirs = bool(tool_input.get("create_parent_dirs", False))

    from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
    try:
        assert_write_allowed(_resolve_path(path))
    except FileAccessError as exc:
        err = str(exc)
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=err,
            updated_parameters=[], raw_result={
                "success": False, "message": err,
                "local_final": True, "text": f"No puedo escribir en esa ruta: {err}", "local_model": "tool-policy",
            },
        )

    write_payload = {
        "action": "write_file",
        "path": path,
        "content": content,
        "create_parent_dirs": create_parent_dirs,
    }
    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(
        action_type="file",
        payload=write_payload,
    )
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True,
            "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "already_existed": True,
            "local_final": True,
            "text": local_text,
            "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name=tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result=result,
        )

    created = manager.create_pending_action(
        action_type="file",
        risk_level="critical",
        summary=f"Escribir archivo {path}",
        payload=write_payload,
        trace_id=trace_id,
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

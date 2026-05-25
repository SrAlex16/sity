from __future__ import annotations

from app.actions.confirmation_manager import ConfirmationManager
from app.actions.file_actions import execute_file_action
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


@tool_handler("rollback_latest_file_change")
def handle_rollback_latest_file_change(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    lookup = execute_file_action({
        "action": "find_latest_reversible_file_change",
        "include_rollbacks": bool(tool_input.get("include_rollbacks", False)),
    })

    if not lookup.get("ok"):
        msg = lookup.get("error", "No se encontró ningún cambio reversible.")
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": f"No encontré ningún cambio reversible: {msg}", "local_model": "tool-policy",
            },
        )

    event = lookup.get("event") or {}
    backup_path = str(lookup.get("backup_path", ""))
    target_path = str(event.get("path", "archivo desconocido"))
    source_action = str(event.get("action", "cambio desconocido"))
    source_trace = str(event.get("trace_id", ""))
    source_pending = str(event.get("pending_action_id", ""))

    from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
    try:
        assert_write_allowed(_resolve_path(target_path))
    except FileAccessError as exc:
        err = str(exc)
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=err,
            updated_parameters=[], raw_result={
                "success": False, "message": err,
                "local_final": True, "text": f"No puedo revertir ese archivo: {err}", "local_model": "tool-policy",
            },
        )

    rollback_payload = {
        "action": "rollback_file_change",
        "backup_path": backup_path,
    }
    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(
        action_type="file",
        payload=rollback_payload,
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
        summary=f"Revertir último cambio de archivo: {target_path}",
        payload=rollback_payload,
        trace_id=trace_id,
    )
    display_message = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Archivo: {target_path}\n"
        f"Acción original: {source_action}\n"
        f"Trace original: {source_trace}\n"
        f"Pending action original: {source_pending}\n"
        f"Backup: {backup_path}\n\n"
        "Antes de restaurar, Sity creará un backup del estado actual.\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True,
        "message": display_message,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True,
        "text": display_message,
        "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=tool_name, ok=True, message=display_message,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("rollback_file_change")
def handle_rollback_file_change(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    backup_path = str(tool_input.get("backup_path", ""))

    from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
    from app.system_agent.file_audit import find_audit_event_by_backup_path
    try:
        source_event = find_audit_event_by_backup_path(backup_path)
        if not source_event:
            msg = "No se encontró ningún evento de auditoría asociado a ese backup."
            return ToolExecutionResult(
                tool_name=tool_name, ok=False, message=msg,
                updated_parameters=[], raw_result={
                    "success": False, "message": msg,
                    "local_final": True, "text": msg, "local_model": "tool-policy",
                },
            )
        target_path = str(source_event.get("path", ""))
        assert_write_allowed(_resolve_path(target_path))
    except FileAccessError as exc:
        err = str(exc)
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=err,
            updated_parameters=[], raw_result={
                "success": False, "message": err,
                "local_final": True, "text": err, "local_model": "tool-policy",
            },
        )
    except Exception as exc:
        err = str(exc)
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=err,
            updated_parameters=[], raw_result={
                "success": False, "message": err,
                "local_final": True, "text": err, "local_model": "tool-policy",
            },
        )

    rollback_payload = {
        "action": "rollback_file_change",
        "backup_path": backup_path,
    }
    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(
        action_type="file",
        payload=rollback_payload,
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
        summary=f"Restaurar {target_path} desde backup",
        payload=rollback_payload,
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
        tool_name=tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result=result,
    )

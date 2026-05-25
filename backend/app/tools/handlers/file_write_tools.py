from __future__ import annotations

from app.actions.confirmation_manager import ConfirmationManager
from app.actions.file_actions import execute_file_action
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


@tool_handler("apply_text_patch")
def handle_apply_text_patch(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    path = str(tool_input.get("path", ""))
    old_text = str(tool_input.get("old_text", ""))
    new_text = str(tool_input.get("new_text", ""))

    from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
    try:
        assert_write_allowed(_resolve_path(path))
    except FileAccessError as exc:
        err = str(exc)
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=err,
            updated_parameters=[], raw_result={
                "success": False, "message": err,
                "local_final": True, "text": f"No puedo modificar esa ruta: {err}", "local_model": "tool-policy",
            },
        )

    preview = execute_file_action({
        "action": "preview_text_patch",
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
    })

    if not preview.get("ok"):
        msg = preview.get("error", "Error generando preview")
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": f"Error al generar el preview del patch: {msg}", "local_model": "tool-policy",
            },
        )

    diff = preview.get("diff", "")
    diff_truncated = preview.get("diff_truncated", False)
    diff_display = diff[:2000] + ("\n... diff truncado ..." if len(diff) > 2000 else "")

    patch_payload = {
        "action": "apply_text_patch",
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
    }
    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(
        action_type="file",
        payload=patch_payload,
    )
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True,
            "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "diff": diff_display,
            "diff_truncated": diff_truncated,
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
        summary=f"Modificar {path}",
        payload={
            "action": "apply_text_patch",
            "path": path,
            "old_text": old_text,
            "new_text": new_text,
        },
        trace_id=trace_id,
    )

    display_message = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )

    result = {
        "success": True,
        "message": display_message,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "diff": diff_display,
        "diff_truncated": diff_truncated,
        "local_final": True,
        "text": display_message,
        "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=tool_name, ok=True, message=display_message,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("apply_unified_diff")
def handle_apply_unified_diff(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    diff_text = str(tool_input.get("diff", ""))

    preview = execute_file_action({
        "action": "preview_unified_diff",
        "diff": diff_text,
    })

    if not preview.get("ok"):
        msg = preview.get("error", "Error generando preview de unified diff")
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": f"Error al validar el unified diff: {msg}", "local_model": "tool-policy",
            },
        )

    path = str(preview.get("path", "archivo desconocido"))
    diff_preview = str(preview.get("diff", ""))
    diff_truncated = bool(preview.get("diff_truncated", False))
    diff_display = diff_preview[:2000] + ("\n... diff truncado ..." if len(diff_preview) > 2000 else "")

    unified_payload = {
        "action": "apply_unified_diff",
        "diff": diff_text,
    }
    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(
        action_type="file",
        payload=unified_payload,
    )
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True,
            "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "diff": diff_display,
            "diff_truncated": diff_truncated,
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
        summary=f"Aplicar unified diff en {path}",
        payload=unified_payload,
        trace_id=trace_id,
    )

    display_message = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )

    result = {
        "success": True,
        "message": display_message,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "diff": diff_display,
        "diff_truncated": diff_truncated,
        "local_final": True,
        "text": display_message,
        "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=tool_name, ok=True, message=display_message,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("apply_multi_file_unified_diff_plan")
def handle_apply_multi_file_unified_diff_plan(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    diff_text = str(tool_input.get("diff", ""))

    split_result = execute_file_action({
        "action": "split_unified_diff_by_file",
        "diff": diff_text,
    })

    if not split_result.get("ok"):
        if split_result.get("rejected_entire_plan"):
            closed_text = (
                "Plan multiarchivo rechazado completo. "
                "No he creado ninguna acción pendiente ni modificado ningún archivo. "
                "Si quieres aplicar solo la parte permitida, envía un patch nuevo sin los archivos bloqueados."
            )
            return ToolExecutionResult(
                tool_name=tool_name, ok=False, message=closed_text,
                updated_parameters=[], raw_result={
                    "success": False,
                    "message": closed_text,
                    "error": split_result.get("error"),
                    "rejected_entire_plan": True,
                    "local_final": True,
                    "text": closed_text,
                    "local_model": "multi-file-plan-manager",
                },
            )

        msg = split_result.get("error", "Error separando diff multiarchivo")
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "multi-file-plan-manager",
            },
        )

    items = split_result.get("items") or []

    if not items:
        msg = "No hay cambios aplicables en el diff multiarchivo."
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "multi-file-plan-manager",
            },
        )

    manager = ConfirmationManager(ctx.executor.session)
    created_actions = []

    for item in items:
        path = str(item.get("path", "archivo desconocido"))
        file_diff = str(item.get("diff", ""))
        preview_diff = str(item.get("preview_diff", ""))
        diff_display = preview_diff[:2000] + ("\n... diff truncado ..." if len(preview_diff) > 2000 else "")

        unified_payload = {
            "action": "apply_unified_diff",
            "diff": file_diff,
        }

        existing = manager.find_equivalent_pending_action(
            action_type="file",
            payload=unified_payload,
        )

        if existing:
            created_actions.append({
                "path": path,
                "action_id": existing.id,
                "confirmation_phrase": existing.confirmation_phrase,
                "already_existed": True,
            })
            continue

        created = manager.create_pending_action(
            action_type="file",
            risk_level="critical",
            summary=f"Aplicar unified diff en {path}",
            payload=unified_payload,
            trace_id=trace_id,
        )
        created_actions.append({
            "path": path,
            "action_id": created.id,
            "confirmation_phrase": created.confirmation_phrase,
            "diff_preview": diff_display,
            "already_existed": False,
        })

    lines = [
        f"Plan multiarchivo creado: {len(created_actions)} acciones pendientes.",
        "",
    ]
    for index, entry in enumerate(created_actions, start=1):
        existed = entry.get("already_existed", False)
        lines.append(f"{index}. {entry['path']}{' (ya existía)' if existed else ''}")
        lines.append(f"   Confirma con: `{entry['confirmation_phrase']}`")

    lines += [
        "",
        "Confirma cada acción por separado.",
        "No se ha modificado ningún archivo todavía.",
    ]

    display_message = "\n".join(lines)

    result = {
        "success": True,
        "message": display_message,
        "pending_actions": created_actions,
        "local_final": True,
        "text": display_message,
        "local_model": "multi-file-plan-manager",
    }
    return ToolExecutionResult(
        tool_name=tool_name, ok=True, message=display_message,
        updated_parameters=[], raw_result=result,
    )

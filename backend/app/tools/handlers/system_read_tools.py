from __future__ import annotations

from app.tools.types import ToolExecutionResult
from app.system.system_reader import (
    list_allowed_directory,
    read_disk_usage,
    read_service_status,
    read_system_status,
    read_top_processes,
)
from app.tools.registry import ToolContext, tool_handler
from app.trace.logger import write_log


@tool_handler("read_recent_debug_events")
def handle_read_recent_debug_events(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._read_recent_debug_events(
        tool_input=ctx.tool_input,
        trace_id=ctx.trace_id,
    )


@tool_handler("read_trace_events")
def handle_read_trace_events(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._read_trace_events(
        tool_input=ctx.tool_input,
        trace_id=ctx.trace_id,
    )


@tool_handler("read_system_status")
def handle_read_system_status(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=read_system_status(),
    )


@tool_handler("read_disk_usage")
def handle_read_disk_usage(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=read_disk_usage(str(ctx.tool_input.get("path", "/"))),
    )


@tool_handler("read_processes")
def handle_read_processes(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=read_top_processes(int(ctx.tool_input.get("limit", 10))),
    )


@tool_handler("read_service_status")
def handle_read_service_status(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=read_service_status(str(ctx.tool_input.get("service_name", ""))),
    )


@tool_handler("list_allowed_directory")
def handle_list_allowed_directory(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=list_allowed_directory(str(ctx.tool_input.get("path", ""))),
    )


@tool_handler("execute_shell")
def handle_execute_shell(ctx: ToolContext) -> ToolExecutionResult:
    from app.actions.confirmation_manager import ConfirmationManager
    from app.actions.shell_actions import classify_command, execute_shell_action

    tool_name = ctx.tool_name
    command = str(ctx.tool_input.get("command", "")).strip()
    working_dir = str(ctx.tool_input.get("working_dir") or ".")
    _timeout_raw = ctx.tool_input.get("timeout")
    timeout = int(_timeout_raw) if isinstance(_timeout_raw, (int, float)) else 30

    if not command:
        msg = "El parámetro 'command' es obligatorio."
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    classification = classify_command(command)

    if classification == "blocked":
        msg = f"Comando bloqueado por política de seguridad: {command!r}"
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    if classification == "read":
        result = execute_shell_action({
            "command": command,
            "working_dir": working_dir,
            "timeout": timeout,
        })
        return ctx.executor._simple_read_tool(
            tool_name=tool_name, trace_id=ctx.trace_id, result=result,
        )

    # write — pending action (respects yolo_mode via ConfirmationManager)
    shell_payload = {
        "action": "execute_shell",
        "command": command,
        "working_dir": working_dir,
        "timeout": timeout,
    }
    manager = ConfirmationManager(ctx.executor.session, ctx.executor.session_id)
    existing = manager.find_equivalent_pending_action(action_type="shell", payload=shell_payload)
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        return ToolExecutionResult(
            tool_name=tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result={
                "success": True, "message": local_text,
                "action_id": existing.id,
                "confirmation_phrase": existing.confirmation_phrase,
                "summary": existing.summary,
                "already_existed": True,
                "local_final": True, "text": local_text, "local_model": "pending-action-manager",
            },
        )

    created = manager.create_pending_action(
        action_type="shell",
        risk_level="critical",
        summary=f"Shell: {command[:80]}",
        payload=shell_payload,
        trace_id=ctx.trace_id,
    )
    yolo = manager.build_yolo_result(created, tool_name)
    if yolo is not None:
        return yolo
    local_text = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    return ToolExecutionResult(
        tool_name=tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result={
            "success": True, "message": local_text,
            "action_id": created.id,
            "confirmation_phrase": created.confirmation_phrase,
            "summary": created.summary,
            "local_final": True, "text": local_text, "local_model": "pending-action-manager",
        },
    )


@tool_handler("set_yolo_mode")
def handle_set_yolo_mode(ctx: ToolContext) -> ToolExecutionResult:
    enabled = bool(ctx.tool_input.get("enabled", False))
    session_id = ctx.executor.session_id

    if not session_id.startswith("user:"):
        msg = "set_yolo_mode solo está disponible para usuarios autenticados."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "tool_name": ctx.tool_name,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    try:
        user_id = int(session_id.split(":", 1)[1])
        from app.memory.models import User
        user = ctx.executor.session.get(User, user_id)
        if user is None:
            msg = "Usuario no encontrado."
            return ToolExecutionResult(
                tool_name=ctx.tool_name, ok=False, message=msg,
                updated_parameters=[], raw_result={
                    "success": False, "tool_name": ctx.tool_name,
                    "local_final": True, "text": msg, "local_model": "tool-policy",
                },
            )
        user.yolo_mode = enabled
        ctx.executor.session.add(user)
        ctx.executor.session.commit()
    except Exception as exc:
        msg = f"Error actualizando yolo_mode: {exc}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "tool_name": ctx.tool_name,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    state = "activado" if enabled else "desactivado"
    text = (
        f"Modo yolo {state}. "
        + ("Las acciones pendientes se ejecutarán sin confirmación (excepto git push)."
           if enabled else
           "Las acciones pendientes volverán a pedir confirmación.")
    )
    write_log(
        level="AUDIT",
        module="system",
        event="yolo_mode_changed",
        trace_id=ctx.trace_id,
        payload={"session_id": session_id, "enabled": enabled},
        audit=True,
    )
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=text,
        updated_parameters=[], raw_result={
            "success": True, "tool_name": ctx.tool_name,
            "yolo_mode": enabled,
            "local_final": True, "text": text, "local_model": "yolo-manager",
        },
    )

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

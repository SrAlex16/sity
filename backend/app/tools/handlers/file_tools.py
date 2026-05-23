from __future__ import annotations

from app.actions.file_actions import execute_file_action
from app.core.tool_executor import ToolExecutionResult
from app.tools.registry import ToolContext, tool_handler


@tool_handler("read_file")
def handle_read_file(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    file_result = execute_file_action({
        "action": "read_file",
        "path": str(tool_input.get("path", "")),
    })
    if not file_result.get("ok"):
        error = str(file_result.get("error", "No puedo acceder a esa ruta."))
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=error,
            updated_parameters=[], raw_result={
                "success": False, "message": error,
                "tool_name": tool_name, "result": file_result,
                "local_final": True, "text": f"No puedo acceder a esa ruta: {error}", "local_model": "tool-policy",
            },
        )
    return ctx.executor._simple_read_tool(tool_name=tool_name, trace_id=trace_id, result=file_result)


@tool_handler("list_directory")
def handle_list_directory(ctx: ToolContext) -> ToolExecutionResult:
    tool_name = ctx.tool_name
    tool_input = ctx.tool_input
    trace_id = ctx.trace_id

    dir_result = execute_file_action({
        "action": "list_directory",
        "path": str(tool_input.get("path", "")),
    })
    if not dir_result.get("ok"):
        error = str(dir_result.get("error", "No puedo acceder a ese directorio."))
        return ToolExecutionResult(
            tool_name=tool_name, ok=False, message=error,
            updated_parameters=[], raw_result={
                "success": False, "message": error,
                "tool_name": tool_name, "result": dir_result,
                "local_final": True, "text": f"No puedo acceder a ese directorio: {error}", "local_model": "tool-policy",
            },
        )
    return ctx.executor._simple_read_tool(tool_name=tool_name, trace_id=trace_id, result=dir_result)

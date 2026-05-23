from __future__ import annotations

from app.actions.system_config_actions import list_allowed_services
from app.tools.types import ToolExecutionResult
from app.tools.registry import ToolContext, tool_handler


@tool_handler("list_allowed_services")
def handle_list_allowed_services(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=list_allowed_services(),
    )

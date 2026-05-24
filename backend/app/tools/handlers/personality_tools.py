from __future__ import annotations

from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


@tool_handler("update_personality_settings")
def handle_update_personality_settings(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._update_personality_settings(
        tool_input=ctx.tool_input,
        trace_id=ctx.trace_id,
    )

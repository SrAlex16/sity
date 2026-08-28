from __future__ import annotations

from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


@tool_handler("update_personality_settings")
def handle_update_personality_settings(ctx: ToolContext) -> ToolExecutionResult:
    result = ctx.executor._update_personality_settings(
        tool_input=ctx.tool_input,
        trace_id=ctx.trace_id,
    )
    if result.ok:
        from app.achievements.triggers.inline import fire as _fire_ach
        _fire_ach(ctx.executor.session, ctx.executor.session_id, "tars")
    return result

from __future__ import annotations

from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


@tool_handler("git_propose_action")
def handle_git_propose_action(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._git_propose_action(
        tool_input=ctx.tool_input,
        trace_id=ctx.trace_id,
    )


@tool_handler("system_propose_action")
def handle_system_propose_action(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._system_propose_action(
        tool_input=ctx.tool_input,
        trace_id=ctx.trace_id,
    )


def _service_propose(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._system_propose_action(
        tool_input={
            "action": ctx.tool_name,
            "service_name": str(ctx.tool_input.get("service_name", "")).strip(),
            "risk_level": "safe",
            "summary": f"{ctx.tool_name} {ctx.tool_input.get('service_name', '')}",
        },
        trace_id=ctx.trace_id,
    )


@tool_handler("start_service")
def handle_start_service(ctx: ToolContext) -> ToolExecutionResult:
    return _service_propose(ctx)


@tool_handler("stop_service")
def handle_stop_service(ctx: ToolContext) -> ToolExecutionResult:
    return _service_propose(ctx)


@tool_handler("restart_service")
def handle_restart_service(ctx: ToolContext) -> ToolExecutionResult:
    return _service_propose(ctx)

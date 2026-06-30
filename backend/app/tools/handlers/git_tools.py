from __future__ import annotations

from app.tools.types import ToolExecutionResult
from app.system.git_reader import git_branches, git_log, git_remotes, git_status
from app.tools.registry import ToolContext, tool_handler


@tool_handler("git_read_status")
def handle_git_read_status(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=git_status(str(ctx.tool_input.get("repo_path", ""))),
    )


@tool_handler("git_read_log")
def handle_git_read_log(ctx: ToolContext) -> ToolExecutionResult:
    hours_raw = ctx.tool_input.get("hours_back")
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=git_log(
            str(ctx.tool_input.get("repo_path", "")),
            int(ctx.tool_input.get("limit", 10)),
            hours_back=int(hours_raw) if hours_raw is not None else None,
        ),
    )


@tool_handler("git_read_branches")
def handle_git_read_branches(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=git_branches(str(ctx.tool_input.get("repo_path", ""))),
    )


@tool_handler("git_read_remotes")
def handle_git_read_remotes(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=git_remotes(str(ctx.tool_input.get("repo_path", ""))),
    )

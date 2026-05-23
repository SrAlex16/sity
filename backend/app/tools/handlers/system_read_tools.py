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

from __future__ import annotations

from app.actions.capture_retention_actions import execute_capture_retention_action
from app.senses.audio import list_audio_devices
from app.senses.camera import list_camera_devices
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


@tool_handler("list_camera_devices")
def handle_list_camera_devices(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=list_camera_devices(),
    )


@tool_handler("list_audio_devices")
def handle_list_audio_devices(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=list_audio_devices(),
    )


@tool_handler("get_capture_storage_summary")
def handle_get_capture_storage_summary(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=execute_capture_retention_action({"action": "get_capture_storage_summary"}),
    )


@tool_handler("clean_old_captures")
def handle_clean_old_captures(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=execute_capture_retention_action({
            "action": "clean_old_captures",
            "older_than_days": int(ctx.tool_input.get("older_than_days", 7)),
            "max_files_per_type": int(ctx.tool_input.get("max_files_per_type", 100)),
            "dry_run": bool(ctx.tool_input.get("dry_run", False)),
        }),
    )

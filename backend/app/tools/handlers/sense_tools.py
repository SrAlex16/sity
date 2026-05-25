from __future__ import annotations

from app.actions.capture_retention_actions import execute_capture_retention_action
from app.actions.sense_actions import execute_sense_action
from app.senses.audio import REAL_WEBCAM_MIC_DEVICE, list_audio_devices
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


@tool_handler("capture_camera_snapshot")
def handle_capture_camera_snapshot(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=execute_sense_action({
            "action": "capture_camera_snapshot",
            "device": str(ctx.tool_input.get("device", "/dev/video0")),
            "width": int(ctx.tool_input.get("width", 1280)),
            "height": int(ctx.tool_input.get("height", 720)),
            "skip_frames": int(ctx.tool_input.get("skip_frames", 20)),
            "client_turn_id": ctx.client_turn_id,
        }),
    )


@tool_handler("record_audio_sample")
def handle_record_audio_sample(ctx: ToolContext) -> ToolExecutionResult:
    return ctx.executor._simple_read_tool(
        tool_name=ctx.tool_name,
        trace_id=ctx.trace_id,
        result=execute_sense_action({
            "action": "record_audio_sample",
            "duration_seconds": int(ctx.tool_input.get("duration_seconds", 3)),
            "device": str(ctx.tool_input.get("device", REAL_WEBCAM_MIC_DEVICE)),
            "client_turn_id": ctx.client_turn_id,
        }),
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

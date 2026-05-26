"""Tests for tool_loop_step.run_tool_loop_step.

Uses a lightweight stub of ToolExecutor that never touches the DB or real
tools, so this test runs without a live backend.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.chat.tool_loop_step import run_tool_loop_step
from app.cortex.schemas import AIToolCall
from app.tools.types import ToolExecutionResult


def _make_tool_call(name: str = "read_file", call_id: str = "tc_001") -> AIToolCall:
    return AIToolCall(id=call_id, name=name, input={"path": "README.md"})


def _make_executor(
    raw_result: dict,
    ok_flag: bool = True,
    updated_params: list | None = None,
) -> MagicMock:
    result = ToolExecutionResult(
        tool_name="read_file",
        ok=ok_flag,
        message="ok",
        updated_parameters=updated_params or [],
        raw_result=raw_result,
    )
    executor = MagicMock()
    executor.execute_tool_call.return_value = result
    return executor


def test_local_final_early_exit() -> None:
    executor = _make_executor(
        {"local_final": True, "text": "  Hecho.  ", "local_model": "tool-policy"}
    )
    step = run_tool_loop_step(
        tool_call=_make_tool_call(),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    assert step.early_kind == "local_final"
    assert step.local_text == "Hecho."
    assert step.local_model == "tool-policy"
    assert step.tool_result_for_claude == {}
    assert step.updated_parameters == []
    assert step.artifacts == []


def test_sensor_cancelled_audio() -> None:
    executor = _make_executor({"result": {"cancelled": True}}, ok_flag=False)
    step = run_tool_loop_step(
        tool_call=_make_tool_call("record_audio_sample"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    assert step.early_kind == "sensor_cancelled"
    assert step.sensor_event_type == "audio_recording_cancelled"
    assert "cancelado" in step.sensor_description.lower()
    assert step.sensor_artifacts == []


def test_sensor_cancelled_camera() -> None:
    executor = _make_executor({"result": {"cancelled": True}}, ok_flag=False)
    step = run_tool_loop_step(
        tool_call=_make_tool_call("capture_camera_snapshot"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    assert step.early_kind == "sensor_cancelled"
    assert step.sensor_event_type == "camera_capture_cancelled"


def test_sensor_finished_no_artifact() -> None:
    executor = _make_executor({"result": {}}, ok_flag=True)
    step = run_tool_loop_step(
        tool_call=_make_tool_call("record_audio_sample"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    assert step.early_kind == "sensor_finished"
    assert step.sensor_event_type == "audio_recording_finished"
    assert step.sensor_artifacts == []


def test_normal_path_ok_with_updated_params() -> None:
    executor = _make_executor(
        {"result": {"ok": True, "content": "file content"}},
        ok_flag=True,
        updated_params=["brightness"],
    )
    step = run_tool_loop_step(
        tool_call=_make_tool_call("read_file"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    assert step.early_kind is None
    assert step.updated_parameters == ["brightness"]
    assert step.artifacts == []
    assert step.tool_result_for_claude["type"] == "tool_result"
    assert step.tool_result_for_claude["tool_use_id"] == "tc_001"


def test_normal_path_failed_clears_updated_params() -> None:
    executor = _make_executor(
        {"error": "permission denied"},
        ok_flag=False,
        updated_params=["should_be_ignored"],
    )
    step = run_tool_loop_step(
        tool_call=_make_tool_call("write_file"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    assert step.early_kind is None
    assert step.updated_parameters == []
    assert step.artifacts == []
    assert "tool_use_id" in step.tool_result_for_claude

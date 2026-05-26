"""Tests for tool_loop_runner.run_tool_loop.

Uses stub ToolExecutor and AIResponse objects — no DB, no network.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.chat.tool_loop_runner import run_tool_loop
from app.cortex.schemas import AIResponse, AIToolCall, AIUsageData
from app.tools.types import ToolExecutionResult


def _make_planner_response(*tool_names: str) -> AIResponse:
    return AIResponse(
        ok=True,
        provider="mock",
        model="mock",
        text="",
        usage=AIUsageData(input_tokens=10, output_tokens=5),
        latency_ms=100,
        tool_calls=[
            AIToolCall(id=f"tc_{i}", name=name, input={})
            for i, name in enumerate(tool_names)
        ],
    )


def _make_executor(*raw_results: tuple) -> MagicMock:
    """raw_results: sequence of (raw_result_dict, ok_flag, updated_params)."""
    side_effects = [
        ToolExecutionResult(
            tool_name="test_tool",
            ok=ok_flag,
            message="ok",
            updated_parameters=updated_params,
            raw_result=raw,
        )
        for raw, ok_flag, updated_params in raw_results
    ]
    executor = MagicMock()
    executor.execute_tool_call.side_effect = side_effects
    return executor


def test_all_normal_tools_accumulate_results() -> None:
    planner = _make_planner_response("read_file", "list_directory")
    executor = _make_executor(
        ({"result": {"content": "data"}}, True, ["p1"]),
        ({"result": {"entries": []}}, True, ["p2"]),
    )
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
    )
    assert outcome.early_kind is None
    assert len(outcome.tool_results_for_claude) == 2
    assert outcome.updated_parameters == ["p1", "p2"]
    assert outcome.artifacts == []
    assert outcome.tool_results_for_claude[0]["tool_use_id"] == "tc_0"
    assert outcome.tool_results_for_claude[1]["tool_use_id"] == "tc_1"


def test_local_final_first_tool_exits_early_without_calling_second() -> None:
    planner = _make_planner_response("cancel_pending_action", "read_file")
    executor = _make_executor(
        ({"local_final": True, "text": " Cancelada. ", "local_model": "tool-policy"}, True, []),
        ({"result": {}}, True, []),  # must not be reached
    )
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
    )
    assert outcome.early_kind == "local_final"
    assert outcome.early_tool_name == "cancel_pending_action"
    assert outcome.local_text == "Cancelada."
    assert outcome.local_model == "tool-policy"
    assert outcome.tool_results_for_claude == []
    assert executor.execute_tool_call.call_count == 1


def test_local_final_second_tool_clears_accumulated_results() -> None:
    planner = _make_planner_response("read_file", "cancel_pending_action")
    executor = _make_executor(
        ({"result": {"content": "readme"}}, True, []),
        ({"local_final": True, "text": "Acción cancelada.", "local_model": "tool-policy"}, True, []),
    )
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
    )
    assert outcome.early_kind == "local_final"
    assert outcome.early_tool_name == "cancel_pending_action"
    assert outcome.local_text == "Acción cancelada."
    assert outcome.tool_results_for_claude == []
    assert executor.execute_tool_call.call_count == 2


def test_sensor_cancelled_exits_early() -> None:
    planner = _make_planner_response("record_audio_sample")
    executor = _make_executor(({"result": {"cancelled": True}}, False, []))
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
    )
    assert outcome.early_kind == "sensor_cancelled"
    assert outcome.early_tool_name == "record_audio_sample"
    assert outcome.sensor_event_type == "audio_recording_cancelled"
    assert outcome.sensor_artifacts == []


def test_sensor_finished_exits_early() -> None:
    planner = _make_planner_response("capture_camera_snapshot")
    executor = _make_executor(({"result": {}}, True, []))
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
    )
    assert outcome.early_kind == "sensor_finished"
    assert outcome.sensor_event_type == "camera_capture_finished"
    assert (
        "completado" in outcome.sensor_description.lower()
        or "correctamente" in outcome.sensor_description.lower()
    )


def test_empty_tool_calls_produces_normal_outcome() -> None:
    planner = _make_planner_response()
    executor = _make_executor()
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
    )
    assert outcome.early_kind is None
    assert outcome.tool_results_for_claude == []
    assert outcome.updated_parameters == []
    assert outcome.artifacts == []
    assert executor.execute_tool_call.call_count == 0

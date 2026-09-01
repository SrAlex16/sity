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


def test_loop_respects_max_iterations() -> None:
    """Tool calls beyond max_iterations are silently dropped."""
    n = 5
    limit = 2
    planner = _make_planner_response(*[f"tool_{i}" for i in range(n)])
    executor = _make_executor(*[({"result": {}}, True, []) for _ in range(n)])
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
        max_iterations=limit,
    )
    assert outcome.early_kind is None
    assert executor.execute_tool_call.call_count == limit
    assert len(outcome.tool_results_for_claude) == limit


def test_loop_executes_all_when_within_limit() -> None:
    """All tool calls run when count is within max_iterations."""
    n = 3
    planner = _make_planner_response(*[f"tool_{i}" for i in range(n)])
    executor = _make_executor(*[({"result": {}}, True, []) for _ in range(n)])
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_test", client_turn_id=None,
        max_iterations=5,
    )
    assert outcome.early_kind is None
    assert executor.execute_tool_call.call_count == n
    assert len(outcome.tool_results_for_claude) == n


def test_two_parallel_web_searches_both_produce_results() -> None:
    """Regression: when the model calls 2 web_search tools in parallel,
    run_tool_loop must return 2 tool_results (not 1).

    Bug (2026-09-01): the orchestrator only detached the first web_search and
    ignored the second, so generate_with_tool_results received 1 result for 2
    tool_use blocks → Anthropic API returned 400 BadRequestError.

    Fix: _execute_tool_branch now falls through to run_tool_loop (which runs
    both tools synchronously) whenever len(tool_calls) > 1, regardless of
    the blocking policy of the first tool. run_tool_loop itself has always
    handled this correctly — this test ensures it stays correct.
    """
    planner = _make_planner_response("web_search", "web_search")
    executor = _make_executor(
        ({"text": "resultado búsqueda 1"}, True, []),
        ({"text": "resultado búsqueda 2"}, True, []),
    )
    outcome = run_tool_loop(
        planner_response=planner, executor=executor,
        trace_id="trc_parallel_search_test", client_turn_id=None,
    )

    assert outcome.early_kind is None
    assert executor.execute_tool_call.call_count == 2, (
        "Both web_search calls must be executed; one must not be silently dropped."
    )
    assert len(outcome.tool_results_for_claude) == 2, (
        "Must return 2 tool_results — one per tool_use block — or the Anthropic "
        "API will reject with 400 'tool_use ids without tool_result blocks'."
    )
    ids = {r["tool_use_id"] for r in outcome.tool_results_for_claude}
    assert ids == {"tc_0", "tc_1"}, (
        f"Both tool_use ids must appear in the results. Got: {ids}"
    )


def test_loop_handles_executor_error() -> None:
    """If executor raises, the exception propagates from run_tool_loop."""
    import pytest

    planner = _make_planner_response("read_file")
    executor = MagicMock()
    executor.execute_tool_call.side_effect = RuntimeError("executor exploded")

    with pytest.raises(RuntimeError, match="executor exploded"):
        run_tool_loop(
            planner_response=planner, executor=executor,
            trace_id="trc_test", client_turn_id=None,
        )

#!/usr/bin/env python3
"""Local tests for tool_loop_runner.run_tool_loop.

Uses stub ToolExecutor and AIResponse objects — no DB, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.chat.tool_loop_runner import run_tool_loop, ToolLoopRunOutcome  # noqa: E402
from app.cortex.schemas import AIResponse, AIToolCall, AIUsageData       # noqa: E402
from app.tools.types import ToolExecutionResult                           # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)
    ok(msg)


def make_planner_response(*tool_names: str) -> AIResponse:
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


def make_executor(*raw_results: tuple) -> MagicMock:
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_all_normal() -> None:
    print("\n==> all normal tools, accumulation")
    planner = make_planner_response("read_file", "list_directory")
    executor = make_executor(
        ({"result": {"content": "data"}}, True, ["p1"]),
        ({"result": {"entries": []}}, True, ["p2"]),
    )
    outcome = run_tool_loop(
        planner_response=planner,
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(outcome.early_kind is None, "no early exit")
    require(len(outcome.tool_results_for_claude) == 2, "two tool results accumulated")
    require(outcome.updated_parameters == ["p1", "p2"], "updated_parameters merged")
    require(outcome.artifacts == [], "no artifacts without path")
    require(outcome.tool_results_for_claude[0]["tool_use_id"] == "tc_0", "first tool_use_id")
    require(outcome.tool_results_for_claude[1]["tool_use_id"] == "tc_1", "second tool_use_id")


def test_local_final_first_tool() -> None:
    print("\n==> local_final on first tool → early exit, second tool not called")
    planner = make_planner_response("cancel_pending_action", "read_file")
    executor = make_executor(
        ({"local_final": True, "text": " Cancelada. ", "local_model": "tool-policy"}, True, []),
        ({"result": {}}, True, []),  # should never be reached
    )
    outcome = run_tool_loop(
        planner_response=planner,
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(outcome.early_kind == "local_final", "early_kind local_final")
    require(outcome.early_tool_name == "cancel_pending_action", "early_tool_name")
    require(outcome.local_text == "Cancelada.", "local_text stripped")
    require(outcome.local_model == "tool-policy", "local_model")
    require(outcome.tool_results_for_claude == [], "no claude results on early exit")
    # Verify second tool was never called
    require(executor.execute_tool_call.call_count == 1, "only one execute_tool_call")


def test_local_final_second_tool() -> None:
    print("\n==> local_final on second tool → first accumulates, then early exit")
    planner = make_planner_response("read_file", "cancel_pending_action")
    executor = make_executor(
        ({"result": {"content": "readme"}}, True, []),
        ({"local_final": True, "text": "Acción cancelada.", "local_model": "tool-policy"}, True, []),
    )
    outcome = run_tool_loop(
        planner_response=planner,
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(outcome.early_kind == "local_final", "early_kind local_final after first normal")
    require(outcome.early_tool_name == "cancel_pending_action", "early_tool_name second tool")
    require(outcome.local_text == "Acción cancelada.", "local_text")
    # Early exit clears accumulated results
    require(outcome.tool_results_for_claude == [], "accumulated cleared on early exit")
    require(executor.execute_tool_call.call_count == 2, "two calls made")


def test_sensor_cancelled() -> None:
    print("\n==> sensor_cancelled → early exit with event type")
    planner = make_planner_response("record_audio_sample")
    executor = make_executor(
        ({"result": {"cancelled": True}}, False, []),
    )
    outcome = run_tool_loop(
        planner_response=planner,
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(outcome.early_kind == "sensor_cancelled", "early_kind sensor_cancelled")
    require(outcome.early_tool_name == "record_audio_sample", "early_tool_name")
    require(outcome.sensor_event_type == "audio_recording_cancelled", "audio cancel event")
    require(outcome.sensor_artifacts == [], "no sensor artifacts on cancel")


def test_sensor_finished() -> None:
    print("\n==> sensor_finished → early exit with event type")
    planner = make_planner_response("capture_camera_snapshot")
    executor = make_executor(
        ({"result": {}}, True, []),
    )
    outcome = run_tool_loop(
        planner_response=planner,
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(outcome.early_kind == "sensor_finished", "early_kind sensor_finished")
    require(outcome.sensor_event_type == "camera_capture_finished", "camera finished event")
    require("completado" in outcome.sensor_description.lower() or
            "correctamente" in outcome.sensor_description.lower(),
            "sensor_description for finished")


def test_empty_tool_calls() -> None:
    print("\n==> empty tool_calls → normal outcome with empty accumulators")
    planner = make_planner_response()  # no tools
    executor = make_executor()
    outcome = run_tool_loop(
        planner_response=planner,
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(outcome.early_kind is None, "no early exit on empty")
    require(outcome.tool_results_for_claude == [], "empty tool results")
    require(outcome.updated_parameters == [], "empty updated_parameters")
    require(outcome.artifacts == [], "empty artifacts")
    require(executor.execute_tool_call.call_count == 0, "no calls made")


def main() -> None:
    test_all_normal()
    test_local_final_first_tool()
    test_local_final_second_tool()
    test_sensor_cancelled()
    test_sensor_finished()
    test_empty_tool_calls()
    print("\n[OK] All tool_loop_runner tests passed")


if __name__ == "__main__":
    main()

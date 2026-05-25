#!/usr/bin/env python3
"""Local tests for tool_loop_step.run_tool_loop_step.

Uses a lightweight stub of ToolExecutor that never touches the DB or real
tools, so this test runs without a live backend.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.chat.tool_loop_step import run_tool_loop_step, ToolLoopStepOutcome  # noqa: E402
from app.cortex.schemas import AIToolCall                                     # noqa: E402
from app.tools.types import ToolExecutionResult                               # noqa: E402


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


def make_tool_call(name: str = "read_file", call_id: str = "tc_001") -> AIToolCall:
    return AIToolCall(id=call_id, name=name, input={"path": "README.md"})


def make_executor(raw_result: dict, ok_flag: bool = True, updated_params: list | None = None) -> MagicMock:
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_local_final() -> None:
    print("\n==> local_final path")
    executor = make_executor({"local_final": True, "text": "  Hecho.  ", "local_model": "tool-policy"})
    step = run_tool_loop_step(
        tool_call=make_tool_call(),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(step.early_kind == "local_final", "early_kind == local_final")
    require(step.local_text == "Hecho.", "local_text stripped")
    require(step.local_model == "tool-policy", "local_model from raw_result")
    require(step.tool_result_for_claude == {}, "no tool_result_for_claude on local_final")
    require(step.updated_parameters == [], "no updated_parameters on local_final")
    require(step.artifacts == [], "no artifacts on local_final")


def test_sensor_cancelled() -> None:
    print("\n==> sensor_cancelled path (audio)")
    executor = make_executor({"result": {"cancelled": True}}, ok_flag=False)
    step = run_tool_loop_step(
        tool_call=make_tool_call("record_audio_sample"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(step.early_kind == "sensor_cancelled", "early_kind == sensor_cancelled")
    require(step.sensor_event_type == "audio_recording_cancelled", "audio event type")
    require("cancelado" in step.sensor_description.lower() or "cancelado" in step.sensor_description.lower(),
            "sensor_description mentions cancellation")
    require(step.sensor_artifacts == [], "no sensor_artifacts on cancel")


def test_sensor_cancelled_camera() -> None:
    print("\n==> sensor_cancelled path (camera)")
    executor = make_executor({"result": {"cancelled": True}}, ok_flag=False)
    step = run_tool_loop_step(
        tool_call=make_tool_call("capture_camera_snapshot"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(step.early_kind == "sensor_cancelled", "early_kind == sensor_cancelled")
    require(step.sensor_event_type == "camera_capture_cancelled", "camera event type")


def test_sensor_finished_no_path() -> None:
    print("\n==> sensor_finished path (no artifact)")
    executor = make_executor({"result": {}}, ok_flag=True)
    step = run_tool_loop_step(
        tool_call=make_tool_call("record_audio_sample"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(step.early_kind == "sensor_finished", "early_kind == sensor_finished")
    require(step.sensor_event_type == "audio_recording_finished", "audio finished event type")
    require(step.sensor_artifacts == [], "no artifact without path")


def test_normal_path_ok() -> None:
    print("\n==> normal path (ok, updated_parameters)")
    executor = make_executor(
        {"result": {"ok": True, "content": "file content"}},
        ok_flag=True,
        updated_params=["brightness"],
    )
    step = run_tool_loop_step(
        tool_call=make_tool_call("read_file"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(step.early_kind is None, "early_kind is None on normal path")
    require(step.updated_parameters == ["brightness"], "updated_parameters forwarded")
    require(step.artifacts == [], "no artifact without inner path")
    require(step.tool_result_for_claude["type"] == "tool_result", "tool_result_for_claude type")
    require(step.tool_result_for_claude["tool_use_id"] == "tc_001", "tool_use_id preserved")


def test_normal_path_failed() -> None:
    print("\n==> normal path (failed, no updated_parameters)")
    executor = make_executor(
        {"error": "permission denied"},
        ok_flag=False,
        updated_params=["should_be_ignored"],
    )
    step = run_tool_loop_step(
        tool_call=make_tool_call("write_file"),
        executor=executor,
        trace_id="trc_test",
        client_turn_id=None,
    )
    require(step.early_kind is None, "early_kind is None on failed normal path")
    require(step.updated_parameters == [], "updated_parameters empty when result.ok=False")
    require(step.artifacts == [], "no artifacts when result.ok=False")
    require("tool_use_id" in step.tool_result_for_claude, "tool_result_for_claude still built")


def main() -> None:
    test_local_final()
    test_sensor_cancelled()
    test_sensor_cancelled_camera()
    test_sensor_finished_no_path()
    test_normal_path_ok()
    test_normal_path_failed()
    print("\n[OK] All tool_loop_step tests passed")


if __name__ == "__main__":
    main()

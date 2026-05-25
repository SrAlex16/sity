"""
tool_loop_step.py — normalises the result of one tool-call iteration.

Calls ToolExecutor, parses raw_result and detects the three early-return
conditions (local_final, sensor cancelled, sensor finished).  Returns a
ToolLoopStepOutcome that routes_chat.py can branch on without the step
function needing access to the session, gateway, or budget parameters.

Side-effect-free except for what ToolExecutor does internally (pending
action writes, sensor I/O, etc.).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.api.schemas import ChatArtifact
from app.chat.artifacts import capture_artifact_from_path
from app.core.tool_executor import ToolExecutor
from app.cortex.schemas import AIToolCall


_SENSOR_TOOLS: frozenset[str] = frozenset({"record_audio_sample", "capture_camera_snapshot"})


@dataclass
class ToolLoopStepOutcome:
    """Normalised result of executing one tool call inside the planner loop.

    ``early_kind`` signals that routes_chat.py should build a response and
    return immediately; ``None`` means continue normal accumulation.

    Values for early_kind:
      "local_final"       — registry handler returned a final text; no AI round-trip needed.
      "sensor_cancelled"  — sensor was cancelled by the user.
      "sensor_finished"   — sensor completed; artifacts (if any) are in sensor_artifacts.
    """

    early_kind: str | None  # None | "local_final" | "sensor_cancelled" | "sensor_finished"

    # ---- local_final (only when early_kind == "local_final") ----
    local_text: str
    local_model: str

    # ---- sensor (only when early_kind in {"sensor_cancelled", "sensor_finished"}) ----
    sensor_event_type: str   # e.g. "audio_recording_finished"
    sensor_description: str  # natural-language description for generate_micro_reaction
    sensor_artifacts: list[ChatArtifact]

    # ---- normal-path accumulation (always populated on early_kind=None) ----
    tool_result_for_claude: dict[str, Any]
    updated_parameters: list[str]
    artifacts: list[ChatArtifact]


def run_tool_loop_step(
    *,
    tool_call: AIToolCall,
    executor: ToolExecutor,
    trace_id: str,
    client_turn_id: str | None,
) -> ToolLoopStepOutcome:
    """Execute one tool call and return a normalised outcome."""
    result = executor.execute_tool_call(
        tool_name=tool_call.name,
        tool_input=tool_call.input,
        trace_id=trace_id,
        client_turn_id=client_turn_id,
    )

    raw = result.raw_result

    # ------------------------------------------------------------------ #
    # local_final: registry handler produced a final text without AI      #
    # ------------------------------------------------------------------ #
    if raw.get("local_final") and raw.get("text"):
        return ToolLoopStepOutcome(
            early_kind="local_final",
            local_text=str(raw["text"]).strip(),
            local_model=str(raw.get("local_model", "tool-result")),
            sensor_event_type="",
            sensor_description="",
            sensor_artifacts=[],
            tool_result_for_claude={},
            updated_parameters=[],
            artifacts=[],
        )

    # ------------------------------------------------------------------ #
    # Sensor paths: cancelled or successfully finished                    #
    # ------------------------------------------------------------------ #
    tool_name = tool_call.name
    is_sensor = tool_name in _SENSOR_TOOLS
    inner = raw.get("result", {})

    if is_sensor and inner.get("cancelled"):
        event_type = (
            "audio_recording_cancelled" if "audio" in tool_name else "camera_capture_cancelled"
        )
        return ToolLoopStepOutcome(
            early_kind="sensor_cancelled",
            local_text="",
            local_model="",
            sensor_event_type=event_type,
            sensor_description="El usuario ha cancelado voluntariamente la operación.",
            sensor_artifacts=[],
            tool_result_for_claude={},
            updated_parameters=[],
            artifacts=[],
        )

    if result.ok and is_sensor:
        event_type = (
            "audio_recording_finished" if "audio" in tool_name else "camera_capture_finished"
        )
        sensor_artifacts: list[ChatArtifact] = []
        raw_path = inner.get("path")
        if raw_path:
            artifact = capture_artifact_from_path(str(raw_path))
            if artifact:
                sensor_artifacts.append(artifact)
        return ToolLoopStepOutcome(
            early_kind="sensor_finished",
            local_text="",
            local_model="",
            sensor_event_type=event_type,
            sensor_description="La operación de sensor ha completado correctamente.",
            sensor_artifacts=sensor_artifacts,
            tool_result_for_claude={},
            updated_parameters=[],
            artifacts=[],
        )

    # ------------------------------------------------------------------ #
    # Normal path: accumulate for AI round-trip                           #
    # ------------------------------------------------------------------ #
    updated_parameters: list[str] = list(result.updated_parameters) if result.ok else []
    artifacts: list[ChatArtifact] = []
    if result.ok:
        raw_path = inner.get("path")
        if raw_path:
            artifact = capture_artifact_from_path(str(raw_path))
            if artifact:
                artifacts.append(artifact)

    return ToolLoopStepOutcome(
        early_kind=None,
        local_text="",
        local_model="",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_result_for_claude={
            "type": "tool_result",
            "tool_use_id": tool_call.id,
            "content": json.dumps(raw, ensure_ascii=False),
        },
        updated_parameters=updated_parameters,
        artifacts=artifacts,
    )

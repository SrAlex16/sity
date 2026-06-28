"""
tool_loop_runner.py — iterates all tool calls in a planner response.

Wraps run_tool_loop_step into a single call that accumulates the normal-path
results or returns an early-exit signal the first time a step asks for one.

Does NOT touch: session, gateway, personality, budget, logging, or saving
messages.  All of those stay in routes_chat.py so it keeps full control over
side-effects and response construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.api.schemas import ChatArtifact
from app.chat.tool_loop_step import run_tool_loop_step
from app.core.tool_executor import ToolExecutor
from app.cortex.schemas import AIResponse


@dataclass
class ToolLoopRunOutcome:
    """Aggregated result of running all tool calls in the planner loop.

    ``early_kind`` is None when every step accumulated normally; non-None
    when iteration stopped at the first early-exit step.

    Consumers should check ``early_kind`` first:
      "local_final"      → use local_text / local_model to build a response
      "sensor_cancelled" → generate a micro-reaction with no artifacts
      "sensor_finished"  → generate a micro-reaction with sensor_artifacts
      None               → use tool_results_for_claude / updated_parameters / artifacts
    """

    early_kind: str | None  # None | "local_final" | "sensor_cancelled" | "sensor_finished"
    early_tool_name: str    # tool_call.name that triggered the early exit (for logs)

    # local_final
    local_text: str
    local_model: str

    # sensor
    sensor_event_type: str
    sensor_description: str
    sensor_artifacts: list[ChatArtifact]

    # normal accumulation (populated only when early_kind is None)
    tool_results_for_claude: list[dict[str, Any]]
    updated_parameters: list[str]
    artifacts: list[ChatArtifact]


_DEFAULT_MAX_ITERATIONS = 3


def run_tool_loop(
    *,
    planner_response: AIResponse,
    executor: ToolExecutor,
    trace_id: str,
    client_turn_id: str | None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> ToolLoopRunOutcome:
    """Run every tool call in planner_response and return a ToolLoopRunOutcome."""
    tool_results_for_claude: list[dict[str, Any]] = []
    updated_parameters: list[str] = []
    artifacts: list[ChatArtifact] = []

    for tool_call in planner_response.tool_calls[:max_iterations]:
        step = run_tool_loop_step(
            tool_call=tool_call,
            executor=executor,
            trace_id=trace_id,
            client_turn_id=client_turn_id,
        )

        if step.early_kind is not None:
            return ToolLoopRunOutcome(
                early_kind=step.early_kind,
                early_tool_name=tool_call.name,
                local_text=step.local_text,
                local_model=step.local_model,
                sensor_event_type=step.sensor_event_type,
                sensor_description=step.sensor_description,
                sensor_artifacts=step.sensor_artifacts,
                tool_results_for_claude=[],
                updated_parameters=[],
                artifacts=[],
            )

        # Normal path: accumulate
        tool_results_for_claude.append(step.tool_result_for_claude)
        updated_parameters.extend(step.updated_parameters)
        artifacts.extend(step.artifacts)

    return ToolLoopRunOutcome(
        early_kind=None,
        early_tool_name="",
        local_text="",
        local_model="",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_results_for_claude=tool_results_for_claude,
        updated_parameters=updated_parameters,
        artifacts=artifacts,
    )

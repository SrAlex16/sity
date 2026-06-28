"""Unit tests for three tool-loop edge cases that require hardware or deep
mocking and cannot be exercised by the integration shell script:

  1. run_micro_reaction — ProviderCallRunner bridges to generate_micro_reaction
  2. sensor_finished   — run_tool_loop propagates sensor_artifacts on early exit
  3. normal artifacts  — run_tool_loop accumulates artifacts on the normal path
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.schemas import ChatArtifact
from app.chat.provider_call_runner import ProviderCallRunner
from app.chat.tool_loop_runner import run_tool_loop
from app.chat.tool_loop_step import ToolLoopStepOutcome


# ---------------------------------------------------------------------------
# 1. micro_reaction
# ---------------------------------------------------------------------------

def test_run_micro_reaction_returns_text() -> None:
    mock_provider = MagicMock()
    mock_provider.generate_micro_reaction.return_value = {
        "text": "Entendido, cancelado.",
        "input_tokens": 10,
        "output_tokens": 5,
    }
    mock_gateway = MagicMock()
    mock_gateway.provider = mock_provider

    runner = ProviderCallRunner(gateway=mock_gateway)
    result = runner.run_micro_reaction(
        event_type="sensor_cancelled",
        event_description="El usuario canceló la captura",
        personality={"warmth_level": 0.8},
        trace_id="trc_test",
    )

    assert result == "Entendido, cancelado."
    mock_provider.generate_micro_reaction.assert_called_once()


def test_run_micro_reaction_empty_text_uses_fallback() -> None:
    """When the provider returns empty text, generate_micro_reaction falls back
    to a non-empty hardcoded string instead of returning empty."""
    mock_provider = MagicMock()
    mock_provider.generate_micro_reaction.return_value = {
        "text": "",
        "input_tokens": 5,
        "output_tokens": 0,
    }
    mock_gateway = MagicMock()
    mock_gateway.provider = mock_provider

    runner = ProviderCallRunner(gateway=mock_gateway)
    result = runner.run_micro_reaction(
        event_type="audio_recording_cancelled",
        event_description="",
        personality=None,
        trace_id=None,
    )

    assert isinstance(result, str)
    assert result  # non-empty fallback


# ---------------------------------------------------------------------------
# 2. sensor_finished — sensor_artifacts propagated through run_tool_loop
# ---------------------------------------------------------------------------

def test_tool_loop_sensor_finished_propagates_artifacts() -> None:
    artifact = ChatArtifact(
        type="image",
        url="/captures/test.jpg",
        filename="test.jpg",
        mime_type="image/jpeg",
    )

    sensor_step = ToolLoopStepOutcome(
        early_kind="sensor_finished",
        local_text="",
        local_model="",
        sensor_event_type="camera_capture_finished",
        sensor_description="Imagen capturada",
        sensor_artifacts=[artifact],
        tool_result_for_claude={},
        updated_parameters=[],
        artifacts=[],
    )

    mock_tool_call = MagicMock()
    mock_tool_call.name = "capture_camera_snapshot"
    mock_planner = MagicMock()
    mock_planner.tool_calls = [mock_tool_call]

    with patch("app.chat.tool_loop_runner.run_tool_loop_step", return_value=sensor_step):
        outcome = run_tool_loop(
            planner_response=mock_planner,
            executor=MagicMock(),
            trace_id="trc_test",
            client_turn_id=None,
        )

    assert outcome.early_kind == "sensor_finished"
    assert len(outcome.sensor_artifacts) == 1
    assert outcome.sensor_artifacts[0].filename == "test.jpg"
    assert outcome.artifacts == []  # normal artifacts not populated on early exit


# ---------------------------------------------------------------------------
# 3. normal artifacts — accumulated on the non-early path
# ---------------------------------------------------------------------------

def test_tool_loop_accumulates_normal_artifacts() -> None:
    artifact = ChatArtifact(
        type="audio",
        url="/audio/response.wav",
        filename="response.wav",
        mime_type="audio/wav",
    )

    normal_step = ToolLoopStepOutcome(
        early_kind=None,
        local_text="",
        local_model="",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_result_for_claude={"type": "tool_result", "content": "ok"},
        updated_parameters=[],
        artifacts=[artifact],
    )

    mock_tool_call = MagicMock()
    mock_planner = MagicMock()
    mock_planner.tool_calls = [mock_tool_call]

    with patch("app.chat.tool_loop_runner.run_tool_loop_step", return_value=normal_step):
        outcome = run_tool_loop(
            planner_response=mock_planner,
            executor=MagicMock(),
            trace_id="trc_test",
            client_turn_id=None,
        )

    assert outcome.early_kind is None
    assert outcome.artifacts == [artifact]
    assert outcome.sensor_artifacts == []

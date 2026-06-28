"""Tests for ChatAIOrchestrator.run() paths.

All external I/O (DB, network, TTS) is mocked. Tests verify which runner
methods are called and what is returned for each routing/planner branch.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.api.schemas import ChatMessageRequest, ChatMessageResponse
from app.chat.ai_orchestrator import ChatAIOrchestrator
from app.chat.ai_turn_prep import AITurnPrep
from app.chat.routing_decision import ChatRoutingDecision, ProviderMode
from app.chat.turn_context import TurnContext
from app.core.persona_engine import PersonaDecision
from app.cortex.schemas import AIResponse, AIToolCall, AIUsageData


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _persona_decision() -> PersonaDecision:
    return PersonaDecision(
        system_prompt="sys",
        refusal_mode=False,
        tone_snapshot={"mood": "neutral"},
    )


def _ai_response(*, text: str = "respuesta", tool_calls: list | None = None) -> AIResponse:
    return AIResponse(
        ok=True,
        provider="mock",
        model="mock-model",
        text=text,
        usage=AIUsageData(input_tokens=10, output_tokens=5),
        latency_ms=50,
        tool_calls=tool_calls or [],
    )


def _make_runner(
    *,
    chat_response: AIResponse | None = None,
    planner_response: AIResponse | None = None,
    local_chat_response: AIResponse | None = None,
    after_tools_response: AIResponse | None = None,
    micro_reaction_text: str = "reacción",
) -> MagicMock:
    runner = MagicMock()
    runner.run_chat.return_value = chat_response or _ai_response()
    runner.run_planner.return_value = planner_response or _ai_response()
    runner.run_local_chat.return_value = local_chat_response or _ai_response()
    runner.run_after_tools.return_value = after_tools_response or _ai_response()
    runner.run_micro_reaction.return_value = micro_reaction_text
    runner._gateway.provider.model = "mock-model"
    return runner


def _make_prompt_context(
    *,
    user_message_with_history: str = "¿qué hora es?",
    planner_user_message: str = "¿qué hora es?",
    prior_messages: list | None = None,
    planner_prior_messages: list | None = None,
) -> MagicMock:
    pc = MagicMock()
    pc.user_message_with_history = user_message_with_history
    pc.planner_user_message = planner_user_message
    pc.prior_messages = prior_messages or []
    pc.planner_prior_messages = planner_prior_messages or []
    return pc


def _make_prep(
    *,
    runner: MagicMock,
    provider_mode: ProviderMode = ProviderMode.cloud_chat,
    selected_tools: list | None = None,
    prompt_context: MagicMock | None = None,
) -> MagicMock:
    prep = MagicMock(spec=AITurnPrep)
    prep.runner = runner
    prep.selected_tools = selected_tools or []
    prep.output_mode = "text"
    prep.should_synth = False
    prep.voice_settings = MagicMock()
    prep.prompt_context = prompt_context or _make_prompt_context()
    routing = MagicMock(spec=ChatRoutingDecision)
    routing.provider_mode = provider_mode
    prep.routing_decision = routing
    prep.persona_decision = _persona_decision()
    return prep


def _make_ctx(*, ai_config: dict | None = None) -> MagicMock:
    ctx = MagicMock(spec=TurnContext)
    ctx.trace_id = "trc_test"
    ctx.personality = {"verbosity_level": 0.5}
    ctx.max_tokens = 1500
    ctx.daily_budget = 1_000_000
    ctx.warning_threshold = 0.80
    ctx.critical_threshold = 0.95
    ctx.ai_config = ai_config or {"claude": {"strong_model": "claude-sonnet-4-6"}}
    ctx.voice_settings = MagicMock()
    persistence = MagicMock()
    persistence.save = MagicMock()
    persistence.tag_sity_with_model = MagicMock()
    ctx.persistence = persistence
    ctx.settings_service = MagicMock()
    ctx.settings_service.get_personality.return_value = {"verbosity_level": 0.5}
    return ctx


def _make_request(message: str = "hola") -> ChatMessageRequest:
    return ChatMessageRequest(
        message=message,
        history=[],
        input_mode="text",
        client_turn_id=None,
        source_channel="web",
    )


def _make_orchestrator(
    *,
    runner: MagicMock | None = None,
    provider_mode: ProviderMode = ProviderMode.cloud_chat,
    ctx: MagicMock | None = None,
    request: ChatMessageRequest | None = None,
    planner_response: AIResponse | None = None,
    ai_config: dict | None = None,
) -> ChatAIOrchestrator:
    _runner = runner or _make_runner(planner_response=planner_response)
    _ctx = ctx or _make_ctx(ai_config=ai_config)
    prep = _make_prep(runner=_runner, provider_mode=provider_mode)
    return ChatAIOrchestrator(
        session=MagicMock(),
        ctx=_ctx,
        prep=prep,
        request=request or _make_request(),
        persona_prompt="sys",
        persona_decision=_persona_decision(),
    )


# ---------------------------------------------------------------------------
# Helpers for patching at the orchestrator module level
# ---------------------------------------------------------------------------

_MODULE = "app.chat.ai_orchestrator"


# ---------------------------------------------------------------------------
# Test 1: local_chat path
# ---------------------------------------------------------------------------

def test_orchestrator_local_chat_path() -> None:
    """Cuando routing_decision es local_chat_candidate, llama a run_local_chat."""
    runner = _make_runner()
    orc = _make_orchestrator(runner=runner, provider_mode=ProviderMode.local_chat_candidate)

    final_response = MagicMock(spec=ChatMessageResponse)
    final_response.ok = True
    final_response.text = "local text"

    with patch(f"{_MODULE}.build_final_ai_response", return_value=final_response), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_local_persona_prompt.return_value = "local sys"
        result = orc.run()

    runner.run_local_chat.assert_called_once()
    runner.run_planner.assert_not_called()
    assert result is final_response


# ---------------------------------------------------------------------------
# Test 2: no_action_required → run_chat
# ---------------------------------------------------------------------------

def test_orchestrator_no_action_required_calls_run_chat() -> None:
    """Cuando planner devuelve no_action_required, llama a run_chat directamente."""
    planner_resp = _ai_response(
        tool_calls=[AIToolCall(id="tc_0", name="no_action_required", input={})]
    )
    runner = _make_runner(planner_response=planner_resp)
    orc = _make_orchestrator(runner=runner, provider_mode=ProviderMode.cloud_tools)

    final_response = MagicMock(spec=ChatMessageResponse)
    final_response.ok = True
    final_response.text = "texto sin herramienta"

    with patch(f"{_MODULE}.build_final_ai_response", return_value=final_response), \
         patch(f"{_MODULE}.has_narrated_search", return_value=False), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0):
        result = orc.run()

    runner.run_chat.assert_called_once()
    assert result is final_response


# ---------------------------------------------------------------------------
# Test 3: tool loop normal → run_after_tools
# ---------------------------------------------------------------------------

def test_orchestrator_tool_loop_calls_after_tools() -> None:
    """Cuando el tool loop devuelve tool_results, llama a run_after_tools."""
    tool_call = AIToolCall(id="tc_real", name="read_file", input={"path": "/tmp/f"})
    planner_resp = _ai_response(tool_calls=[tool_call])
    after_resp = _ai_response(text="resultado tras tools")
    runner = _make_runner(planner_response=planner_resp, after_tools_response=after_resp)
    orc = _make_orchestrator(runner=runner, provider_mode=ProviderMode.cloud_tools)

    from app.chat.tool_loop_runner import ToolLoopRunOutcome

    fake_loop = ToolLoopRunOutcome(
        early_kind=None,
        early_tool_name="",
        local_text="",
        local_model="",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_results_for_claude=[{"type": "tool_result", "tool_use_id": "tc_real", "content": "data"}],
        updated_parameters=[],
        artifacts=[],
    )

    final_response = MagicMock(spec=ChatMessageResponse)
    final_response.ok = True
    final_response.text = "resultado tras tools"

    with patch(f"{_MODULE}.run_tool_loop", return_value=fake_loop), \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final_response), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_persona_prompt.return_value = _persona_decision()
        result = orc.run()

    runner.run_after_tools.assert_called_once()
    assert result is final_response


# ---------------------------------------------------------------------------
# Test 4: local_final → no run_after_tools
# ---------------------------------------------------------------------------

def test_orchestrator_local_final_returns_without_after_tools() -> None:
    """Cuando tool loop devuelve early_kind=local_final, no llama a run_after_tools."""
    tool_call = AIToolCall(id="tc_lf", name="write_file", input={})
    planner_resp = _ai_response(tool_calls=[tool_call])
    runner = _make_runner(planner_response=planner_resp)
    orc = _make_orchestrator(runner=runner, provider_mode=ProviderMode.cloud_tools)

    from app.chat.tool_loop_runner import ToolLoopRunOutcome

    fake_loop = ToolLoopRunOutcome(
        early_kind="local_final",
        early_tool_name="write_file",
        local_text="Archivo guardado.",
        local_model="local-final",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_results_for_claude=[],
        updated_parameters=[],
        artifacts=[],
    )

    with patch(f"{_MODULE}.run_tool_loop", return_value=fake_loop), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.build_budget_snapshot") as mock_snap:
        mock_snap.return_value = MagicMock(daily_used=0, daily_budget=1_000_000,
                                           daily_ratio=0.0, warnings=[])
        result = orc.run()

    runner.run_after_tools.assert_not_called()
    assert isinstance(result, ChatMessageResponse)
    assert result.ok is True


# ---------------------------------------------------------------------------
# Test 5: sensor_finished → run_micro_reaction
# ---------------------------------------------------------------------------

def test_orchestrator_sensor_finished_calls_micro_reaction() -> None:
    """Cuando tool loop devuelve sensor_finished, llama a run_micro_reaction."""
    tool_call = AIToolCall(id="tc_cam", name="take_photo", input={})
    planner_resp = _ai_response(tool_calls=[tool_call])
    runner = _make_runner(planner_response=planner_resp, micro_reaction_text="¡foto tomada!")
    orc = _make_orchestrator(runner=runner, provider_mode=ProviderMode.cloud_tools)

    from app.chat.tool_loop_runner import ToolLoopRunOutcome

    fake_loop = ToolLoopRunOutcome(
        early_kind="sensor_finished",
        early_tool_name="take_photo",
        local_text="",
        local_model="",
        sensor_event_type="photo_taken",
        sensor_description="foto tomada correctamente",
        sensor_artifacts=[],
        tool_results_for_claude=[],
        updated_parameters=[],
        artifacts=[],
    )

    with patch(f"{_MODULE}.run_tool_loop", return_value=fake_loop), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0):
        result = orc.run()

    runner.run_micro_reaction.assert_called_once()
    assert isinstance(result, ChatMessageResponse)
    assert result.ok is True


# ---------------------------------------------------------------------------
# Test 6: propose_model_upgrade → set_proposal
# ---------------------------------------------------------------------------

def test_orchestrator_model_upgrade_proposed_saves_proposal() -> None:
    """Cuando planner devuelve propose_model_upgrade, guarda la propuesta."""
    tool_call = AIToolCall(
        id="tc_up",
        name="propose_model_upgrade",
        input={"reason": "tarea compleja"},
    )
    planner_resp = _ai_response(tool_calls=[tool_call])
    runner = _make_runner(planner_response=planner_resp)
    orc = _make_orchestrator(runner=runner, provider_mode=ProviderMode.cloud_tools)

    with patch(f"{_MODULE}.set_proposal") as mock_set_proposal, \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.build_budget_snapshot") as mock_snap:
        mock_snap.return_value = MagicMock(daily_used=0, daily_budget=1_000_000,
                                           daily_ratio=0.0, warnings=[])
        result = orc.run()

    mock_set_proposal.assert_called_once()
    call_arg = mock_set_proposal.call_args[0][0]
    from app.chat.model_router import ModelUpgradeProposal
    assert isinstance(call_arg, ModelUpgradeProposal)
    assert call_arg.reason == "tarea compleja"
    assert isinstance(result, ChatMessageResponse)
    assert result.ok is True

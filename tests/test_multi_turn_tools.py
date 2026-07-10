"""Validation tests for the multi-turn tool-calling loop (Cases A–F).

All tools are generic mocks — no Spotify, Calendar, or domain-specific
names — to verify that the mechanism is fully generic and works for any
tool combination, present or future.

The loop in ai_orchestrator.py is exercised via its public AIRequest/
AIResponse/runner interfaces so no real DB or network calls are made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from app.api.schemas import ChatMessageRequest, ChatMessageResponse
from app.chat.ai_orchestrator import ChatAIOrchestrator
from app.chat.ai_turn_prep import AITurnPrep
from app.chat.routing_decision import ChatRoutingDecision, ProviderMode
from app.chat.tool_loop_runner import ToolLoopRunOutcome
from app.chat.turn_context import TurnContext
from app.core.persona_engine import PersonaDecision
from app.cortex.schemas import AIResponse, AIToolCall, AIUsageData


_MODULE = "app.chat.ai_orchestrator"


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------

def _persona() -> PersonaDecision:
    return PersonaDecision(
        system_prompt="sys",
        refusal_mode=False,
        tone_snapshot={"mood": "neutral"},
    )


def _ai_resp(*, text: str = "", tool_calls: list | None = None) -> AIResponse:
    return AIResponse(
        ok=True, provider="mock", model="mock",
        text=text,
        usage=AIUsageData(input_tokens=10, output_tokens=5),
        latency_ms=50,
        tool_calls=tool_calls or [],
    )


def _loop_outcome(
    *,
    tool_results: list | None = None,
    early_kind: str | None = None,
    local_text: str = "",
    local_model: str = "",
    sensor_event_type: str = "",
    sensor_description: str = "",
) -> ToolLoopRunOutcome:
    return ToolLoopRunOutcome(
        early_kind=early_kind,
        early_tool_name="mock_tool",
        local_text=local_text,
        local_model=local_model,
        sensor_event_type=sensor_event_type,
        sensor_description=sensor_description,
        sensor_artifacts=[],
        tool_results_for_claude=tool_results or [],
        updated_parameters=[],
        artifacts=[],
    )


def _make_runner(
    *,
    planner_response: AIResponse | None = None,
    after_tools_responses: list[AIResponse] | None = None,
) -> MagicMock:
    runner = MagicMock()
    runner.run_planner.return_value = planner_response or _ai_resp()
    runner._gateway.provider.model = "mock"
    if after_tools_responses:
        runner.run_after_tools.side_effect = after_tools_responses
    else:
        runner.run_after_tools.return_value = _ai_resp(text="done")
    runner.run_micro_reaction.return_value = "reaccion"
    return runner


def _make_ctx(*, ai_config: dict | None = None) -> MagicMock:
    ctx = MagicMock(spec=TurnContext)
    ctx.trace_id = "trc_test"
    ctx.personality = {"verbosity_level": 0.5}
    ctx.max_tokens = 1500
    ctx.daily_budget = 1_000_000
    ctx.warning_threshold = 0.80
    ctx.critical_threshold = 0.95
    ctx.ai_config = ai_config or {"claude": {"strong_model": "claude-sonnet-4-6"}}
    persistence = MagicMock()
    persistence.save = MagicMock()
    persistence.tag_sity_with_model = MagicMock()
    ctx.persistence = persistence
    ctx.settings_service = MagicMock()
    ctx.settings_service.get_personality.return_value = {"verbosity_level": 0.5}
    return ctx


def _make_orc(
    *,
    runner: MagicMock,
    ctx: MagicMock | None = None,
    ai_config: dict | None = None,
) -> ChatAIOrchestrator:
    _ctx = ctx or _make_ctx(ai_config=ai_config)
    prep = MagicMock(spec=AITurnPrep)
    prep.runner = runner
    prep.selected_tools = []
    prep.output_mode = "text"
    prep.should_synth = False
    prep.voice_settings = MagicMock()
    prep.prompt_context = MagicMock()
    prep.prompt_context.user_message_with_history = "msg"
    prep.prompt_context.planner_user_message = "msg"
    prep.prompt_context.prior_messages = []
    prep.prompt_context.planner_prior_messages = []
    routing = MagicMock(spec=ChatRoutingDecision)
    routing.provider_mode = ProviderMode.cloud_tools
    prep.routing_decision = routing
    prep.persona_decision = _persona()
    return ChatAIOrchestrator(
        session=MagicMock(),
        ctx=_ctx,
        prep=prep,
        request=ChatMessageRequest(
            message="msg", history=[], input_mode="text",
            client_turn_id=None, source_channel="web",
        ),
        persona_prompt="sys",
        persona_decision=_persona(),
    )


# ---------------------------------------------------------------------------
# Case A — two-step chain resolves correctly
#
# Planner → mock_list → after-tools wants mock_act → mock_act runs →
# after-tools says "Done". run_after_tools called twice.
# ---------------------------------------------------------------------------

def test_case_a_two_step_chain_resolves() -> None:
    planner_resp = _ai_resp(
        tool_calls=[AIToolCall(id="tc0", name="mock_list", input={})]
    )
    runner = _make_runner(
        planner_response=planner_resp,
        after_tools_responses=[
            # round 0: wants to chain mock_act
            _ai_resp(tool_calls=[AIToolCall(id="tc1", name="mock_act", input={})]),
            # round 1: done
            _ai_resp(text="Done, action performed."),
        ],
    )
    orc = _make_orc(runner=runner)

    round0_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc0", "content": "items"}],
    )
    round1_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc1", "content": "ok"}],
    )

    final = MagicMock(spec=ChatMessageResponse)
    final.ok = True
    final.text = "Done, action performed."

    with patch(f"{_MODULE}.run_tool_loop", side_effect=[round0_loop, round1_loop]), \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_persona_prompt.return_value = _persona()
        result = orc.run()

    assert runner.run_after_tools.call_count == 2
    assert result is final


# ---------------------------------------------------------------------------
# Case B — single tool, no chain (no regression)
#
# Planner → mock_query → after-tools returns text, no tool_calls.
# run_after_tools called exactly once.
# ---------------------------------------------------------------------------

def test_case_b_single_tool_no_chain() -> None:
    planner_resp = _ai_resp(
        tool_calls=[AIToolCall(id="tc0", name="mock_query", input={})]
    )
    runner = _make_runner(
        planner_response=planner_resp,
        after_tools_responses=[_ai_resp(text="Here are the results.")],
    )
    orc = _make_orc(runner=runner)

    fake_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc0", "content": "data"}],
    )
    final = MagicMock(spec=ChatMessageResponse)
    final.ok = True

    with patch(f"{_MODULE}.run_tool_loop", return_value=fake_loop), \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_persona_prompt.return_value = _persona()
        orc.run()

    runner.run_after_tools.assert_called_once()


# ---------------------------------------------------------------------------
# Case C — local_final in intermediate round stops the loop
#
# Round 0: mock_read runs normally. After-tools wants mock_confirm.
# Round 1: mock_confirm returns local_final=True.
# Loop must stop and use local_text as response.text.
# ---------------------------------------------------------------------------

def test_case_c_local_final_in_intermediate_round() -> None:
    planner_resp = _ai_resp(
        tool_calls=[AIToolCall(id="tc0", name="mock_read", input={})]
    )
    runner = _make_runner(
        planner_response=planner_resp,
        after_tools_responses=[
            # round 0 after-tools: wants mock_confirm
            _ai_resp(tool_calls=[AIToolCall(id="tc1", name="mock_confirm", input={})]),
        ],
    )
    orc = _make_orc(runner=runner)

    round0_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc0", "content": "content"}],
    )
    round1_loop = _loop_outcome(
        early_kind="local_final",
        local_text="Confirmación pendiente: di 'sí hazlo' para continuar.",
        local_model="tool-policy",
    )

    final = MagicMock(spec=ChatMessageResponse)
    final.ok = True

    with patch(f"{_MODULE}.run_tool_loop", side_effect=[round0_loop, round1_loop]), \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final) as mock_build, \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_persona_prompt.return_value = _persona()
        orc.run()

    # run_after_tools called once (round 0 only; round 1 exits via local_final before after-tools)
    runner.run_after_tools.assert_called_once()
    # response.text must be local_text, not after-tools text
    built_response = mock_build.call_args[1]["response"]
    assert built_response.text == "Confirmación pendiente: di 'sí hazlo' para continuar."


# ---------------------------------------------------------------------------
# Case D — cancellation mid-loop stops cleanly
#
# Round 0 after-tools returns more tool_calls, but is_cancelled returns True
# before round 1 starts. run_after_tools called only once.
# ---------------------------------------------------------------------------

def test_case_d_cancellation_mid_loop() -> None:
    planner_resp = _ai_resp(
        tool_calls=[AIToolCall(id="tc0", name="mock_search", input={})]
    )
    runner = _make_runner(
        planner_response=planner_resp,
        after_tools_responses=[
            _ai_resp(tool_calls=[AIToolCall(id="tc1", name="mock_act", input={})]),
            _ai_resp(text="Should not reach here."),
        ],
    )
    orc = _make_orc(runner=runner)

    fake_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc0", "content": "results"}],
    )
    final = MagicMock(spec=ChatMessageResponse)
    final.ok = True

    # is_cancelled sequence: False (initial gate) → False (round 0 loop start) →
    # False (post-after-tools check inside run_after_tools) → True (round 1 gate)
    with patch(f"{_MODULE}.run_tool_loop", return_value=fake_loop), \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe, \
         patch(f"{_MODULE}.is_cancelled", side_effect=[False, False, False, True]):
        mock_pe.return_value.build_persona_prompt.return_value = _persona()
        orc.run()

    # run_after_tools called once; round 1 is skipped because is_cancelled → True
    runner.run_after_tools.assert_called_once()


# ---------------------------------------------------------------------------
# Case E — max_after_tools_rounds limits the loop
#
# after-tools always returns a new tool_call. With max_after_tools_rounds=2,
# the loop must stop after 2 after-tools calls regardless.
# ---------------------------------------------------------------------------

def test_case_e_max_rounds_limit_stops_loop() -> None:
    planner_resp = _ai_resp(
        tool_calls=[AIToolCall(id="tc0", name="mock_fetch", input={})]
    )
    # after-tools always wants one more tool call
    runner = _make_runner(
        planner_response=planner_resp,
        after_tools_responses=[
            _ai_resp(text="partial", tool_calls=[AIToolCall(id="tc1", name="mock_more", input={})]),
            _ai_resp(text="still going", tool_calls=[AIToolCall(id="tc2", name="mock_more2", input={})]),
            _ai_resp(text="Should not reach here."),
        ],
    )
    orc = _make_orc(runner=runner, ai_config={"max_after_tools_rounds": 2})

    fake_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc0", "content": "r"}],
    )
    loop2 = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc1", "content": "r"}],
    )
    final = MagicMock(spec=ChatMessageResponse)
    final.ok = True

    with patch(f"{_MODULE}.run_tool_loop", side_effect=[fake_loop, loop2, MagicMock()]), \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_persona_prompt.return_value = _persona()
        orc.run()

    # With max=2, run_after_tools called at most 2 times
    assert runner.run_after_tools.call_count == 2


# ---------------------------------------------------------------------------
# Case F — detach in intermediate round closes turn immediately
#
# Round 0: mock_fetch runs. After-tools wants "mock_detachable" tool.
# get_blocking_policy("mock_detachable") == "detachable" → _detach_tool runs.
# Next after-tools sees synthetic "en_progreso" result → returns text → done.
# Exactly 2 run_after_tools calls: round 0 (wants detachable) + round 1 (en_progreso).
# ---------------------------------------------------------------------------

def test_case_f_detach_in_intermediate_round() -> None:
    planner_resp = _ai_resp(
        tool_calls=[AIToolCall(id="tc0", name="mock_fetch", input={})]
    )
    runner = _make_runner(
        planner_response=planner_resp,
        after_tools_responses=[
            # round 0: wants detachable tool
            _ai_resp(tool_calls=[AIToolCall(id="tc1", name="mock_detachable", input={})]),
            # round 1: en_progreso synthetic result → text response
            _ai_resp(text="Estoy buscando, te aviso pronto."),
        ],
    )
    orc = _make_orc(runner=runner)

    round0_loop = _loop_outcome(
        tool_results=[{"type": "tool_result", "tool_use_id": "tc0", "content": "data"}],
    )
    det_loop = ToolLoopRunOutcome(
        early_kind=None,
        early_tool_name="mock_detachable",
        local_text="",
        local_model="",
        sensor_event_type="",
        sensor_description="",
        sensor_artifacts=[],
        tool_results_for_claude=[{
            "type": "tool_result",
            "tool_use_id": "tc1",
            "content": '{"status": "en_progreso", "message": "Búsqueda lanzada."}',
        }],
        updated_parameters=[],
        artifacts=[],
    )

    final = MagicMock(spec=ChatMessageResponse)
    final.ok = True

    def _mock_get_blocking_policy(name: str) -> str:
        return "detachable" if name == "mock_detachable" else "blocking"

    with patch(f"{_MODULE}.run_tool_loop", return_value=round0_loop), \
         patch(f"{_MODULE}.get_blocking_policy", side_effect=_mock_get_blocking_policy), \
         patch(f"{_MODULE}._detach_tool", return_value=det_loop) as mock_detach, \
         patch(f"{_MODULE}.build_final_ai_response", return_value=final), \
         patch(f"{_MODULE}.get_today_token_usage", return_value=0), \
         patch(f"{_MODULE}.PersonaEngine") as mock_pe:
        mock_pe.return_value.build_persona_prompt.return_value = _persona()
        orc.run()

    mock_detach.assert_called_once()
    assert runner.run_after_tools.call_count == 2

"""ChatAIOrchestrator — complete AI turn execution.

Receives pre-built context (TurnContext + AITurnPrep) and runs the full
AI pipeline: routing decision, planner, tool loop, early returns
(local_final, sensor_*), model_upgrade_proposed, and final response with
optional TTS synthesis.
"""
from __future__ import annotations

import json
from typing import Any, NamedTuple, Optional

from app.audio.tts_service import maybe_attach_tts

from sqlmodel import Session, select

from app.api.schemas import ChatArtifact, ChatMessageRequest, ChatMessageResponse
from app.chat.ai_request_builder import (
    build_after_tools_ai_request,
    build_chat_ai_request,
    build_forced_search_request,
    build_planner_ai_request,
)
from app.chat.ai_turn_prep import AITurnPrep
from app.chat.background_dispatch import _detach_tool
from app.chat.budget_snapshot import build_budget_snapshot
from app.chat.chat_persistence import get_today_token_usage
from app.chat.final_response_builder import build_final_ai_response
from app.chat.model_router import (
    LocalFlowSignal,
    ModelUpgradeProposal,
    _categorize_upgrade_reason,
    get_accepted_upgrade_category,
    record_accepted_upgrade,
    set_proposal,
)
from app.chat.response_factory import local_tool_response, micro_reaction_response
from app.chat.response_guard import has_narrated_search
from app.chat.routing_decision import ProviderMode
from app.chat.tool_loop_runner import get_blocking_policy, run_tool_loop
from app.core.cancellation import is_cancelled
from app.chat.turn_context import TurnContext
from app.core.persona_engine import PersonaDecision, PersonaEngine
from app.core.tool_executor import ToolExecutor
from app.memory.models import AIUsage, ChatMessage
from app.trace.logger import write_log
from app.trace.redaction import redact_tool_call_input


# _detach_tool and _dispatch_background_task_result live in background_dispatch.py


def _tool_use_blocks(response: "Any") -> "list[dict[str, Any]]":
    return [
        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
        for tc in response.tool_calls
    ]




class _ToolBranchOutcome(NamedTuple):
    """Result of _execute_tool_branch; early_return is non-None for local_final/sensor exits."""
    early_return: Optional[ChatMessageResponse]
    tool_results: list[dict[str, Any]]
    updated_parameters: list[str]
    artifacts: list[ChatArtifact]
    persona_decision: PersonaDecision
    executor: Optional[ToolExecutor]


class ChatAIOrchestrator:
    def __init__(
        self,
        *,
        session: Session,
        ctx: TurnContext,
        prep: AITurnPrep,
        request: ChatMessageRequest,
        persona_prompt: str,
        persona_decision: PersonaDecision,
    ) -> None:
        self.session = session
        self.ctx = ctx
        self.prep = prep
        self.request = request
        self.persona_prompt = persona_prompt
        self._persona_decision = persona_decision

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> ChatMessageResponse:
        """Execute the full AI turn: routing → planner → tools → final response + TTS."""
        ctx = self.ctx
        prep = self.prep
        session = self.session
        request = self.request
        persona_decision = self._persona_decision

        write_log(
            level="INFO",
            module="core",
            event="persona_context_built",
            trace_id=ctx.trace_id,
            payload={
                "personality": ctx.personality,
                "refusal_mode": persona_decision.refusal_mode,
            },
        )

        tool_results_for_claude: list[dict] = []  # type: ignore[type-arg]
        updated_parameters: list[str] = []
        response_artifacts: list[ChatArtifact] = []
        executor: Optional[ToolExecutor] = None

        if prep.routing_decision.provider_mode == ProviderMode.local_chat_candidate:
            response = self._run_local_path()
        else:
            planner_response = self._run_cloud_planner()
            response = planner_response

            if planner_response.ok and planner_response.tool_calls:
                first_tool = planner_response.tool_calls[0]

                if first_tool.name == "no_action_required":
                    response = self._handle_no_action_required(planner_response, persona_decision)

                elif first_tool.name == "propose_model_upgrade":
                    return self._handle_model_upgrade(planner_response, persona_decision)

                else:
                    outcome = self._execute_tool_branch(planner_response, persona_decision)
                    if outcome.early_return is not None:
                        return outcome.early_return
                    tool_results_for_claude = outcome.tool_results
                    updated_parameters = outcome.updated_parameters
                    response_artifacts = outcome.artifacts
                    persona_decision = outcome.persona_decision
                    executor = outcome.executor

        if tool_results_for_claude and not is_cancelled(request.client_turn_id):
            self._run_after_tools_loop(response, tool_results_for_claude, persona_decision, executor)

        ctx.persistence.tag_sity_with_model(response.model)
        chat_result = build_final_ai_response(
            session=session,
            trace_id=ctx.trace_id,
            response=response,
            daily_budget=ctx.daily_budget,
            warning_threshold=ctx.warning_threshold,
            critical_threshold=ctx.critical_threshold,
            get_today_token_usage=get_today_token_usage,
            save_message=ctx.persistence.save,
            refusal_mode=persona_decision.refusal_mode,
            user_message=request.message,
            updated_parameters=updated_parameters,
            artifacts=response_artifacts,
            tone_meta=json.dumps(persona_decision.tone_snapshot),
            output_mode=prep.output_mode,
            source_channel=request.source_channel,
            session_id=ctx.session_id,
            language_override=ctx.language_override,
        )

        if prep.should_synth and chat_result.ok and chat_result.text:
            tts_result = maybe_attach_tts(
                text=chat_result.text,
                session=session,
                session_id=ctx.session_id,
                trace_id=ctx.trace_id,
                result=chat_result,
                voice_settings=ctx.voice_settings,
                language_override=ctx.language_override,
            )
            if tts_result is not None:
                n_fragments, audio_filename = tts_result
                _tts_row = session.exec(
                    select(ChatMessage).where(
                        ChatMessage.trace_id == ctx.trace_id,
                        ChatMessage.role == "sity",
                    )
                ).first()
                if _tts_row is not None:
                    _tts_row.tts_fragments = n_fragments
                    _tts_row.audio_filename = audio_filename
                    session.add(_tts_row)
                    session.commit()
                    write_log(level="INFO", module="audio", event="tts_db_committed",
                              trace_id=ctx.trace_id,
                              payload={"audio_filename": _tts_row.audio_filename,
                                       "tts_fragments": _tts_row.tts_fragments})
                if request.input_mode == "voice":
                    from app.achievements.triggers.inline import fire as _fire_ach
                    _fire_ach(session, ctx.session_id, "codec")

        return chat_result

    # ------------------------------------------------------------------
    # Phase 1 — initial AI call
    # ------------------------------------------------------------------

    def _run_local_path(self) -> Any:
        """Local LLM (Ollama) chat-only path — no planner, no tools, compact persona prompt."""
        ctx = self.ctx
        request = self.request
        local_persona_prompt = PersonaEngine().build_local_persona_prompt(
            ctx.personality, request.message, is_admin=ctx.is_admin
        )
        return self.prep.runner.run_local_chat(
            build_chat_ai_request(
                trace_id=ctx.trace_id,
                persona_prompt=local_persona_prompt,
                user_message=self.prep.prompt_context.user_message_with_history,
                max_tokens=ctx.max_tokens,
                prior_messages=self.prep.prompt_context.prior_messages,
                images=[{"media_type": img.media_type, "data": img.data} for img in request.images],
            )
        )

    def _run_cloud_planner(self) -> Any:
        """Run the action-planner call and return the planner AIResponse."""
        ctx = self.ctx
        prep = self.prep
        request = self.request

        _planner_max_tokens = ctx.ai_config.get("planner_max_tokens", 500)
        planner_request = build_planner_ai_request(
            trace_id=ctx.trace_id,
            user_message=prep.prompt_context.planner_user_message,
            tools=prep.selected_tools,
            prior_messages=prep.prompt_context.planner_prior_messages,
            max_tokens=_planner_max_tokens,
            images=[{"media_type": img.media_type, "data": img.data} for img in request.images],
            client_turn_id=request.client_turn_id,
        )

        write_log(
            level="INFO",
            module="cortex",
            event="ai_call_started",
            trace_id=ctx.trace_id,
            payload={
                "provider": "anthropic",
                "model": prep.runner._gateway.provider.model,
                "task_type": "action_planner",
                "max_tokens": _planner_max_tokens,
                "verbosity_level": float(ctx.personality.get("verbosity_level", 0.45)),
                "session_id": ctx.session_id,
            },
        )

        planner_response = prep.runner.run_planner(planner_request)

        write_log(
            level="INFO",
            module="cortex",
            event="ai_response_received",
            trace_id=ctx.trace_id,
            payload={
                "text_length": len(planner_response.text or ""),
                "tool_calls_count": len(planner_response.tool_calls),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "input_summary": redact_tool_call_input(tc.name, tc.input),
                    }
                    for tc in planner_response.tool_calls
                ],
            },
        )

        return planner_response

    # ------------------------------------------------------------------
    # Phase 2 — planner branch dispatch
    # ------------------------------------------------------------------

    def _handle_no_action_required(
        self, planner_response: Any, persona_decision: PersonaDecision
    ) -> Any:
        """Run the chat call for no_action_required, including the narration guard.

        Returns a new AIResponse with planner token usage merged in.
        """
        ctx = self.ctx
        prep = self.prep
        request = self.request
        images = [{"media_type": img.media_type, "data": img.data} for img in request.images]

        response = prep.runner.run_chat(
            build_chat_ai_request(
                trace_id=ctx.trace_id,
                persona_prompt=self.persona_prompt,
                user_message=prep.prompt_context.user_message_with_history,
                max_tokens=ctx.max_tokens,
                prior_messages=prep.prompt_context.prior_messages,
                images=images,
                client_turn_id=request.client_turn_id,
                assistant_prefill=None,
            )
        )

        # Guard: Sity narrated a search without calling the tool — force the real call.
        if response.ok and has_narrated_search(response.text):
            write_log(
                level="WARN",
                module="chat",
                event="narrated_search_without_tool_call",
                trace_id=ctx.trace_id,
                payload={"text_snippet": response.text[:200]},
            )
            _forced_plan = prep.runner.run_planner(
                build_forced_search_request(
                    trace_id=ctx.trace_id,
                    user_message=prep.prompt_context.planner_user_message,
                    tools=prep.selected_tools,
                    prior_messages=prep.prompt_context.planner_prior_messages,
                    client_turn_id=request.client_turn_id,
                )
            )
            if _forced_plan.ok and _forced_plan.tool_calls:
                _guard_loop = run_tool_loop(
                    planner_response=_forced_plan,
                    executor=ToolExecutor(self.session, ctx.session_id),
                    trace_id=ctx.trace_id,
                    client_turn_id=request.client_turn_id,
                    max_iterations=ctx.ai_config.get("max_tool_loop_iterations", 3),
                )
                if not _guard_loop.early_kind and _guard_loop.tool_results_for_claude:
                    _guard_after = prep.runner.run_after_tools(
                        request=build_after_tools_ai_request(
                            trace_id=ctx.trace_id,
                            persona_prompt=self.persona_prompt,
                            user_message=prep.prompt_context.user_message_with_history,
                            max_tokens=max(ctx.max_tokens, ctx.ai_config.get("after_tools_min_tokens", 700)),
                            tools=prep.selected_tools,
                            prior_messages=prep.prompt_context.prior_messages,
                            images=images,
                            client_turn_id=request.client_turn_id,
                        ),
                        first_response_content=[
                            {
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.input,
                            }
                            for tc in _forced_plan.tool_calls
                        ],
                        tool_results=_guard_loop.tool_results_for_claude,
                    )
                    if _guard_after.ok:
                        response.text = _guard_after.text
                    response.usage.input_tokens += (
                        _forced_plan.usage.input_tokens + _guard_after.usage.input_tokens
                    )
                    response.usage.output_tokens += (
                        _forced_plan.usage.output_tokens + _guard_after.usage.output_tokens
                    )
                    response.latency_ms += _forced_plan.latency_ms + _guard_after.latency_ms

        response.usage.input_tokens += planner_response.usage.input_tokens
        response.usage.output_tokens += planner_response.usage.output_tokens
        response.latency_ms += planner_response.latency_ms

        return response

    def _handle_model_upgrade(
        self, planner_response: Any, persona_decision: PersonaDecision
    ):
        """Record a model-upgrade proposal and return the prompt-the-user response.

        If the user already accepted an upgrade for the same task category this session,
        auto-accepts and returns LocalFlowSignal instead of asking again.
        """
        ctx = self.ctx
        prep = self.prep

        first_tool = planner_response.tool_calls[0]
        _reason = str(first_tool.input.get("reason", "")).strip()
        _strong = ctx.ai_config.get("claude", {}).get("strong_model", "claude-sonnet-4-6")

        # Auto-accept if the same task category was already accepted this session.
        _category = _categorize_upgrade_reason(_reason)
        _accepted_category = get_accepted_upgrade_category(ctx.session_id)
        if _accepted_category is not None and _accepted_category == _category:
            write_log(
                level="INFO", module="chat", event="model_upgrade_auto_accepted",
                trace_id=ctx.trace_id,
                payload={"reason": _reason, "category": _category, "strong_model": _strong},
            )
            return LocalFlowSignal(
                kind="model_upgrade_accepted",
                original_message=self.request.message,
                strong_model=_strong,
                selected_tools=list(prep.selected_tools),
                skip_history_turns=0,
            )

        set_proposal(ModelUpgradeProposal(
            original_message=self.request.message,
            strong_model=_strong,
            reason=_reason,
            selected_tools=list(prep.selected_tools),
        ))
        _proposal_text = (
            f"Esta tarea se beneficiaría del modelo más potente ({_strong}). "
            f"{_reason}. ¿Quieres que lo use?"
        )
        _snap = build_budget_snapshot(
            daily_used=get_today_token_usage(self.session),
            daily_budget=ctx.daily_budget,
            warning_threshold=ctx.warning_threshold,
            critical_threshold=ctx.critical_threshold,
        )
        _usage_row = AIUsage(
            trace_id=ctx.trace_id,
            session_id=None,
            provider=planner_response.provider,
            model=planner_response.model,
            task_type="action_planner",
            input_tokens=planner_response.usage.input_tokens,
            output_tokens=planner_response.usage.output_tokens,
            estimated_cost=0.0,
            latency_ms=planner_response.latency_ms,
            fallback_used=planner_response.fallback_used,
            success=planner_response.ok,
            error_type=planner_response.error_type,
        )
        self.session.add(_usage_row)
        self.session.commit()
        write_log(level="INFO", module="chat", event="model_upgrade_proposed",
                  trace_id=ctx.trace_id,
                  payload={"reason": _reason, "strong_model": _strong})
        ctx.persistence.save(
            role="sity", text=_proposal_text, trace_id=ctx.trace_id,
            tone_meta=json.dumps(persona_decision.tone_snapshot),
        )
        return local_tool_response(
            trace_id=ctx.trace_id,
            text=_proposal_text,
            model="model-router",
            planner_input_tokens=planner_response.usage.input_tokens,
            planner_output_tokens=planner_response.usage.output_tokens,
            daily_used=_snap.daily_used,
            daily_budget=_snap.daily_budget,
            daily_ratio=_snap.daily_ratio,
            warnings=_snap.warnings,
        )

    def _execute_tool_branch(
        self, planner_response: Any, persona_decision: PersonaDecision
    ) -> _ToolBranchOutcome:
        """Run the tool (detachable or blocking) for a normal planner tool call.

        Returns _ToolBranchOutcome with early_return set for local_final/sensor exits,
        or with tool_results/persona_decision populated for the normal after-tools path.
        """
        ctx = self.ctx
        prep = self.prep
        request = self.request

        executor = ToolExecutor(self.session, ctx.session_id)
        _first_tool = planner_response.tool_calls[0]

        if get_blocking_policy(_first_tool.name) == "detachable" and len(planner_response.tool_calls) == 1:
            _loop = _detach_tool(
                tool_call=_first_tool,
                executor=executor,
                trace_id=ctx.trace_id,
                runner=prep.runner,
                persona_prompt=self.persona_prompt,
                user_message_with_history=prep.prompt_context.user_message_with_history,
                prior_messages=prep.prompt_context.prior_messages,
                selected_tools=prep.selected_tools,
                request=request,
                ctx=ctx,
            )
        else:
            _loop = run_tool_loop(
                planner_response=planner_response,
                executor=executor,
                trace_id=ctx.trace_id,
                client_turn_id=request.client_turn_id,
                max_iterations=ctx.ai_config.get("max_tool_loop_iterations", 3),
            )

        if _loop.early_kind == "local_final":
            _usage_row = AIUsage(
                trace_id=ctx.trace_id,
                session_id=None,
                provider=planner_response.provider,
                model=planner_response.model,
                task_type="action_planner",
                input_tokens=planner_response.usage.input_tokens,
                output_tokens=planner_response.usage.output_tokens,
                estimated_cost=0.0,
                latency_ms=planner_response.latency_ms,
                fallback_used=planner_response.fallback_used,
                success=planner_response.ok,
                error_type=planner_response.error_type,
            )
            self.session.add(_usage_row)
            self.session.commit()

            _snap = build_budget_snapshot(
                daily_used=get_today_token_usage(self.session),
                daily_budget=ctx.daily_budget,
                warning_threshold=ctx.warning_threshold,
                critical_threshold=ctx.critical_threshold,
            )
            write_log(
                level="INFO",
                module="cortex",
                event="local_tool_response",
                trace_id=ctx.trace_id,
                payload={"tool": _loop.early_tool_name, "model": _loop.local_model},
            )
            ctx.persistence.save(
                role="sity", text=_loop.local_text, trace_id=ctx.trace_id,
                tone_meta=json.dumps(persona_decision.tone_snapshot),
            )
            _early_response = local_tool_response(
                trace_id=ctx.trace_id,
                text=_loop.local_text,
                model=_loop.local_model,
                planner_input_tokens=planner_response.usage.input_tokens,
                planner_output_tokens=planner_response.usage.output_tokens,
                daily_used=_snap.daily_used,
                daily_budget=_snap.daily_budget,
                daily_ratio=_snap.daily_ratio,
                warnings=_snap.warnings,
            )
            if prep.should_synth and _loop.local_text:
                _tts_result = maybe_attach_tts(
                    text=_loop.local_text,
                    session=self.session,
                    session_id=ctx.session_id,
                    trace_id=ctx.trace_id,
                    result=_early_response,
                    voice_settings=ctx.voice_settings,
                    language_override=ctx.language_override,
                )
                if _tts_result is not None:
                    _n_frags, _audio_fn = _tts_result
                    _tts_row = self.session.exec(
                        select(ChatMessage).where(
                            ChatMessage.trace_id == ctx.trace_id,
                            ChatMessage.role == "sity",
                        )
                    ).first()
                    if _tts_row is not None:
                        _tts_row.tts_fragments = _n_frags
                        _tts_row.audio_filename = _audio_fn
                        self.session.add(_tts_row)
                        self.session.commit()
            return _ToolBranchOutcome(
                early_return=_early_response,
                tool_results=[],
                updated_parameters=[],
                artifacts=[],
                persona_decision=persona_decision,
                executor=None,
            )

        if _loop.early_kind in ("sensor_cancelled", "sensor_finished"):
            _personality_dict = ctx.personality if isinstance(ctx.personality, dict) else {}
            _react_text = prep.runner.run_micro_reaction(
                event_type=_loop.sensor_event_type,
                event_description=_loop.sensor_description,
                personality=_personality_dict,
                trace_id=ctx.trace_id,
            )
            write_log(
                level="AUDIT",
                module="senses",
                event=_loop.sensor_event_type,
                trace_id=ctx.trace_id,
                payload={"tool": _loop.early_tool_name},
                audit=True,
            )
            ctx.persistence.save(
                role="sity", text=_react_text, trace_id=ctx.trace_id,
                tone_meta=json.dumps(persona_decision.tone_snapshot),
            )
            return _ToolBranchOutcome(
                early_return=micro_reaction_response(
                    trace_id=ctx.trace_id,
                    text=_react_text,
                    daily_used=get_today_token_usage(self.session),
                    daily_budget=ctx.daily_budget,
                    artifacts=_loop.sensor_artifacts,
                ),
                tool_results=[],
                updated_parameters=[],
                artifacts=[],
                persona_decision=persona_decision,
                executor=None,
            )

        # Normal path: propagate accumulated results and re-derive persona after tool side-effects.
        write_log(
            level="INFO",
            module="tools",
            event="tool_results_ready",
            trace_id=ctx.trace_id,
            payload={
                "updated_parameters": _loop.updated_parameters,
                "tool_results_count": len(_loop.tool_results_for_claude),
            },
        )

        ctx.personality = ctx.settings_service.get_personality()
        updated_persona_decision = PersonaEngine().build_persona_prompt(
            ctx.personality, request.message, session_id=ctx.session_id, language_override=ctx.language_override, is_admin=ctx.is_admin
        )

        return _ToolBranchOutcome(
            early_return=None,
            tool_results=_loop.tool_results_for_claude,
            updated_parameters=_loop.updated_parameters,
            artifacts=_loop.artifacts,
            persona_decision=updated_persona_decision,
            executor=executor,
        )

    # ------------------------------------------------------------------
    # Phase 3 — after-tools multi-round loop
    # ------------------------------------------------------------------

    def _run_after_tools_loop(
        self,
        response: Any,
        tool_results_for_claude: list[dict],  # type: ignore[type-arg]
        persona_decision: PersonaDecision,
        executor: Optional[ToolExecutor],
    ) -> None:
        """Run up to max_after_tools_rounds of after-tools calls, handling chained tool requests.

        Mutates response in place (text, usage, error fields). executor must be non-None
        because tool_results_for_claude being non-empty implies a tool branch ran first.
        """
        assert executor is not None
        ctx = self.ctx
        prep = self.prep
        request = self.request
        images = [{"media_type": img.media_type, "data": img.data} for img in request.images]

        max_after_tools_rounds: int = ctx.ai_config.get("max_after_tools_rounds", 3)
        source_response = response
        accumulated_tool_rounds: list[dict[str, Any]] = []

        for _round in range(max_after_tools_rounds):
            if is_cancelled(request.client_turn_id):
                break

            response_after_tools = prep.runner.run_after_tools(
                request=build_after_tools_ai_request(
                    trace_id=ctx.trace_id,
                    persona_prompt=self.persona_prompt,
                    user_message=prep.prompt_context.user_message_with_history,
                    max_tokens=max(ctx.max_tokens, ctx.ai_config.get("after_tools_min_tokens", 700)),
                    tools=prep.selected_tools,
                    prior_messages=prep.prompt_context.prior_messages,
                    images=images,
                    client_turn_id=request.client_turn_id,
                ),
                first_response_content=_tool_use_blocks(source_response),
                tool_results=tool_results_for_claude,
                extra_prior_rounds=accumulated_tool_rounds or None,
            )

            response.usage.input_tokens += response_after_tools.usage.input_tokens
            response.usage.output_tokens += response_after_tools.usage.output_tokens
            response.latency_ms += response_after_tools.latency_ms
            response.error_type = response_after_tools.error_type
            response.error_message = response_after_tools.error_message
            response.text = response_after_tools.text

            if not response_after_tools.tool_calls or is_cancelled(request.client_turn_id):
                break

            write_log(
                level="INFO",
                module="tools",
                event="tool_chain_continued",
                trace_id=ctx.trace_id,
                payload={
                    "round": _round + 1,
                    "tool_calls_requested": [tc.name for tc in response_after_tools.tool_calls],
                },
            )

            accumulated_tool_rounds = accumulated_tool_rounds + [
                {"role": "assistant", "content": _tool_use_blocks(source_response)},
                {"role": "user",      "content": tool_results_for_claude},
            ]

            _first_tc = response_after_tools.tool_calls[0]
            if get_blocking_policy(_first_tc.name) == "detachable" and len(response_after_tools.tool_calls) == 1:
                _det_loop = _detach_tool(
                    tool_call=_first_tc,
                    executor=executor,
                    trace_id=ctx.trace_id,
                    runner=prep.runner,
                    persona_prompt=self.persona_prompt,
                    user_message_with_history=prep.prompt_context.user_message_with_history,
                    prior_messages=prep.prompt_context.prior_messages,
                    selected_tools=prep.selected_tools,
                    request=request,
                    ctx=ctx,
                )
                tool_results_for_claude = _det_loop.tool_results_for_claude
                source_response = response_after_tools
                continue

            _loop = run_tool_loop(
                planner_response=response_after_tools,
                executor=executor,
                trace_id=ctx.trace_id,
                client_turn_id=request.client_turn_id,
                max_iterations=ctx.ai_config.get("max_tool_loop_iterations", 3),
                loop_round=_round + 1,
            )

            if _loop.early_kind == "local_final":
                response.text = _loop.local_text
                break

            if _loop.early_kind in ("sensor_cancelled", "sensor_finished"):
                _personality_dict = ctx.personality if isinstance(ctx.personality, dict) else {}
                response.text = prep.runner.run_micro_reaction(
                    event_type=_loop.sensor_event_type,
                    event_description=_loop.sensor_description,
                    personality=_personality_dict,
                    trace_id=ctx.trace_id,
                )
                break

            tool_results_for_claude = _loop.tool_results_for_claude
            source_response = response_after_tools

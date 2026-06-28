"""ChatAIOrchestrator — complete AI turn execution.

Receives pre-built context (TurnContext + AITurnPrep) and runs the full
AI pipeline: routing decision, planner, tool loop, early returns
(local_final, sensor_*), model_upgrade_proposed, and final response with
optional TTS synthesis.

Also hosts _clean_text_for_tts and _attach_tts_artifacts (re-exported from
routes_chat for backwards-compatible test imports).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from sqlmodel import Session, select

from app.api.schemas import ChatArtifact, ChatMessageRequest, ChatMessageResponse
from app.chat.ai_request_builder import (
    build_after_tools_ai_request,
    build_chat_ai_request,
    build_forced_search_request,
    build_planner_ai_request,
)
from app.chat.ai_turn_prep import AITurnPrep
from app.chat.budget_snapshot import build_budget_snapshot
from app.chat.chat_persistence import get_today_token_usage
from app.chat.final_response_builder import build_final_ai_response
from app.chat.model_router import ModelUpgradeProposal, set_proposal
from app.chat.response_factory import local_tool_response, micro_reaction_response
from app.chat.response_guard import has_narrated_search
from app.chat.routing_decision import ProviderMode
from app.chat.tool_loop_runner import run_tool_loop
from app.chat.turn_context import TurnContext
from app.core.persona_engine import PersonaDecision, PersonaEngine
from app.core.tool_executor import ToolExecutor
from app.memory.models import AIUsage, ChatMessage
from app.trace.logger import write_log
from app.trace.redaction import redact_tool_call_input


def _clean_text_for_tts(text: str) -> str:
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text.strip()


def _attach_tts_artifacts(
    *, result, text: str, voice_settings, trace_id: str
) -> Optional[tuple[int, Optional[str]]]:
    """Synthesize TTS audio and attach as artifacts to result. Modifies result.artifacts in place.

    Returns (n_fragments, audio_filename) where audio_filename is the persistent file written to
    data/audio/ (or None if persistence is disabled). Returns None if synthesis was skipped/failed.
    """
    from app.api.routes_audio import synthesize_to_tmp, synthesize_to_persistent
    from app.audio.synthesizer import load_tts_config
    from app.audio.tts_splitter import split_by_sentences
    from app.settings.config_loader import load_default_config

    cfg = load_tts_config()
    raw_audio_cfg = load_default_config().get("audio", {})
    persist_tts: bool = bool(raw_audio_cfg.get("persist_tts", False))

    try:
        tts_text = _clean_text_for_tts(text)
        if len(tts_text) <= cfg.long_response_chars:
            fragments = [tts_text]
        elif voice_settings.voice_long_response_action == "split":
            fragments = split_by_sentences(tts_text, cfg.long_response_chars)
        else:
            write_log(level="INFO", module="audio", event="tts_skipped_long_response",
                      trace_id=trace_id, payload={"chars": len(text)})
            return None

        first_persistent_filename: Optional[str] = None
        artifact_index = 0
        for i, fragment in enumerate(fragments):
            if not fragment.strip():
                write_log(level="INFO", module="audio", event="tts_fragment_skipped",
                          trace_id=trace_id, payload={"fragment_index": i, "reason": "empty"})
                continue
            if persist_tts:
                url, filename = synthesize_to_persistent(fragment, trace_id=trace_id)
                write_log(level="INFO", module="audio", event="tts_fragment_persisted",
                          trace_id=trace_id,
                          payload={"fragment_index": i, "filename": filename})
                if first_persistent_filename is None:
                    first_persistent_filename = filename
            else:
                url = synthesize_to_tmp(fragment)
            result.artifacts.append(ChatArtifact(
                type="audio",
                url=url,
                filename=f"sity_response_{artifact_index + 1}.wav",
                mime_type="audio/wav",
            ))
            artifact_index += 1

        write_log(level="INFO", module="audio", event="tts_attached",
                  trace_id=trace_id,
                  payload={"fragments": len(fragments), "total_chars": len(text),
                           "first_persistent_filename": first_persistent_filename})
        return len(fragments), first_persistent_filename
    except Exception as exc:
        write_log(level="WARN", module="audio", event="tts_failed",
                  trace_id=trace_id, payload={"error": str(exc), "error_type": type(exc).__name__})
        return None


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

    def run(self) -> ChatMessageResponse:
        """
        Ejecuta el flujo AI completo:
        - local_chat (Ollama) o cloud_chat/cloud_tools
        - planner → tool loop → after_tools
        - early returns (local_final, sensor_*)
        - model_upgrade_proposed
        - respuesta final con TTS
        """
        ctx = self.ctx
        prep = self.prep
        session = self.session
        request = self.request
        persona_prompt = self.persona_prompt
        persona_decision = self._persona_decision

        runner = prep.runner
        selected_tools = prep.selected_tools
        routing_decision = prep.routing_decision
        output_mode = prep.output_mode
        _should_synth = prep.should_synth
        user_message_with_history = prep.prompt_context.user_message_with_history
        planner_user_message = prep.prompt_context.planner_user_message
        prior_messages = prep.prompt_context.prior_messages
        planner_prior_messages = prep.prompt_context.planner_prior_messages

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
        planner_response = None

        if routing_decision.provider_mode == ProviderMode.local_chat_candidate:
            # Local LLM (Ollama): chat-only path — no planner, no tools sent.
            # Uses a compact, label-free persona prompt suited to smaller models.
            # Uses the separately configured local_provider, NOT the cloud gateway.
            # provider_unavailable / provider_error errors flow through
            # build_final_ai_response as controlled (ok=False) responses.
            local_persona_prompt = PersonaEngine().build_local_persona_prompt(
                ctx.personality, request.message
            )
            response = runner.run_local_chat(
                build_chat_ai_request(
                    trace_id=ctx.trace_id,
                    persona_prompt=local_persona_prompt,
                    user_message=user_message_with_history,
                    max_tokens=ctx.max_tokens,
                    prior_messages=prior_messages,
                )
            )
        else:
            # cloud_chat or cloud_tools: planner decides tool selection.
            planner_request = build_planner_ai_request(
                trace_id=ctx.trace_id,
                user_message=planner_user_message,
                tools=selected_tools,
                prior_messages=planner_prior_messages,
            )

            write_log(
                level="INFO",
                module="cortex",
                event="ai_call_started",
                trace_id=ctx.trace_id,
                payload={
                    "provider": "anthropic",
                    "model": runner._gateway.provider.model,
                    "task_type": "action_planner",
                    "max_tokens": 500,
                    "verbosity_level": float(ctx.personality.get("verbosity_level", 0.45)),
                },
            )

            planner_response = runner.run_planner(planner_request)

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

            response = planner_response

        if planner_response is not None and planner_response.ok and planner_response.tool_calls:
            first_tool = planner_response.tool_calls[0]

            if first_tool.name == "no_action_required":
                response = runner.run_chat(
                    build_chat_ai_request(
                        trace_id=ctx.trace_id,
                        persona_prompt=persona_prompt,
                        user_message=user_message_with_history,
                        max_tokens=ctx.max_tokens,
                        prior_messages=prior_messages,
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
                    _forced_plan = runner.run_planner(
                        build_forced_search_request(
                            trace_id=ctx.trace_id,
                            user_message=planner_user_message,
                            tools=selected_tools,
                            prior_messages=planner_prior_messages,
                        )
                    )
                    if _forced_plan.ok and _forced_plan.tool_calls:
                        _guard_loop = run_tool_loop(
                            planner_response=_forced_plan,
                            executor=ToolExecutor(session),
                            trace_id=ctx.trace_id,
                            client_turn_id=request.client_turn_id,
                        )
                        if not _guard_loop.early_kind and _guard_loop.tool_results_for_claude:
                            _guard_after = runner.run_after_tools(
                                request=build_after_tools_ai_request(
                                    trace_id=ctx.trace_id,
                                    persona_prompt=persona_prompt,
                                    user_message=user_message_with_history,
                                    max_tokens=max(ctx.max_tokens, 700),
                                    tools=selected_tools,
                                    prior_messages=prior_messages,
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

            elif first_tool.name == "propose_model_upgrade":
                _reason = str(first_tool.input.get("reason", "")).strip()
                _strong = ctx.ai_config.get("claude", {}).get("strong_model", "claude-sonnet-4-6")
                set_proposal(ModelUpgradeProposal(
                    original_message=request.message,
                    strong_model=_strong,
                    reason=_reason,
                ))
                _proposal_text = (
                    f"Esta tarea se beneficiaría del modelo más potente ({_strong}). "
                    f"{_reason}. ¿Quieres que lo use?"
                )
                _snap = build_budget_snapshot(
                    daily_used=get_today_token_usage(session),
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
                session.add(_usage_row)
                session.commit()
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

            else:
                executor = ToolExecutor(session)
                _loop = run_tool_loop(
                    planner_response=planner_response,
                    executor=executor,
                    trace_id=ctx.trace_id,
                    client_turn_id=request.client_turn_id,
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
                    session.add(_usage_row)
                    session.commit()

                    _snap = build_budget_snapshot(
                        daily_used=get_today_token_usage(session),
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
                    return local_tool_response(
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

                if _loop.early_kind in ("sensor_cancelled", "sensor_finished"):
                    _personality_dict = ctx.personality if isinstance(ctx.personality, dict) else {}
                    _react_text = runner.run_micro_reaction(
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
                    return micro_reaction_response(
                        trace_id=ctx.trace_id,
                        text=_react_text,
                        daily_used=get_today_token_usage(session),
                        daily_budget=ctx.daily_budget,
                        artifacts=_loop.sensor_artifacts,
                    )

                # Normal path: propagate accumulated results
                tool_results_for_claude = _loop.tool_results_for_claude
                updated_parameters = _loop.updated_parameters
                response_artifacts = _loop.artifacts

                write_log(
                    level="INFO",
                    module="tools",
                    event="tool_results_ready",
                    trace_id=ctx.trace_id,
                    payload={
                        "updated_parameters": updated_parameters,
                        "tool_results_count": len(tool_results_for_claude),
                    },
                )

                ctx.personality = ctx.settings_service.get_personality()
                persona_decision = PersonaEngine().build_persona_prompt(
                    ctx.personality, request.message
                )

        if tool_results_for_claude:
            response_after_tools = runner.run_after_tools(
                request=build_after_tools_ai_request(
                    trace_id=ctx.trace_id,
                    persona_prompt=persona_decision.system_prompt,
                    user_message=user_message_with_history,
                    max_tokens=max(ctx.max_tokens, 700),
                    tools=selected_tools,
                    prior_messages=prior_messages,
                ),
                first_response_content=[
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.input,
                    }
                    for tool_call in response.tool_calls
                ],
                tool_results=tool_results_for_claude,
            )

            response.text = response_after_tools.text
            response.usage.input_tokens += response_after_tools.usage.input_tokens
            response.usage.output_tokens += response_after_tools.usage.output_tokens
            response.latency_ms += response_after_tools.latency_ms
            response.error_type = response_after_tools.error_type
            response.error_message = response_after_tools.error_message

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
            output_mode=output_mode,
            source_channel=request.source_channel,
        )

        # TTS post-processing: reuse the decision already made before generation.
        if _should_synth and chat_result.ok and chat_result.text:
            tts_result = _attach_tts_artifacts(
                result=chat_result,
                text=chat_result.text,
                voice_settings=ctx.voice_settings,
                trace_id=ctx.trace_id,
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

        return chat_result

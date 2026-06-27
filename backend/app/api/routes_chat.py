import json
from typing import Optional


from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.schemas import (
    ChatArtifact,
    ChatHistoryItem,
    ChatMessageItem,
    ChatMessageRequest,
    ChatMessageResponse,
    CurrentChatResponse,
)
from app.chat.chat_persistence import (
    DEFAULT_CHAT_SESSION_ID,
    get_or_create_default_chat_session,
    get_recent_db_messages,
    get_today_token_usage,
    save_chat_message,
)
from app.chat.prompt_context import PromptContextBuilder
from app.chat.local_flow import ChatLocalFlow, LocalFlowContext
from app.chat.model_router import LocalFlowSignal, ModelUpgradeProposal, set_proposal
from app.chat.local_provider_config import resolve_local_provider_model
from app.chat.budget_guard import BudgetGuardContext, ChatBudgetGuard
from app.chat.ai_request_builder import (
    build_after_tools_ai_request,
    build_chat_ai_request,
    build_forced_search_request,
    build_planner_ai_request,
    max_tokens_for_verbosity,
)
from app.chat.toolset_selector import (
    history_limit_for_message,
    message_mentions_file_path,
    select_toolset_with_metadata,
)
from app.chat.routing_decision import build_chat_routing_decision, ProviderMode
from app.chat.pending_action_runner import PendingActionRunner
from app.chat.budget_snapshot import build_budget_snapshot
from app.chat.tool_loop_runner import run_tool_loop
from app.chat.provider_call_runner import ProviderCallRunner
from app.chat.final_response_builder import build_final_ai_response
from app.chat.response_factory import (
    local_tool_response,
    micro_reaction_response,
)
from app.chat.response_guard import has_narrated_search

from app.actions.confirmation_manager import ConfirmationManager
from app.core.cancellation import clear_operation, register_operation
from app.core.runtime_config import get_runtime_config
from app.core.realtime_events import publish_event_sync
from app.core.order_override import has_direct_order_override
from app.core.persona_engine import PersonaEngine
from app.core.refusal_tracker import get_last_refusal
from app.core.tool_executor import ToolExecutor
from app.cortex.ai_gateway import AIGateway
from app.cortex.providers.factory import build_ai_provider

from app.chat.turn_persistence import ChatTurnPersistence
from app.memory.db import get_session
from app.memory.models import AIUsage, ChatMessage
from app.training.dataset_capture import DatasetCaptureService
from app.settings.config_loader import load_default_config
from app.settings.settings_service import SettingsService
from app.trace.logger import new_trace_id, write_log
from app.trace.redaction import redact_tool_call_input


router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/current", response_model=CurrentChatResponse)
def current_chat(session: Session = Depends(get_session)):
    get_or_create_default_chat_session(session)

    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == DEFAULT_CHAT_SESSION_ID)
        .order_by(ChatMessage.id.desc())
        .limit(200)
    )

    rows = list(session.exec(statement))
    rows.reverse()

    messages = [
        ChatMessageItem(
            role=row.role,
            text=row.text,
            trace_id=row.trace_id,
            created_at=row.created_at,
            audio_filename=row.audio_filename,
        )
        for row in rows
    ]

    return CurrentChatResponse(
        ok=True,
        session_id=DEFAULT_CHAT_SESSION_ID,
        messages=messages,
    )



















@router.post("/message", response_model=ChatMessageResponse)
def chat_message(
    request: ChatMessageRequest,
    session: Session = Depends(get_session),
):
    cid = request.client_turn_id
    if cid:
        register_operation(cid)

    try:
        result = _chat_message_inner(request=request, session=session)
        if isinstance(result, LocalFlowSignal) and result.kind == "model_upgrade_accepted":
            write_log(level="INFO", module="chat", event="model_upgrade_accepted",
                      trace_id="outer",
                      payload={"original_message": result.original_message[:80],
                               "strong_model": result.strong_model})
            upgraded = request.model_copy(update={"message": result.original_message})
            write_log(level="INFO", module="chat", event="model_upgrade_rerun",
                      trace_id="outer",
                      payload={"strong_model": result.strong_model,
                               "message_len": len(result.original_message)})
            result = _chat_message_inner(
                request=upgraded, session=session, _strong_model=result.strong_model
            )
        return result
    except Exception:
        publish_event_sync(cid, {"type": "error", "label": "Error procesando la petición."})
        raise
    finally:
        publish_event_sync(cid, {"type": "done"})
        if cid:
            clear_operation(cid)


def _chat_message_inner(
    *,
    request: ChatMessageRequest,
    session: Session,
    _strong_model: str | None = None,
):
    trace_id = new_trace_id()
    config = load_default_config()
    if _strong_model:
        import copy
        config = copy.deepcopy(config)
        config.setdefault("ai", {}).setdefault("claude", {})["model"] = _strong_model
    settings_service = SettingsService(session)
    personality = settings_service.get_personality()

    # Read capture context once per turn; build role-specific metadata from it.
    _capture_svc = DatasetCaptureService(session)
    _capture_ctx = _capture_svc.get()
    persistence = ChatTurnPersistence(session, _capture_ctx, _capture_svc)

    write_log(
        level="INFO",
        module="chat",
        event="user_message_received",
        trace_id=trace_id,
        payload={
            "message_length": len(request.message),
            "history_items": len(request.history),
        },
    )

    persona_decision = PersonaEngine().build_persona_prompt(personality, request.message)
    persona_prompt = persona_decision.system_prompt

    if has_direct_order_override(request.message):
        last = get_last_refusal()
        if last:
            persona_prompt += (
                "\n\nCONTEXTO DE OVERRIDE: El usuario está ordenando ejecutar esta petición "
                "que fue rechazada antes por personalidad:\n"
                f"\"{last['user_message']}\"\n\n"
                "Responde a esa petición ahora. Mantén tu personalidad y tono, "
                "pero no rechaces por refusal_mode. La seguridad y las allowlists siguen activas."
            )

    ai_config = config.get("ai", {})
    usage_config = config.get("usage", {})

    configured_max_tokens = int(ai_config.get("claude", {}).get("max_tokens", 1500))
    verbosity_level = float(personality.get("verbosity_level", 0.45))
    max_tokens = max_tokens_for_verbosity(
        verbosity_level=verbosity_level,
        configured_max_tokens=configured_max_tokens,
    )
    daily_budget = int(usage_config.get("daily_token_budget", 1000000))
    warning_threshold = float(usage_config.get("warning_threshold", 0.80))
    critical_threshold = float(usage_config.get("critical_threshold", 0.95))

    confirmation_manager = ConfirmationManager(session)
    local_flow = ChatLocalFlow(confirmation_manager)

    _local_ctx = LocalFlowContext(
        session=session,
        trace_id=trace_id,
        message=request.message,
        daily_budget=daily_budget,
        warnings=[],
        save_message=persistence.save,
        get_usage=get_today_token_usage,
    )

    local_response = local_flow.try_handle(_local_ctx)
    if local_response:
        return local_response

    pending_action = confirmation_manager.find_pending_action_by_confirmation(request.message)

    if not pending_action:
        pending_action = confirmation_manager.find_pending_action_by_context(request.message)

    if pending_action:
        runner = PendingActionRunner(confirmation_manager)
        return runner.run(pending_action, _local_ctx)

    runtime_config = get_runtime_config()

    budget_response = ChatBudgetGuard().try_handle(
        BudgetGuardContext(
            session=session,
            trace_id=trace_id,
            message=request.message,
            daily_budget=daily_budget,
            runtime_config=runtime_config,
            save_message=persistence.save,
            get_usage=get_today_token_usage,
        )
    )
    if budget_response:
        return budget_response

    history_limit = history_limit_for_message(request.message)
    if message_mentions_file_path(request.message):
        history_limit = 2

    # Compute output_mode once — reused for prompt context AND TTS post-processing.
    voice_settings = settings_service.get_voice_settings()
    _should_synth = _should_synthesize(voice_settings.voice_response_mode, request.input_mode)
    output_mode = "voice" if _should_synth else "text"
    write_log(level="INFO", module="audio", event="tts_decision",
              trace_id=trace_id,
              payload={"voice_response_mode": voice_settings.voice_response_mode,
                       "input_mode": request.input_mode,
                       "should_synth": _should_synth})

    prompt_context = PromptContextBuilder(
        get_recent_messages=get_recent_db_messages,
    ).build(
        session=session,
        message=request.message,
        history_limit=history_limit,
        planner_history_limit=4,
        trace_id=trace_id,
        input_mode=request.input_mode,
        output_mode=output_mode,
    )

    recent_history = prompt_context.recent_history
    planner_history = prompt_context.planner_history
    user_message_with_history = prompt_context.user_message_with_history
    planner_user_message = prompt_context.planner_user_message
    prior_messages = prompt_context.prior_messages
    planner_prior_messages = prompt_context.planner_prior_messages

    write_log(
        level="INFO",
        module="chat",
        event="history_injected",
        trace_id=trace_id,
        payload={
            "session_id": DEFAULT_CHAT_SESSION_ID,
            "history_limit": history_limit,
            "history_count": len(recent_history),
            "planner_history_count": len(planner_history),
        },
    )

    write_log(
        level="INFO",
        module="core",
        event="persona_context_built",
        trace_id=trace_id,
        payload={
            "personality": personality,
            "refusal_mode": persona_decision.refusal_mode,
        },
    )

    _voice_edit_pct: Optional[float] = None
    if request.input_mode == "voice" and request.voice_transcript_original:
        from app.audio.edit_distance import compute_edit_distance_pct
        _voice_edit_pct = compute_edit_distance_pct(
            request.voice_transcript_original, request.message
        )
        write_log(
            level="INFO",
            module="audio",
            event="voice_input",
            trace_id=trace_id,
            payload={
                "input_mode": "voice",
                "edit_distance_pct": _voice_edit_pct,
                "original_len": len(request.voice_transcript_original),
                "final_len": len(request.message),
            },
        )

    persistence.save(
        role="user",
        text=request.message,
        trace_id=trace_id,
        input_mode=request.input_mode,
        voice_transcript_original=request.voice_transcript_original,
        edit_distance_pct=_voice_edit_pct,
        source_channel=request.source_channel,
    )

    # Build local provider when SITY_LOCAL_AI_ENABLED=true.
    # SITY_AI_PROVIDER is the cloud provider (anthropic); local provider is separate.
    # SITY_OLLAMA_MODEL must be set explicitly — never use the cloud model as fallback.
    _local_provider = None
    if runtime_config.local_ai_enabled:
        _ollama_model = resolve_local_provider_model(runtime_config)
        if _ollama_model is None:
            write_log(
                level="ERROR",
                module="chat",
                event="local_ai_misconfigured",
                trace_id=trace_id,
                payload={
                    "error_message": "SITY_LOCAL_AI_ENABLED=true but SITY_OLLAMA_MODEL is not configured",
                    "local_ai_provider": runtime_config.local_ai_provider,
                },
            )
        else:
            _local_provider = build_ai_provider(
                runtime_config.local_ai_provider,
                model=_ollama_model,
            )

    runner = ProviderCallRunner(AIGateway(config=config), local_provider=_local_provider)

    toolset_selection = select_toolset_with_metadata(request.message, input_mode=request.input_mode)
    selected_tools = toolset_selection.tools

    # Inject read_own_trace only when dataset_source == "debug_test".
    if _capture_ctx.dataset_source == "debug_test":
        from app.cortex.tool_schemas import READ_OWN_TRACE_TOOL
        if not any(t.get("name") == "read_own_trace" for t in selected_tools):
            selected_tools = list(selected_tools) + [READ_OWN_TRACE_TOOL]

    # Inject propose_model_upgrade when model_router_enabled, but NOT on strong-model re-runs
    # (_strong_model is set) to prevent Sonnet from proposing a further upgrade.
    if ai_config.get("claude", {}).get("model_router_enabled", False) and not _strong_model:
        from app.cortex.tool_schemas import PROPOSE_MODEL_UPGRADE_TOOL
        if not any(t.get("name") == "propose_model_upgrade" for t in selected_tools):
            selected_tools = list(selected_tools) + [PROPOSE_MODEL_UPGRADE_TOOL]

    routing_decision = build_chat_routing_decision(
        message=request.message,
        selection=toolset_selection,
        local_ai_enabled=runtime_config.local_ai_enabled,
    )

    write_log(
        level="INFO",
        module="chat",
        event="routing_decision",
        trace_id=trace_id,
        payload={
            "provider_mode": routing_decision.provider_mode.value,
            "activated_domains": sorted(toolset_selection.activated_domains),
            "reasons": toolset_selection.reasons,
            "local_ai_enabled": routing_decision.local_ai_enabled,
            "reason": routing_decision.reason,
        },
    )

    tool_results_for_claude: list[dict] = []
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
            personality, request.message
        )
        response = runner.run_local_chat(
            build_chat_ai_request(
                trace_id=trace_id,
                persona_prompt=local_persona_prompt,
                user_message=user_message_with_history,
                max_tokens=max_tokens,
                prior_messages=prior_messages,
            )
        )
    else:
        # cloud_chat or cloud_tools: planner decides tool selection.
        planner_request = build_planner_ai_request(
            trace_id=trace_id,
            user_message=planner_user_message,
            tools=selected_tools,
            prior_messages=planner_prior_messages,
        )

        write_log(
            level="INFO",
            module="cortex",
            event="ai_call_started",
            trace_id=trace_id,
            payload={
                "provider": "anthropic",
                "task_type": "action_planner",
                "max_tokens": 500,
                "verbosity_level": verbosity_level,
            },
        )

        planner_response = runner.run_planner(planner_request)

        write_log(
            level="INFO",
            module="cortex",
            event="ai_response_received",
            trace_id=trace_id,
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
                    trace_id=trace_id,
                    persona_prompt=persona_prompt,
                    user_message=user_message_with_history,
                    max_tokens=max_tokens,
                    prior_messages=prior_messages,
                )
            )

            # Guard: Sity narrated a search without calling the tool — force the real call.
            if response.ok and has_narrated_search(response.text):
                write_log(
                    level="WARN",
                    module="chat",
                    event="narrated_search_without_tool_call",
                    trace_id=trace_id,
                    payload={"text_snippet": response.text[:200]},
                )
                _forced_plan = runner.run_planner(
                    build_forced_search_request(
                        trace_id=trace_id,
                        user_message=planner_user_message,
                        tools=selected_tools,
                        prior_messages=planner_prior_messages,
                    )
                )
                if _forced_plan.ok and _forced_plan.tool_calls:
                    _guard_loop = run_tool_loop(
                        planner_response=_forced_plan,
                        executor=ToolExecutor(session),
                        trace_id=trace_id,
                        client_turn_id=request.client_turn_id,
                    )
                    if not _guard_loop.early_kind and _guard_loop.tool_results_for_claude:
                        _guard_after = runner.run_after_tools(
                            request=build_after_tools_ai_request(
                                trace_id=trace_id,
                                persona_prompt=persona_prompt,
                                user_message=user_message_with_history,
                                max_tokens=max(max_tokens, 700),
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
                        response.usage.input_tokens += _forced_plan.usage.input_tokens + _guard_after.usage.input_tokens
                        response.usage.output_tokens += _forced_plan.usage.output_tokens + _guard_after.usage.output_tokens
                        response.latency_ms += _forced_plan.latency_ms + _guard_after.latency_ms

            response.usage.input_tokens += planner_response.usage.input_tokens
            response.usage.output_tokens += planner_response.usage.output_tokens
            response.latency_ms += planner_response.latency_ms
        elif first_tool.name == "propose_model_upgrade":
            _reason = str(first_tool.input.get("reason", "")).strip()
            _strong = ai_config.get("claude", {}).get("strong_model", "claude-sonnet-4-6")
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
                daily_budget=daily_budget,
                warning_threshold=warning_threshold,
                critical_threshold=critical_threshold,
            )
            _usage_row = AIUsage(
                trace_id=trace_id,
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
                      trace_id=trace_id,
                      payload={"reason": _reason, "strong_model": _strong})
            persistence.save(role="sity", text=_proposal_text, trace_id=trace_id,
                             tone_meta=json.dumps(persona_decision.tone_snapshot))
            return local_tool_response(
                trace_id=trace_id,
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
                trace_id=trace_id,
                client_turn_id=request.client_turn_id,
            )

            if _loop.early_kind == "local_final":
                _usage_row = AIUsage(
                    trace_id=trace_id,
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
                    daily_budget=daily_budget,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                )
                write_log(
                    level="INFO",
                    module="cortex",
                    event="local_tool_response",
                    trace_id=trace_id,
                    payload={"tool": _loop.early_tool_name, "model": _loop.local_model},
                )
                persistence.save(role="sity", text=_loop.local_text, trace_id=trace_id,
                                 tone_meta=json.dumps(persona_decision.tone_snapshot))
                return local_tool_response(
                    trace_id=trace_id,
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
                _personality_dict = personality if isinstance(personality, dict) else {}
                _react_text = runner.run_micro_reaction(
                    event_type=_loop.sensor_event_type,
                    event_description=_loop.sensor_description,
                    personality=_personality_dict,
                    trace_id=trace_id,
                )
                write_log(
                    level="AUDIT",
                    module="senses",
                    event=_loop.sensor_event_type,
                    trace_id=trace_id,
                    payload={"tool": _loop.early_tool_name},
                    audit=True,
                )
                persistence.save(role="sity", text=_react_text, trace_id=trace_id,
                                 tone_meta=json.dumps(persona_decision.tone_snapshot))
                return micro_reaction_response(
                    trace_id=trace_id,
                    text=_react_text,
                    daily_used=get_today_token_usage(session),
                    daily_budget=daily_budget,
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
                trace_id=trace_id,
                payload={
                    "updated_parameters": updated_parameters,
                    "tool_results_count": len(tool_results_for_claude),
                },
            )

            personality = settings_service.get_personality()
            persona_decision = PersonaEngine().build_persona_prompt(personality, request.message)

    if tool_results_for_claude:
        response_after_tools = runner.run_after_tools(
            request=build_after_tools_ai_request(
                trace_id=trace_id,
                persona_prompt=persona_decision.system_prompt,
                user_message=user_message_with_history,
                max_tokens=max(max_tokens, 700),
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

    persistence.tag_sity_with_model(response.model)
    chat_result = build_final_ai_response(
        session=session,
        trace_id=trace_id,
        response=response,
        daily_budget=daily_budget,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        get_today_token_usage=get_today_token_usage,
        save_message=persistence.save,
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
            voice_settings=voice_settings,
            trace_id=trace_id,
        )
        if tts_result is not None:
            n_fragments, audio_filename = tts_result
            _tts_row = session.exec(
                select(ChatMessage).where(
                    ChatMessage.trace_id == trace_id,
                    ChatMessage.role == "sity",
                )
            ).first()
            if _tts_row is not None:
                _tts_row.tts_fragments = n_fragments
                _tts_row.audio_filename = audio_filename
                session.add(_tts_row)
                session.commit()
                write_log(level="INFO", module="audio", event="tts_db_committed",
                          trace_id=trace_id,
                          payload={"audio_filename": _tts_row.audio_filename,
                                   "tts_fragments": _tts_row.tts_fragments})

    return chat_result


def _should_synthesize(voice_response_mode: str, input_mode: str) -> bool:
    if voice_response_mode == "always":
        return True
    if voice_response_mode == "never":
        return False
    # symmetric: only when user input was voice
    return input_mode == "voice"


def _clean_text_for_tts(text: str) -> str:
    import re
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
    from app.api.schemas import ChatArtifact
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

"""AITurnPrep — AI context and infrastructure setup for one chat turn.

build_ai_turn_prep() handles everything between the pre-AI gates and the
first provider call: output-mode decision, prompt context, user message
persistence, local provider wiring, toolset selection, and routing.
The result is a plain dataclass accessed by the caller as prep.*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.api.schemas import ChatMessageRequest
from app.chat.chat_persistence import DEFAULT_CHAT_SESSION_ID, get_recent_db_messages
from app.chat.local_provider_config import resolve_local_provider_model
from app.chat.prompt_context import PromptContext, PromptContextBuilder
from app.chat.provider_call_runner import ProviderCallRunner
from app.chat.routing_decision import ChatRoutingDecision, build_chat_routing_decision
from app.chat.toolset_selector import (
    history_limit_for_message,
    message_mentions_file_path,
    select_toolset_with_metadata,
)
from app.chat.turn_context import TurnContext
from app.core.runtime_config import RuntimeConfig, get_runtime_config
from app.cortex.ai_gateway import AIGateway
from app.cortex.providers.factory import build_ai_provider
from app.settings.schemas import VoiceSettings
from app.trace.logger import write_log


def _should_synthesize(voice_response_mode: str, input_mode: str) -> bool:
    if voice_response_mode == "always":
        return True
    if voice_response_mode == "never":
        return False
    # symmetric: only when user input was voice
    return input_mode == "voice"


@dataclass
class AITurnPrep:
    output_mode: str
    should_synth: bool
    voice_settings: VoiceSettings
    prompt_context: PromptContext
    runner: ProviderCallRunner
    selected_tools: list[dict]  # type: ignore[type-arg]
    routing_decision: ChatRoutingDecision
    runtime_config: RuntimeConfig


def build_ai_turn_prep(
    *,
    session: Session,
    request: ChatMessageRequest,
    ctx: TurnContext,
    strong_model: str | None = None,
    skip_history_turns: int = 0,
    upgrade_context: str | None = None,  # noqa: ARG001 — reserved for Fase 4 ChatOrchestrator
    persona_prompt: str,  # noqa: ARG001 — reserved for Fase 4 ChatOrchestrator
) -> AITurnPrep:
    runtime_config = get_runtime_config()

    # Output mode — computed once, reused for prompt context AND TTS post-processing.
    should_synth = _should_synthesize(ctx.voice_settings.voice_response_mode, request.input_mode)
    output_mode = "voice" if should_synth else "text"
    write_log(
        level="INFO", module="audio", event="tts_decision",
        trace_id=ctx.trace_id,
        payload={
            "voice_response_mode": ctx.voice_settings.voice_response_mode,
            "input_mode": request.input_mode,
            "should_synth": should_synth,
        },
    )

    # Prompt context — history, prior_messages, planner variants.
    history_limit = history_limit_for_message(request.message)
    if message_mentions_file_path(request.message):
        history_limit = 2

    prompt_context = PromptContextBuilder(
        get_recent_messages=get_recent_db_messages,
    ).build(
        session=session,
        message=request.message,
        history_limit=history_limit,
        planner_history_limit=4,
        trace_id=ctx.trace_id,
        input_mode=request.input_mode,
        output_mode=output_mode,
        skip_last_turns=skip_history_turns,
    )

    write_log(
        level="INFO",
        module="chat",
        event="history_injected",
        trace_id=ctx.trace_id,
        payload={
            "session_id": DEFAULT_CHAT_SESSION_ID,
            "history_limit": history_limit,
            "history_count": len(prompt_context.recent_history),
            "planner_history_count": len(prompt_context.planner_history),
        },
    )

    # Voice edit distance — only computed when a transcript correction was applied.
    _voice_edit_pct: float | None = None
    if request.input_mode == "voice" and request.voice_transcript_original:
        from app.audio.edit_distance import compute_edit_distance_pct
        _voice_edit_pct = compute_edit_distance_pct(
            request.voice_transcript_original, request.message
        )
        write_log(
            level="INFO",
            module="audio",
            event="voice_input",
            trace_id=ctx.trace_id,
            payload={
                "input_mode": "voice",
                "edit_distance_pct": _voice_edit_pct,
                "original_len": len(request.voice_transcript_original),
                "final_len": len(request.message),
            },
        )

    # Persist the user message before any provider call.
    ctx.persistence.save(
        role="user",
        text=request.message,
        trace_id=ctx.trace_id,
        input_mode=request.input_mode,
        voice_transcript_original=request.voice_transcript_original,
        edit_distance_pct=_voice_edit_pct,
        source_channel=request.source_channel,
    )

    # Local provider — only when SITY_LOCAL_AI_ENABLED=true.
    # SITY_AI_PROVIDER is the cloud provider (anthropic); local provider is separate.
    # SITY_OLLAMA_MODEL must be set explicitly — never fall back to the cloud model name.
    _local_provider = None
    if runtime_config.local_ai_enabled:
        _ollama_model = resolve_local_provider_model(runtime_config)
        if _ollama_model is None:
            write_log(
                level="ERROR",
                module="chat",
                event="local_ai_misconfigured",
                trace_id=ctx.trace_id,
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

    runner = ProviderCallRunner(
        AIGateway(config=ctx.config, model_override=strong_model),
        local_provider=_local_provider,
    )

    # Toolset selection and special tool injection.
    toolset_selection = select_toolset_with_metadata(request.message, input_mode=request.input_mode)
    selected_tools: list[Any] = list(toolset_selection.tools)

    # Inject read_own_trace only when dataset_source == "debug_test".
    if ctx.capture_ctx.dataset_source == "debug_test":
        from app.cortex.tool_schemas import READ_OWN_TRACE_TOOL
        if not any(t.get("name") == "read_own_trace" for t in selected_tools):
            selected_tools = selected_tools + [READ_OWN_TRACE_TOOL]

    # Inject propose_model_upgrade when model_router_enabled, but NOT on strong-model re-runs
    # (strong_model is set) to prevent Sonnet from proposing a further upgrade.
    if ctx.ai_config.get("claude", {}).get("model_router_enabled", False) and not strong_model:
        from app.cortex.tool_schemas import PROPOSE_MODEL_UPGRADE_TOOL
        if not any(t.get("name") == "propose_model_upgrade" for t in selected_tools):
            selected_tools = selected_tools + [PROPOSE_MODEL_UPGRADE_TOOL]

    routing_decision = build_chat_routing_decision(
        message=request.message,
        selection=toolset_selection,
        local_ai_enabled=runtime_config.local_ai_enabled,
    )

    write_log(
        level="INFO",
        module="chat",
        event="routing_decision",
        trace_id=ctx.trace_id,
        payload={
            "provider_mode": routing_decision.provider_mode.value,
            "activated_domains": sorted(toolset_selection.activated_domains),
            "reasons": toolset_selection.reasons,
            "local_ai_enabled": routing_decision.local_ai_enabled,
            "reason": routing_decision.reason,
        },
    )

    return AITurnPrep(
        output_mode=output_mode,
        should_synth=should_synth,
        voice_settings=ctx.voice_settings,
        prompt_context=prompt_context,
        runner=runner,
        selected_tools=selected_tools,
        routing_decision=routing_decision,
        runtime_config=runtime_config,
    )

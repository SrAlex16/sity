"""Chat turn execution — background worker and inner turn handler.

_run_turn_in_background: thread-pool worker launched by POST /chat/message.
    Runs the full turn, publishes SSE done/error, dispatches background notification.

_chat_message_inner: builds turn context, applies refusal gate, invokes orchestrator.
"""
from __future__ import annotations

import json

from sqlmodel import Session

from app.api.schemas import ChatMessageRequest, ChatMessageResponse
from app.chat.chat_persistence import DEFAULT_CHAT_SESSION_ID
from app.chat.model_router import LocalFlowSignal, clear_proposal
from app.core.cancellation import clear_operation
from app.core.order_override import has_direct_order_override
from app.core.persona_engine import PersonaEngine
from app.core.realtime_events import get_subscriber_state, publish_event_sync
from app.core.refusal_tracker import clear_last_refusal, get_last_refusal, set_last_refusal
from app.trace.logger import write_log


def _snippet(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, cutting at the last word boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rfind(" ")
    return text[:cut] if cut > 0 else text[:max_chars]


def _maybe_dispatch_chat_response(
    result: "ChatMessageResponse",
    session_id: str,
    db: "Session",
) -> None:
    """Dispatch a chat_response notification when the tab is not in the foreground.

    The ChatMessage was already persisted by build_final_ai_response — this only
    handles delivery (session SSE queue + optional Web Push). Skipped when visible
    because the user already sees the response live through the per-turn SSE stream.
    chat_response has no dispatcher rate limit (user-triggered, same as timer_fired).
    """
    from app.notifications.dispatcher import dispatch
    from app.notifications.fact import NotificationFact

    state = get_subscriber_state(session_id)
    if state == "visible":
        return

    text = result.text or ""
    snippet = _snippet(text, 80)
    trace_id = result.trace_id or ""

    fact = NotificationFact(
        session_id=session_id,
        notification_type="chat_response",
        fact_id=f"chat_response:{trace_id}",
        payload={"title": "Sity", "body": snippet, "url": "/", "urgent": False},
        urgency="medium",
        subtype="chat_response",
    )
    try:
        dispatch(fact, db)
    except Exception as exc:
        write_log(
            level="WARN",
            module="chat",
            event="chat_response_dispatch_failed",
            trace_id=trace_id,
            payload={"error": str(exc), "session_id": session_id},
        )


def _run_turn_in_background(request: ChatMessageRequest, turn_id: str, session_id: str = DEFAULT_CHAT_SESSION_ID, is_admin: bool = False) -> None:
    """Worker that runs the full chat turn in a thread pool and publishes
    the result (or error) as SSE events before closing with 'done'."""
    from app.memory.db import engine

    # Ensure client_turn_id is always the resolved turn_id so downstream
    # is_cancelled() checks work (frontend never sends client_turn_id in body).
    if request.client_turn_id != turn_id:
        request = request.model_copy(update={"client_turn_id": turn_id})

    with Session(engine) as session:
        try:
            result = _chat_message_inner(request=request, session=session, _session_id=session_id, _is_admin=is_admin)
            if isinstance(result, LocalFlowSignal) and result.kind == "model_upgrade_accepted":
                original_message = result.original_message
                strong_model = result.strong_model
                forced_tools = result.selected_tools or None
                write_log(
                    level="INFO", module="chat", event="model_upgrade_accepted",
                    trace_id=turn_id,
                    payload={"original_message": original_message[:80], "strong_model": strong_model},
                )
                upgraded = request.model_copy(update={"message": original_message})
                clear_proposal()
                write_log(
                    level="INFO", module="chat", event="model_upgrade_rerun",
                    trace_id=turn_id,
                    payload={"strong_model": strong_model, "message_len": len(original_message)},
                )
                _upgrade_ctx = (
                    "CONTEXTO DE UPGRADE: El usuario ya confirmó usar el modelo más potente para esta tarea. "
                    "Ejecuta la tarea directamente sin volver a preguntar ni proponer cambios de modelo. "
                    "No menciones el cambio de modelo — simplemente responde a la tarea."
                )
                result = _chat_message_inner(
                    request=upgraded,
                    session=session,
                    _strong_model=strong_model,
                    _skip_history_turns=3,
                    _upgrade_context=_upgrade_ctx,
                    _session_id=session_id,
                    _forced_tools=forced_tools,
                    _is_admin=is_admin,
                )
            # Skip "response" event for cancelled turns — the frontend already
            # shows a cancelled bubble from the abort handler; emitting here
            # would cause a duplicate or overwrite it with the empty text.
            if getattr(result, "error_type", None) != "cancelled":
                publish_event_sync(turn_id, {
                    "type": "response",
                    "data": result.model_dump(mode="json"),
                })
                # Paso C: notify when tab is in background or absent.
                # The ChatMessage is already in DB at this point (persisted by
                # build_final_ai_response). Dispatcher handles channel selection.
                if not getattr(result, "error_type", None) and getattr(result, "text", None):
                    _maybe_dispatch_chat_response(result, session_id, session)
        except Exception:
            publish_event_sync(turn_id, {"type": "error", "label": "Error procesando la petición."})
        finally:
            publish_event_sync(turn_id, {"type": "done"})
            clear_operation(turn_id)


def _chat_message_inner(
    *,
    request: ChatMessageRequest,
    session: Session,
    _strong_model: str | None = None,
    _skip_history_turns: int = 0,
    _upgrade_context: str | None = None,
    _session_id: str = DEFAULT_CHAT_SESSION_ID,
    _forced_tools: list[dict] | None = None,
    _is_admin: bool = False,
):
    from app.chat.turn_context import build_turn_context
    from app.chat.pre_ai_flow import ChatPreAIFlow
    from app.chat.ai_turn_prep import build_ai_turn_prep
    from app.chat.ai_orchestrator import ChatAIOrchestrator

    ctx = build_turn_context(session, request, _strong_model, session_id=_session_id, is_admin=_is_admin)

    persona_decision = PersonaEngine().build_persona_prompt(ctx.personality, request.message, session_id=ctx.session_id, language_override=ctx.language_override, is_admin=ctx.is_admin)

    # Classify the message when refusal_mode is active:
    # - trivial messages bypass refusal_mode entirely.
    # - config_query bypasses refusal_mode; main model answers with verified values.
    # This is a structural check — the main model has no vote on this decision.
    _classification = None
    if persona_decision.refusal_mode:
        from app.core.message_classifier import classify_message
        _last_refusal_data = get_last_refusal(ctx.session_id)
        _classification = classify_message(
            request.message,
            trace_id=ctx.trace_id,
            last_was_refusal=_last_refusal_data is not None,
        )
        if not _classification.is_real_request:
            # Trivial message — reset refusal_mode.
            persona_decision = PersonaEngine().build_persona_prompt(
                ctx.personality, request.message,
                refusal_mode_override=False,
                session_id=ctx.session_id,
                language_override=ctx.language_override,
                is_admin=ctx.is_admin,
            )

    persona_prompt = persona_decision.system_prompt

    # Config query: inject verified parameter values so the model cannot hallucinate them.
    if _classification is not None and _classification.is_config_query:
        from app.core.message_classifier import build_verified_config_block
        persona_prompt += build_verified_config_block(ctx.personality)

    if _upgrade_context:
        persona_prompt += f"\n\n{_upgrade_context}"

    # Extract override flag once — used both for prompt injection and refusal gate.
    _has_override = has_direct_order_override(request.message)
    if _has_override:
        last = get_last_refusal(ctx.session_id)
        if last:
            persona_prompt += (
                "\n\nCONTEXTO DE OVERRIDE: El usuario está ordenando ejecutar esta petición "
                "que fue rechazada antes por personalidad:\n"
                f"\"{last['user_message']}\"\n\n"
                "Responde a esa petición ahora. Mantén tu personalidad y tono, "
                "pero no rechaces por refusal_mode. La seguridad y las allowlists siguen activas."
            )

    pre_ai = ChatPreAIFlow(session, ctx)
    if response := pre_ai.try_handle(request):
        return response

    # STRUCTURAL REFUSAL: when refusal_mode is active for a real (non-config) request
    # and no valid override exists, the main model never sees this turn.
    # Haiku generates a personality-driven refusal directly.
    if (
        persona_decision.refusal_mode
        and _classification is not None
        and _classification.is_real_request
        and not _classification.is_config_query
        and not _has_override
    ):
        from app.core.message_classifier import generate_refusal_response
        from app.chat.chat_persistence import get_today_token_usage
        from app.chat.response_factory import refusal_response

        refusal_text = generate_refusal_response(
            ctx.personality, request.message, trace_id=ctx.trace_id,
        )
        ctx.persistence.save(
            role="user",
            text=request.message,
            trace_id=ctx.trace_id,
            input_mode=request.input_mode,
            voice_transcript_original=request.voice_transcript_original,
            source_channel=request.source_channel,
        )
        ctx.persistence.save(
            role="sity",
            text=refusal_text,
            trace_id=ctx.trace_id,
            source_channel=request.source_channel,
        )
        set_last_refusal(
            session_id=ctx.session_id,
            user_message=request.message,
            assistant_message=refusal_text,
            trace_id=ctx.trace_id,
        )
        write_log(
            level="INFO",
            module="chat",
            event="structural_refusal_generated",
            trace_id=ctx.trace_id,
            payload={
                "message_length": len(request.message),
                "refusal_length": len(refusal_text),
            },
        )
        return refusal_response(
            trace_id=ctx.trace_id,
            text=refusal_text,
            daily_used=get_today_token_usage(session),
            daily_budget=ctx.daily_budget,
        )

    # Non-refusal turn: clear the per-session refusal state so the next turn
    # does not receive stale "last was refusal" context.
    clear_last_refusal(ctx.session_id)

    prep = build_ai_turn_prep(
        session=session,
        request=request,
        ctx=ctx,
        strong_model=_strong_model,
        skip_history_turns=_skip_history_turns,
        persona_prompt=persona_prompt,
        persona_decision=persona_decision,
        forced_tools=_forced_tools,
    )

    orchestrator = ChatAIOrchestrator(
        session=session,
        ctx=ctx,
        prep=prep,
        request=request,
        persona_prompt=persona_prompt,
        persona_decision=persona_decision,
    )
    return orchestrator.run()

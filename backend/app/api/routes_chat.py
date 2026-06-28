from fastapi import APIRouter, Depends
from sqlmodel import Session, col, select

from app.api.schemas import (
    ChatMessageItem,
    ChatMessageRequest,
    ChatMessageResponse,
    CurrentChatResponse,
)
from app.chat.chat_persistence import (
    DEFAULT_CHAT_SESSION_ID,
    get_or_create_default_chat_session,
)
from app.chat.model_router import LocalFlowSignal, clear_proposal
from app.chat.ai_turn_prep import _should_synthesize  # noqa: F401
from app.chat.ai_orchestrator import (  # noqa: F401
    _attach_tts_artifacts,
    _clean_text_for_tts,
)

from app.core.cancellation import clear_operation, register_operation
from app.core.order_override import has_direct_order_override
from app.core.persona_engine import PersonaEngine
from app.core.realtime_events import publish_event_sync
from app.core.refusal_tracker import get_last_refusal

from app.memory.db import get_session
from app.memory.models import ChatMessage
from app.trace.logger import write_log


router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/current", response_model=CurrentChatResponse)
def current_chat(session: Session = Depends(get_session)):
    get_or_create_default_chat_session(session)

    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == DEFAULT_CHAT_SESSION_ID)
        .order_by(col(ChatMessage.id).desc())
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
            original_message = result.original_message
            strong_model = result.strong_model
            write_log(level="INFO", module="chat", event="model_upgrade_accepted",
                      trace_id="outer",
                      payload={"original_message": original_message[:80],
                               "strong_model": strong_model})
            upgraded = request.model_copy(update={"message": original_message})
            clear_proposal()
            write_log(level="INFO", module="chat", event="model_upgrade_rerun",
                      trace_id="outer",
                      payload={"strong_model": strong_model,
                               "message_len": len(original_message)})
            _upgrade_ctx = (
                "CONTEXTO DE UPGRADE: El usuario ya confirmó usar el modelo más potente para esta tarea. "
                "Ejecuta la tarea directamente sin volver a preguntar ni proponer cambios de modelo. "
                "No menciones el cambio de modelo — simplemente responde a la tarea."
            )
            result = _chat_message_inner(
                request=upgraded, session=session, _strong_model=strong_model,
                _skip_history_turns=2, _upgrade_context=_upgrade_ctx,
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
    _skip_history_turns: int = 0,
    _upgrade_context: str | None = None,
):
    from app.chat.turn_context import build_turn_context
    from app.chat.pre_ai_flow import ChatPreAIFlow
    from app.chat.ai_turn_prep import build_ai_turn_prep
    from app.chat.ai_orchestrator import ChatAIOrchestrator

    ctx = build_turn_context(session, request, _strong_model)

    persona_decision = PersonaEngine().build_persona_prompt(ctx.personality, request.message)
    persona_prompt = persona_decision.system_prompt

    if _upgrade_context:
        persona_prompt += f"\n\n{_upgrade_context}"

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

    pre_ai = ChatPreAIFlow(session, ctx)
    if response := pre_ai.try_handle(request):
        return response

    prep = build_ai_turn_prep(
        session=session,
        request=request,
        ctx=ctx,
        strong_model=_strong_model,
        skip_history_turns=_skip_history_turns,
        persona_prompt=persona_prompt,
        persona_decision=persona_decision,
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

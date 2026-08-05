from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from app.api.schemas import (
    ChatImageInput,
    ChatMessageItem,
    ChatMessageRequest,
    ChatMessageResponse,
    CurrentChatResponse,
)
from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.ip_rate_limiter import get_guest_ip_rate_limiter, get_real_client_ip
from app.chat.chat_persistence import (
    DEFAULT_CHAT_SESSION_ID,
    get_or_create_chat_session,
)
from app.chat.model_router import LocalFlowSignal, clear_proposal
from app.chat.ai_turn_prep import _should_synthesize  # noqa: F401
from app.chat.ai_orchestrator import (  # noqa: F401
    _attach_tts_artifacts,
    _clean_text_for_tts,
)

from app.core.cancellation import cancel_operation, clear_operation, register_operation
from app.core.order_override import has_direct_order_override
from app.core.persona_engine import PersonaEngine
from app.core.realtime_events import (
    ensure_queue,
    new_client_turn_id,
    publish_event_sync,
    subscribe,
)
from app.core.refusal_tracker import get_last_refusal

from app.memory.db import get_session
from app.memory.models import ChatMessage
from app.trace.logger import write_log


router = APIRouter(prefix="/chat", tags=["chat"])

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def _validate_images(images: list[ChatImageInput]) -> str | None:
    import base64
    for img in images:
        if img.media_type not in _ALLOWED_IMAGE_TYPES:
            return f"Tipo de imagen no soportado: {img.media_type}"
        try:
            decoded_size = len(base64.b64decode(img.data, validate=True))
        except Exception:
            return "Imagen con datos base64 inválidos."
        if decoded_size > _MAX_IMAGE_BYTES:
            return "La imagen supera el límite de 5MB."
    return None


@router.get("/current", response_model=CurrentChatResponse)
def current_chat(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    session_id = current.session_id
    get_or_create_chat_session(session, session_id)

    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
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
        session_id=session_id,
        messages=messages,
    )


@router.post("/message", status_code=202)
async def chat_message(
    request: ChatMessageRequest,
    http_request: Request,
    current: CurrentUser = Depends(get_current_user),
):
    if err := _validate_images(request.images):
        raise HTTPException(status_code=400, detail=err)

    if current.is_guest:
        ip = get_real_client_ip(http_request)
        if not get_guest_ip_rate_limiter().is_allowed(ip):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes. Inténtalo de nuevo más tarde.",
            )

    turn_id = request.client_turn_id or new_client_turn_id()
    ensure_queue(turn_id)
    register_operation(turn_id)

    session_id = current.session_id
    is_admin = bool(current.user and current.user.role == "admin")
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _run_turn_in_background, request, turn_id, session_id, is_admin)

    # Return dict (not JSONResponse) so FastAPI merges dependency-set cookies
    # (e.g. sity_guest_session from get_current_user) into the actual 202 response.
    return {"turn_id": turn_id, "status": "processing"}


@router.get("/stream/{turn_id}")
async def chat_stream(turn_id: str):
    """SSE stream — subscribe here to receive the result of a POST /chat/message."""
    async def event_generator():
        async for event in subscribe(turn_id):
            if event is None:
                yield ": heartbeat\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stream/{turn_id}/cancel")
def cancel_stream(turn_id: str):
    ok = cancel_operation(turn_id)
    publish_event_sync(turn_id, {
        "type": "cancelled",
        "label": "Cancelando…",
        "message": "Has cancelado la operación.",
    })
    return {"ok": ok}


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

    persona_decision = PersonaEngine().build_persona_prompt(ctx.personality, request.message, session_id=ctx.session_id)
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

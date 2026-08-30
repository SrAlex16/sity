from __future__ import annotations

import asyncio
import json

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from app.api.schemas import (
    ChatImageInput,
    ChatMessageItem,
    ChatMessageRequest,
    CurrentChatResponse,
)
from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.ip_rate_limiter import get_guest_ip_rate_limiter, get_real_client_ip
from app.audio.tts_service import (  # noqa: F401  (re-exported for test backward compat)
    _attach_tts_artifacts,
    _clean_text_for_tts,
)
from app.chat.chat_persistence import get_or_create_chat_session
from app.chat.turn_runner import _run_turn_in_background
from app.core.cancellation import cancel_operation, register_operation
from app.core.realtime_events import (
    ensure_queue,
    new_client_turn_id,
    publish_event_sync,
    subscribe,
)
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


@router.get("/export")
def export_chat(
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida")

    rows = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == current.session_id)
        .order_by(col(ChatMessage.id))
    ).all()

    export_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "session_id": current.session_id,
        "messages": [
            {
                "role": row.role,
                "text": row.text,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }

    json_bytes = json.dumps(export_data, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="sity-conversacion.json"',
        },
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

    write_log(
        level="INFO",
        module="routes_chat",
        event="chat_message_received",
        turn_id=turn_id,
        payload={
            "client_turn_id": request.client_turn_id,
            "text_prefix": request.message[:120] if request.message else "",
            "text_len": len(request.message) if request.message else 0,
        },
    )

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



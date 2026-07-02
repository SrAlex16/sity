import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.cancellation import cancel_operation
from app.core.realtime_events import publish_event_sync, subscribe


router = APIRouter(prefix="/events", tags=["events"])


@router.get("/chat/{client_turn_id}")
async def chat_events(client_turn_id: str):
    async def event_stream():
        async for event in subscribe(client_turn_id):
            if event is None:
                yield ": heartbeat\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat/{client_turn_id}/cancel")
def cancel_chat_operation(client_turn_id: str):
    ok = cancel_operation(client_turn_id)
    publish_event_sync(client_turn_id, {
        "type": "cancelled",
        "label": "Cancelando…",
        "message": "Has cancelado la operación.",
    })
    return {"ok": ok}


@router.get("/chat/{client_turn_id}/test")
async def test_chat_event(client_turn_id: str):
    publish_event_sync(client_turn_id, {
        "type": "tool_started",
        "tool": "record_audio_sample",
        "label": "Grabando audio…",
        "can_cancel": True,
    })
    return {"ok": True}

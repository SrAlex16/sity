import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.cancellation import cancel_operation
from app.core.realtime_events import publish_event_sync, subscribe, subscribe_session


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


@router.get("/session/{session_id}")
async def session_events(session_id: str):
    """Persistent SSE stream for a chat session — never closes, emits job_done/job_error events."""
    async def event_stream():
        async for event in subscribe_session(session_id):
            if event is None:
                yield ": heartbeat\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/session/{session_id}/jobs")
def list_session_jobs(session_id: str):
    from app.core.job_manager import get_job_manager
    jobs = get_job_manager().list_for_session(session_id)
    return {
        "session_id": session_id,
        "jobs": [
            {
                "job_id": j.job_id,
                "tool_name": j.tool_name,
                "status": j.status,
                "error": j.error,
            }
            for j in jobs
        ],
        "active": sum(1 for j in jobs if j.status == "running"),
    }


@router.get("/session/{session_id}/test")
async def test_session_event(session_id: str):
    """Simula un job corto para verificar el pipeline SSE de sesión end-to-end."""
    import asyncio
    import uuid
    from app.core.realtime_events import publish_session_event

    job_id = f"test_{uuid.uuid4().hex[:8]}"
    await publish_session_event(session_id, {
        "type": "job_start",
        "job_id": job_id,
        "tool_name": "test_job",
        "label": "Tarea de prueba…",
    })

    async def _finish_after_delay():
        await asyncio.sleep(3)
        await publish_session_event(session_id, {
            "type": "job_done",
            "job_id": job_id,
            "tool_name": "test_job",
            "label": "Tarea completada",
        })

    asyncio.ensure_future(_finish_after_delay())
    return {"ok": True, "job_id": job_id}


@router.get("/chat/{client_turn_id}/test")
async def test_chat_event(client_turn_id: str):
    publish_event_sync(client_turn_id, {
        "type": "tool_started",
        "tool": "record_audio_sample",
        "label": "Grabando audio…",
        "can_cancel": True,
    })
    return {"ok": True}

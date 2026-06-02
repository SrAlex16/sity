from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.debug.schemas import LastTraceResponse, RecentEventsResponse, TraceEvent
from app.memory.db import get_session
from app.memory.models import ChatMessage
from app.trace.trace_reader import (
    get_events_by_trace_id,
    get_last_trace_id,
    get_recent_events,
)
from app.training.dataset_stats import compute_dataset_stats


router = APIRouter(prefix="/debug", tags=["debug"])

DEFAULT_CHAT_SESSION_ID = "default"


@router.get("/events/recent", response_model=RecentEventsResponse)
def recent_events(limit: int = Query(default=100, ge=1, le=500)):
    events = [TraceEvent(**event) for event in get_recent_events(limit=limit)]
    return RecentEventsResponse(ok=True, events=events)


@router.get("/last-trace", response_model=LastTraceResponse)
def last_trace():
    trace_id = get_last_trace_id()

    if not trace_id:
        return LastTraceResponse(ok=True, trace_id=None, events=[])

    events = [TraceEvent(**event) for event in get_events_by_trace_id(trace_id)]
    return LastTraceResponse(ok=True, trace_id=trace_id, events=events)


@router.get("/traces/{trace_id}", response_model=LastTraceResponse)
def trace_by_id(trace_id: str):
    events = [TraceEvent(**event) for event in get_events_by_trace_id(trace_id)]
    return LastTraceResponse(ok=True, trace_id=trace_id, events=events)


@router.get("/dataset-stats")
def dataset_stats(session: Session = Depends(get_session)):
    """Return read-only dataset statistics for the single Sity timeline.

    Computes usable user→Sity pairs, per-bucket counts and progress
    towards LoRA v1 targets.  No message text is returned in full.
    """
    messages = list(session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == DEFAULT_CHAT_SESSION_ID)
        .order_by(ChatMessage.id)
    ))
    stats = compute_dataset_stats(messages)
    return {"ok": True, **stats}

from fastapi import APIRouter, Query

from app.debug.schemas import LastTraceResponse, RecentEventsResponse, TraceEvent
from app.trace.trace_reader import (
    get_events_by_trace_id,
    get_last_trace_id,
    get_recent_events,
)


router = APIRouter(prefix="/debug", tags=["debug"])


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

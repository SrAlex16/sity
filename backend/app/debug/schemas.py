from typing import Any, Optional

from pydantic import BaseModel


class TraceEvent(BaseModel):
    timestamp: str
    level: str
    module: str
    event: str
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    payload: dict[str, Any] = {}


class RecentEventsResponse(BaseModel):
    ok: bool
    events: list[TraceEvent]


class LastTraceResponse(BaseModel):
    ok: bool
    trace_id: Optional[str]
    events: list[TraceEvent]

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, select
from typing import Optional

from app.debug.schemas import LastTraceResponse, RecentEventsResponse, TraceEvent
from app.memory.db import get_session
from app.memory.models import ChatMessage
from app.trace.trace_reader import (
    get_events_by_trace_id,
    get_last_trace_id,
    get_recent_events,
)
from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
from app.training.dataset_stats import compute_dataset_stats


router = APIRouter(prefix="/debug", tags=["debug"])

DEFAULT_CHAT_SESSION_ID = "default"


class DatasetCaptureRequest(BaseModel):
    enabled: bool
    dataset_source: str = "normal_use"
    speaker_label: Optional[str] = None
    speaker_source: Optional[str] = None
    speaker_confidence: Optional[float] = None
    dataset_eligible: bool = True
    dataset_tags: list[str] = []

    @field_validator("speaker_confidence")
    @classmethod
    def validate_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("speaker_confidence must be between 0 and 1")
        return v

    @field_validator("dataset_source")
    @classmethod
    def validate_source_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("dataset_source must not be empty")
        return v

    @model_validator(mode="after")
    def validate_enabled_requirements(self) -> "DatasetCaptureRequest":
        if self.enabled:
            if not self.speaker_source or not self.speaker_source.strip():
                raise ValueError("speaker_source is required when enabled=true")
        return self


def _ctx_to_response(ctx: DatasetCaptureContext) -> dict:
    return {
        "ok": True,
        "enabled": ctx.enabled,
        "dataset_source": ctx.dataset_source,
        "speaker_label": ctx.speaker_label,
        "speaker_source": ctx.speaker_source,
        "speaker_confidence": ctx.speaker_confidence,
        "dataset_eligible": ctx.dataset_eligible,
        "dataset_tags": ctx.dataset_tags,
        "updated_at": ctx.updated_at,
    }


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


@router.get("/dataset-capture")
def get_dataset_capture(session: Session = Depends(get_session)):
    """Return the current dataset capture context."""
    ctx = DatasetCaptureService(session).get()
    return _ctx_to_response(ctx)


@router.put("/dataset-capture")
def put_dataset_capture(
    body: DatasetCaptureRequest,
    session: Session = Depends(get_session),
):
    """Persist a new dataset capture context."""
    ctx = DatasetCaptureContext(
        enabled=body.enabled,
        dataset_source=body.dataset_source,
        speaker_label=body.speaker_label,
        speaker_source=body.speaker_source,
        speaker_confidence=body.speaker_confidence,
        dataset_eligible=body.dataset_eligible,
        dataset_tags=body.dataset_tags,
    )
    svc = DatasetCaptureService(session)
    svc.save(ctx)
    return _ctx_to_response(svc.get())


@router.post("/dataset-capture/disable")
def disable_dataset_capture(session: Session = Depends(get_session)):
    """Disable capture mode while preserving the remaining context fields."""
    ctx = DatasetCaptureService(session).disable()
    return _ctx_to_response(ctx)


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

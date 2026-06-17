from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import Session, func, select
from typing import Optional

from app.debug.schemas import LastTraceResponse, RecentEventsResponse, TraceEvent
from app.memory.db import get_session
from app.memory.models import AIUsage, ChatMessage
from app.settings.config_loader import load_default_config
from app.trace.trace_reader import (
    get_events_by_trace_id,
    get_last_trace_id,
    get_recent_events,
)
from app.chat.chat_persistence import DEFAULT_CHAT_SESSION_ID
from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
from app.training.dataset_stats import compute_dataset_stats
from app.training.demo_cleanup import run_demo_cleanup


router = APIRouter(prefix="/debug", tags=["debug"])


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
        "demo_start_at": ctx.demo_start_at,
    }


def _is_demo_active(ctx: DatasetCaptureContext) -> bool:
    return ctx.enabled and ctx.dataset_source == "demo_session"


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
    """Persist a new dataset capture context.

    Transitions out of demo_session trigger export + cleanup before saving.
    Transitioning into demo_session records demo_start_at automatically.
    """
    svc = DatasetCaptureService(session)
    old_ctx = svc.get()

    activating_demo = body.enabled and body.dataset_source == "demo_session"
    was_demo_active = _is_demo_active(old_ctx)
    deactivating_demo = was_demo_active and (not body.enabled or body.dataset_source != "demo_session")

    # Cleanup first — export then delete — before saving the new context
    if deactivating_demo and old_ctx.demo_start_at:
        result = run_demo_cleanup(old_ctx.demo_start_at)
        if result.error:
            raise HTTPException(status_code=500, detail=f"Demo cleanup failed: {result.error}")

    # Determine demo_start_at for the new context
    if activating_demo and not was_demo_active:
        new_demo_start_at: Optional[str] = datetime.now(timezone.utc).isoformat()
    elif activating_demo and was_demo_active:
        new_demo_start_at = old_ctx.demo_start_at  # preserve — user re-saved without leaving demo
    else:
        new_demo_start_at = None

    ctx = DatasetCaptureContext(
        enabled=body.enabled,
        dataset_source=body.dataset_source,
        speaker_label=body.speaker_label,
        speaker_source=body.speaker_source,
        speaker_confidence=body.speaker_confidence,
        dataset_eligible=body.dataset_eligible,
        dataset_tags=body.dataset_tags,
        demo_start_at=new_demo_start_at,
    )
    svc.save(ctx)
    return _ctx_to_response(svc.get())


@router.post("/dataset-capture/disable")
def disable_dataset_capture(session: Session = Depends(get_session)):
    """Disable capture mode. Triggers demo cleanup if demo_session was active."""
    svc = DatasetCaptureService(session)
    old_ctx = svc.get()

    if _is_demo_active(old_ctx) and old_ctx.demo_start_at:
        result = run_demo_cleanup(old_ctx.demo_start_at)
        if result.error:
            raise HTTPException(status_code=500, detail=f"Demo cleanup failed: {result.error}")

    ctx = svc.disable()  # clears demo_start_at internally
    return _ctx_to_response(ctx)


@router.get("/budget")
def budget(session: Session = Depends(get_session)):
    """Return today's token usage and the configured daily budget."""
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .replace(tzinfo=None)
    )
    result = session.exec(
        select(func.sum(AIUsage.input_tokens + AIUsage.output_tokens)).where(
            AIUsage.created_at >= today_start
        )
    ).one()
    used = int(result or 0)
    cfg = load_default_config()
    daily_budget = int(cfg.get("usage", {}).get("daily_token_budget", 1000000))
    return {"daily_used": used, "daily_budget": daily_budget}


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

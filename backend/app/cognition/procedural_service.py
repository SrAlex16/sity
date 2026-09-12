"""procedural_service.py — Memoria procedimental (Remake Fase 7).

Detects and maintains per-user behavioural patterns across similar turns.

Architecture (sección 27):
  1. Per-turn: insert ProceduralObservation (pure DB write, never blocks turn).
  2. Trigger: when unprocessed observations for (user_id, context_type) >= threshold,
     fire a daemon thread to synthesise or update a ProceduralPattern.
  3. Background synthesis: Haiku reads observation excerpts + existing pattern
     → generates/updates strategy_description, bumps confidence + occurrence_count,
     marks observations processed.
  4. Decision integration (Paso 2): load_active_patterns() returns patterns for
     context-aware score adjustments in compute_utility_scores().

Isolation invariant: ProceduralObservation and ProceduralPattern rows are always
filtered by user_id. A pattern from user A can NEVER influence user B.

Confidence formula: min(0.85, 0.45 + (occurrence_count - 3) * 0.04)
  occurrence_count=3  → 0.45 (created, below Decision threshold)
  occurrence_count=6  → 0.57
  occurrence_count=9  → 0.69  (typically enough to influence Decision)
  occurrence_count=12 → 0.81
  occurrence_count≥13 → 0.85 (cap — procedural knowledge is never certain)

Never raises — returns None / empty list on any error.
"""
from __future__ import annotations

import json
import os
import threading

from sqlalchemy import func
from sqlmodel import Session, select

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.db import engine
from app.memory.models import ProceduralObservation, ProceduralPattern, utc_now
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Minimum unprocessed observations before pattern synthesis fires
_PROCEDURAL_THRESHOLD: int = 3

# Confidence threshold for patterns to influence Decision (Paso 2)
PROCEDURAL_CONFIDENCE_MIN: float = 0.55

_SYNTHESIS_SYSTEM = (
    "You are Sity's procedural memory module. Your task is to extract a short behavioural "
    "pattern from a set of conversation excerpts of the same type.\n\n"
    "Given the context_type and a list of user message excerpts (what the user typically "
    "says in this kind of interaction), identify ONE concise strategy that Sity should "
    "apply in future interactions of this type.\n\n"
    "If an existing strategy is provided, refine it rather than replacing it entirely.\n\n"
    "Return ONLY a single short sentence (max 120 characters) describing the strategy. "
    "No JSON, no explanation, no prefix — just the strategy text.\n\n"
    "Examples of good strategy descriptions:\n"
    "- 'Prefer showing trade-offs before implementation details in design discussions'\n"
    "- 'Ask one clarifying question before diving into debugging steps'\n"
    "- 'Keep explanations concise; user grasps concepts quickly'\n"
    "- 'Use concrete code examples rather than abstract descriptions'\n\n"
    "Output only the strategy sentence."
)


# ---------------------------------------------------------------------------
# Confidence formula
# ---------------------------------------------------------------------------

def _compute_confidence(occurrence_count: int) -> float:
    return min(0.85, 0.45 + max(0, occurrence_count - 3) * 0.04)


# ---------------------------------------------------------------------------
# Per-turn: record observation
# ---------------------------------------------------------------------------

def record_observation(
    session: Session,
    *,
    user_id: int,
    context_type: str,
    user_message: str,
    trace_id: str = "",
) -> int:
    """Insert one ProceduralObservation and return count of unprocessed for this (user_id, context_type).

    Called from turn_cognition Step 15. Never raises.
    """
    try:
        obs = ProceduralObservation(
            user_id=user_id,
            context_type=context_type,
            user_message_excerpt=user_message[:100],
            trace_id=trace_id,
        )
        session.add(obs)
        session.commit()

        unprocessed: int = session.exec(  # type: ignore[assignment]
            select(func.count()).select_from(ProceduralObservation)
            .where(ProceduralObservation.user_id == user_id)
            .where(ProceduralObservation.context_type == context_type)
            .where(ProceduralObservation.processed == False)  # noqa: E712
        ).one()
        return int(unprocessed)
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="procedural_observation_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return 0


# ---------------------------------------------------------------------------
# Background: pattern synthesis
# ---------------------------------------------------------------------------

def _synthesise_strategy(
    context_type: str,
    excerpts: list[str],
    existing_strategy: str,
    trace_id: str,
) -> str | None:
    """Call Haiku to generate/refine a strategy_description. Returns None on failure."""
    user_msg = (
        f"context_type: {context_type}\n\n"
        f"Recent excerpts:\n"
        + "\n".join(f"- {e}" for e in excerpts)
    )
    if existing_strategy:
        user_msg += f"\n\nExisting strategy (refine, do not discard): {existing_strategy}"

    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="procedural_synthesis",
            system_prompt=_SYNTHESIS_SYSTEM,
            user_message=user_msg,
            max_tokens=150,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            return response.text.strip()[:500]
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="procedural_synthesis_haiku_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return None


def _run_pattern_synthesis(user_id: int, context_type: str, trace_id: str) -> None:
    """Background daemon: synthesise or update ProceduralPattern for (user_id, context_type).

    Opens its own Session. Never raises — logs WARN and returns on any error.
    Isolation invariant: all queries are filtered by user_id.
    """
    try:
        with Session(engine) as db:
            # Load unprocessed observations (up to 5 most recent)
            obs_rows = db.exec(
                select(ProceduralObservation)
                .where(ProceduralObservation.user_id == user_id)
                .where(ProceduralObservation.context_type == context_type)
                .where(ProceduralObservation.processed == False)  # noqa: E712
                .order_by(ProceduralObservation.created_at.desc())  # type: ignore[attr-defined]
                .limit(5)
            ).all()

            if not obs_rows:
                return

            excerpts = [r.user_message_excerpt for r in obs_rows if r.user_message_excerpt]
            new_trace_ids = [r.trace_id for r in obs_rows if r.trace_id]

            # Load existing active pattern for this (user_id, context_type)
            existing = db.exec(
                select(ProceduralPattern)
                .where(ProceduralPattern.user_id == user_id)
                .where(ProceduralPattern.context_type == context_type)
                .where(ProceduralPattern.is_active == True)  # noqa: E712
            ).first()

            existing_strategy = existing.strategy_description if existing else ""

            strategy = _synthesise_strategy(context_type, excerpts, existing_strategy, trace_id)
            if not strategy:
                return

            # Merge evidence trails
            old_trail: list[str] = json.loads(existing.evidence_trail_json) if existing else []
            merged_trail = list(dict.fromkeys(old_trail + new_trace_ids))[:50]

            if existing is not None:
                existing.strategy_description = strategy
                existing.occurrence_count += len(obs_rows)
                existing.confidence = _compute_confidence(existing.occurrence_count)
                existing.evidence_trail_json = json.dumps(merged_trail, ensure_ascii=False)
                existing.last_observed_at = utc_now()
                db.add(existing)
            else:
                pattern = ProceduralPattern(
                    user_id=user_id,
                    context_type=context_type,
                    strategy_description=strategy,
                    confidence=_compute_confidence(len(obs_rows)),
                    evidence_trail_json=json.dumps(merged_trail, ensure_ascii=False),
                    occurrence_count=len(obs_rows),
                    last_observed_at=utc_now(),
                )
                db.add(pattern)

            # Mark observations as processed
            for obs in obs_rows:
                obs.processed = True
                db.add(obs)

            db.commit()

            write_log(
                level="INFO",
                module="cognition",
                event="procedural_pattern_updated",
                trace_id=trace_id,
                payload={
                    "user_id": user_id,
                    "context_type": context_type,
                    "occurrence_count": (existing.occurrence_count if existing else len(obs_rows)),
                    "confidence": round(_compute_confidence(
                        existing.occurrence_count if existing else len(obs_rows)
                    ), 3),
                },
            )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="procedural_pattern_synthesis_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "context_type": context_type, "error": str(exc)[:200]},
        )


# ---------------------------------------------------------------------------
# Public trigger (called from turn_cognition)
# ---------------------------------------------------------------------------

def maybe_trigger_pattern_synthesis(
    session: Session,
    *,
    user_id: int,
    context_type: str,
    user_message: str,
    trace_id: str = "",
) -> None:
    """Record observation and fire background synthesis if threshold reached.

    Called from turn_cognition Step 15. Never raises. Non-blocking.
    """
    unprocessed = record_observation(
        session,
        user_id=user_id,
        context_type=context_type,
        user_message=user_message,
        trace_id=trace_id,
    )

    if unprocessed >= _PROCEDURAL_THRESHOLD:
        threading.Thread(
            target=_run_pattern_synthesis,
            args=(user_id, context_type, trace_id),
            daemon=True,
        ).start()
        write_log(
            level="INFO",
            module="cognition",
            event="procedural_synthesis_triggered",
            trace_id=trace_id,
            payload={"user_id": user_id, "context_type": context_type, "unprocessed": unprocessed},
        )


# ---------------------------------------------------------------------------
# Decision integration (Paso 2)
# ---------------------------------------------------------------------------

def load_active_patterns(
    session: Session,
    *,
    user_id: int,
    context_type: str,
    min_confidence: float = PROCEDURAL_CONFIDENCE_MIN,
) -> list[ProceduralPattern]:
    """Load active ProceduralPattern rows for (user_id, context_type) above confidence threshold.

    Isolation invariant: always filtered by user_id — patterns from other users are never returned.
    Returns empty list on any error.
    """
    try:
        return list(session.exec(
            select(ProceduralPattern)
            .where(ProceduralPattern.user_id == user_id)
            .where(ProceduralPattern.context_type == context_type)
            .where(ProceduralPattern.is_active == True)  # noqa: E712
            .where(ProceduralPattern.confidence >= min_confidence)
        ).all())
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="procedural_load_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return []

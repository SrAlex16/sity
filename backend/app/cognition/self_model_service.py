"""self_model_service.py — DB operations for SelfModel, SelfBelief, SityValues (Fase 6).

Public API:
  get_or_create_self_model   — singleton SelfModel row (global, not per-user)
  get_or_create_sity_values  — singleton SityValues row (global, not per-user)
  load_values_dict           — {value_autonomy: float, ...} convenience wrapper
  get_active_beliefs         — active SelfBelief rows for a SelfModel
  add_belief_candidate       — create a new SelfBelief with evidence entry
  update_belief_confidence   — adjust confidence + append to evidence_trail
  deactivate_belief          — mark a belief is_active=False (superseded/retracted)

Design principle (sección 57):
  Beliefs from metacognition enter with confidence ≤ 0.40 and source="metacognition".
  They are NEVER auto-applied as facts — the caller is responsible for deciding
  whether to promote a candidate. This module only provides the persistence layer.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.memory.models import SelfBelief, SelfModel, SityValues, utc_now


# ---------------------------------------------------------------------------
# SelfModel singleton
# ---------------------------------------------------------------------------

def get_or_create_self_model(session: Session) -> SelfModel:
    """Return the unique global SelfModel row, creating it if absent."""
    row = session.exec(select(SelfModel)).first()
    if row is None:
        row = SelfModel()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# SityValues singleton
# ---------------------------------------------------------------------------

def get_or_create_sity_values(session: Session) -> SityValues:
    """Return the unique global SityValues row, creating it if absent."""
    row = session.exec(select(SityValues)).first()
    if row is None:
        row = SityValues()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def load_values_dict(session: Session) -> dict[str, float]:
    """Return SityValues as a plain dict keyed by value_ field names.

    Always returns all 6 values. Creates the singleton row if absent.
    """
    v = get_or_create_sity_values(session)
    return {
        "value_autonomy":    v.value_autonomy,
        "value_honesty":     v.value_honesty,
        "value_helpfulness": v.value_helpfulness,
        "value_curiosity":   v.value_curiosity,
        "value_fairness":    v.value_fairness,
        "value_loyalty":     v.value_loyalty,
    }


# ---------------------------------------------------------------------------
# SelfBelief operations
# ---------------------------------------------------------------------------

def get_active_beliefs(session: Session, self_model_id: int) -> list[SelfBelief]:
    """Return all is_active SelfBelief rows for self_model_id, ordered by created_at."""
    return list(session.exec(
        select(SelfBelief)
        .where(SelfBelief.self_model_id == self_model_id, SelfBelief.is_active == True)  # noqa: E712
        .order_by(SelfBelief.id)  # type: ignore[arg-type]
    ).all())


def add_belief_candidate(
    session: Session,
    *,
    self_model_id: int,
    proposition: str,
    confidence: float = 0.40,
    source: str = "metacognition",
    trace_id: str = "",
    evidence_type: str = "reflection",
    evidence_description: str = "",
) -> SelfBelief:
    """Create a new SelfBelief with an initial evidence entry.

    confidence defaults to 0.40 for metacognition candidates (sección 57 principle).
    Use source="initial" or "configuration" for seed beliefs with higher confidence.
    """
    evidence: list[dict] = []
    if trace_id or evidence_description:
        evidence.append({
            "trace_id": trace_id,
            "type": evidence_type,
            "description": evidence_description,
        })
    belief = SelfBelief(
        self_model_id=self_model_id,
        proposition=proposition,
        confidence=max(0.0, min(1.0, confidence)),
        source=source,
        evidence_trail_json=json.dumps(evidence),
    )
    session.add(belief)
    session.commit()
    session.refresh(belief)
    return belief


def update_belief_confidence(
    session: Session,
    *,
    belief_id: int,
    new_confidence: float,
    trace_id: str = "",
    evidence_type: str = "reflection",
    evidence_description: str = "",
) -> SelfBelief | None:
    """Update confidence for an existing SelfBelief and append an evidence entry.

    Returns the updated belief, or None if belief_id not found.
    """
    belief = session.get(SelfBelief, belief_id)
    if belief is None:
        return None
    belief.confidence = max(0.0, min(1.0, new_confidence))
    if trace_id or evidence_description:
        trail: list[dict] = json.loads(belief.evidence_trail_json)
        trail.append({
            "trace_id": trace_id,
            "type": evidence_type,
            "description": evidence_description,
        })
        belief.evidence_trail_json = json.dumps(trail)
    belief.updated_at = utc_now()
    session.add(belief)
    session.commit()
    session.refresh(belief)
    return belief


def add_self_model_observation(
    session: Session,
    observation: str,
    *,
    trace_id: str = "",
) -> SelfBelief | None:
    """Create or reinforce a SelfBelief from a self_model_update string (Punto 6).

    confidence=0.30 for new entries (lower than belief_updates' 0.40 — self-model
    observations are more tentative). Matches existing beliefs by exact proposition.
    Returns None on any error.
    """
    prop_clean = observation.strip()[:300]
    if not prop_clean:
        return None
    try:
        sm = get_or_create_self_model(session)
        if sm.id is None:
            return None

        existing = session.exec(
            select(SelfBelief)
            .where(SelfBelief.self_model_id == sm.id)
            .where(SelfBelief.proposition == prop_clean)
            .where(SelfBelief.is_active == True)  # noqa: E712
        ).first()

        if existing is not None and existing.id is not None:
            return update_belief_confidence(
                session,
                belief_id=existing.id,
                new_confidence=min(1.0, existing.confidence + 0.05),
                trace_id=trace_id,
                evidence_type="self_model_reflection",
                evidence_description=f"repeated: {prop_clean[:60]}",
            )

        return add_belief_candidate(
            session,
            self_model_id=sm.id,
            proposition=prop_clean,
            confidence=0.30,
            source="self_model_reflection",
            trace_id=trace_id,
            evidence_type="self_model_reflection",
            evidence_description="first observation",
        )
    except Exception:
        return None


def deactivate_belief(session: Session, belief_id: int) -> None:
    """Mark a SelfBelief as inactive (superseded or retracted). No-op if not found."""
    belief = session.get(SelfBelief, belief_id)
    if belief is not None:
        belief.is_active = False
        belief.updated_at = utc_now()
        session.add(belief)
        session.commit()

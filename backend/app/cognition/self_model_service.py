"""self_model_service.py — DB operations for SelfModel, SelfBelief, SityValues (Fase 6).

Public API:
  get_or_create_self_model   — singleton SelfModel row (global, not per-user)
  get_or_create_sity_values  — singleton SityValues row (global, not per-user)
  load_values_dict           — {value_autonomy: float, ...} convenience wrapper
  get_active_beliefs         — active SelfBelief rows for a SelfModel
  add_belief_candidate       — create a new SelfBelief with evidence entry
  update_belief_confidence   — adjust confidence + append to evidence_trail
  reinforce_belief           — confidence += (1-confidence)*_BELIEF_REINFORCE_RATE
  contradict_belief          — confidence -= confidence*_BELIEF_CONTRADICT_RATE
  deactivate_belief          — mark a belief is_active=False (superseded/retracted)

Design principle (sección 57):
  Beliefs from metacognition enter with confidence ≤ 0.40 and source="metacognition".
  They are NEVER auto-applied as facts — the caller is responsible for deciding
  whether to promote a candidate. This module only provides the persistence layer.

Confidence formula (Punto 4C — diminishing returns):
  Reinforcement: confidence += (1 - confidence) * _BELIEF_REINFORCE_RATE  (0.20)
  Contradiction: confidence -= confidence * _BELIEF_CONTRADICT_RATE        (0.15)
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.memory.models import SelfBelief, SelfModel, SityValues, utc_now

_BELIEF_REINFORCE_RATE: float = 0.20   # learning rate for diminishing-returns reinforcement
_BELIEF_CONTRADICT_RATE: float = 0.15  # relative rate for contradiction


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
    related_belief_id: int | None = None,
) -> SelfBelief:
    """Create a new SelfBelief with an initial evidence entry.

    confidence defaults to 0.40 for metacognition candidates (sección 57 principle).
    Use source="initial" or "configuration" for seed beliefs with higher confidence.
    related_belief_id: set when semantic resolution returned RELATED (Punto 4A).
    """
    from app.memory.models import utc_now as _utc_now
    evidence: list[dict] = [{
        "turn_id": trace_id,
        "relation": "support" if evidence_type not in ("contradiction", "contradict") else "contradict",
        "strength": max(0.0, min(1.0, confidence)),
        "source": evidence_type,
        "description": evidence_description or "initial candidate",
        "timestamp": _utc_now().isoformat(),
    }]
    belief = SelfBelief(
        self_model_id=self_model_id,
        proposition=proposition,
        confidence=max(0.0, min(1.0, confidence)),
        source=source,
        evidence_trail_json=json.dumps(evidence),
        related_belief_id=related_belief_id,
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
        now = utc_now()
        trail: list[dict] = json.loads(belief.evidence_trail_json)
        trail.append({
            "turn_id": trace_id,
            "relation": "support" if evidence_type not in ("contradiction", "contradict") else "contradict",
            "strength": _BELIEF_REINFORCE_RATE,
            "source": evidence_type,
            "description": evidence_description,
            "timestamp": now.isoformat(),
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

    Uses semantic resolution (resolve_candidate) so any caller automatically avoids
    semantic duplicates — not just exact-string matches.
    confidence=0.30 for new entries (more tentative than belief_updates' 0.40).
    Returns None on any error.
    """
    prop_clean = observation.strip()[:300]
    if not prop_clean:
        return None
    try:
        from app.cognition.semantic_resolver import resolve_candidate
        sm = get_or_create_self_model(session)
        if sm.id is None:
            return None
        existing_beliefs = get_active_beliefs(session, sm.id)
        resolution = resolve_candidate(
            prop_clean, "self_belief", existing_beliefs, trace_id=trace_id
        )
        if resolution.relation == "match" and resolution.target_id is not None:
            return reinforce_belief(
                session, resolution.target_id,
                trace_id=trace_id,
                evidence_description=f"self_model match: {prop_clean[:60]}",
            )
        elif resolution.relation == "contradict" and resolution.target_id is not None:
            return contradict_belief(
                session, resolution.target_id,
                trace_id=trace_id,
                evidence_description=f"self_model contradiction: {prop_clean[:60]}",
            )
        else:
            rel_id = resolution.target_id if resolution.relation == "related" else None
            return add_belief_candidate(
                session,
                self_model_id=sm.id,
                proposition=prop_clean,
                confidence=0.30,
                source="self_model_reflection",
                trace_id=trace_id,
                evidence_type="self_model_reflection",
                evidence_description="observation",
                related_belief_id=rel_id,
            )
    except Exception:
        return None


def reinforce_belief(
    session: Session,
    belief_id: int,
    *,
    trace_id: str = "",
    evidence_description: str = "",
) -> SelfBelief | None:
    """Increase confidence with diminishing returns: confidence += (1-confidence)*0.20.

    Returns updated belief or None if not found. Appends to evidence_trail_json.
    """
    belief = session.get(SelfBelief, belief_id)
    if belief is None:
        return None
    new_conf = min(1.0, belief.confidence + (1 - belief.confidence) * _BELIEF_REINFORCE_RATE)
    return update_belief_confidence(
        session,
        belief_id=belief_id,
        new_confidence=new_conf,
        trace_id=trace_id,
        evidence_type="reinforcement",
        evidence_description=evidence_description or "semantic match",
    )


def contradict_belief(
    session: Session,
    belief_id: int,
    *,
    trace_id: str = "",
    evidence_description: str = "",
) -> SelfBelief | None:
    """Reduce confidence: confidence -= confidence * 0.15.

    Returns updated belief or None if not found. Appends to evidence_trail_json.
    """
    belief = session.get(SelfBelief, belief_id)
    if belief is None:
        return None
    new_conf = max(0.0, belief.confidence - belief.confidence * _BELIEF_CONTRADICT_RATE)
    return update_belief_confidence(
        session,
        belief_id=belief_id,
        new_confidence=new_conf,
        trace_id=trace_id,
        evidence_type="contradiction",
        evidence_description=evidence_description or "semantic contradiction",
    )


def deactivate_belief(session: Session, belief_id: int) -> None:
    """Mark a SelfBelief as inactive (superseded or retracted). No-op if not found."""
    belief = session.get(SelfBelief, belief_id)
    if belief is not None:
        belief.is_active = False
        belief.updated_at = utc_now()
        session.add(belief)
        session.commit()


def get_relevant_self_beliefs(
    session: Session,
    user_id: int,  # noqa: ARG001 — accepted for call-site consistency; SelfBelief is global
    *,
    context_type: str = "",  # noqa: ARG001 — reserved for future context-type filtering
    min_confidence: float = 0.60,
    limit: int = 5,
) -> list[SelfBelief]:
    """Return active SelfBelief rows with confidence ≥ min_confidence, sorted desc.

    SelfBelief rows belong to the global SelfModel (not per-user). user_id and
    context_type are accepted for call-site consistency with other service functions
    but are not used as filters today.
    Returns [] when no SelfModel row exists yet.
    """
    sm = session.exec(select(SelfModel)).first()
    if sm is None or sm.id is None:
        return []
    return list(session.exec(
        select(SelfBelief)
        .where(SelfBelief.self_model_id == sm.id)
        .where(SelfBelief.is_active == True)  # noqa: E712
        .where(SelfBelief.confidence >= min_confidence)
        .order_by(SelfBelief.confidence.desc())  # type: ignore[attr-defined,arg-type]
        .limit(limit)
    ).all())

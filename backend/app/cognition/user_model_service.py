"""user_model_service.py — User Model, Theory of Mind, Expectations (Remake Fase 8).

Three interconnected capabilities:
  1. UserKnowledge: Sity's estimate of what topics/domains the user knows well.
  2. BeliefAttribution: Sity's beliefs about what the user believes (Theory of Mind).
  3. Expectation: Sity's forward-looking predictions of user behaviour per context_type.

All functions return empty list / None on any error (never raise).
All queries are filtered by user_id — isolation invariant across all three tables.

Confidence policy:
  UserKnowledge.confidence  — capped at 0.80 (indirect observation is imprecise)
  BeliefAttribution.confidence — capped at 0.65 (attributing beliefs to another mind
    is always speculative — same sección 57 principle as SelfBelief, stricter)
  Expectation.probability — free [0, 1]; Decision gate is _EXPECTATION_PROBABILITY_MIN
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.memory.models import BeliefAttribution, Expectation, UserKnowledge, utc_now
from app.trace.logger import write_log

# Fixed enum for expected_behavior — same discipline as context_type in Fase 7
VALID_EXPECTED_BEHAVIORS: frozenset[str] = frozenset({
    "ask_question",
    "request_help",
    "challenge_sity",
    "share_feedback",
    "casual_engagement",
    "creative_collaboration",
    "seek_explanation",
    "plan_together",
})

# Confidence caps enforced by service layer
_MAX_KNOWLEDGE_CONFIDENCE: float = 0.80
_MAX_BELIEF_CONFIDENCE: float = 0.65


# ---------------------------------------------------------------------------
# UserKnowledge
# ---------------------------------------------------------------------------

def load_knowledge(
    session: Session,
    user_id: int,
    *,
    topic: str | None = None,
) -> list[UserKnowledge]:
    """Return active UserKnowledge rows for user_id, optionally filtered by topic.

    Always filtered by user_id — isolation invariant.
    Returns empty list on any error.
    """
    try:
        stmt = (
            select(UserKnowledge)
            .where(UserKnowledge.user_id == user_id)
            .where(UserKnowledge.is_active == True)  # noqa: E712
        )
        if topic is not None:
            stmt = stmt.where(UserKnowledge.topic == topic)
        return list(session.exec(stmt).all())
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="user_knowledge_load_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return []


def upsert_knowledge(
    session: Session,
    *,
    user_id: int,
    topic: str,
    level: float,
    confidence: float,
    trace_id: str = "",
) -> UserKnowledge | None:
    """Create or update a UserKnowledge row for (user_id, topic).

    Returns the saved row, or None on failure.
    Confidence is capped at _MAX_KNOWLEDGE_CONFIDENCE (0.80).
    """
    try:
        clamped_level = max(0.0, min(1.0, level))
        clamped_confidence = max(0.0, min(_MAX_KNOWLEDGE_CONFIDENCE, confidence))

        existing = session.exec(
            select(UserKnowledge)
            .where(UserKnowledge.user_id == user_id)
            .where(UserKnowledge.topic == topic)
            .where(UserKnowledge.is_active == True)  # noqa: E712
        ).first()

        if existing is not None:
            old_trail: list[str] = json.loads(existing.evidence_trail_json)
            if trace_id and trace_id not in old_trail:
                old_trail.append(trace_id)
            existing.level = clamped_level
            existing.confidence = clamped_confidence
            existing.occurrence_count += 1
            existing.evidence_trail_json = json.dumps(old_trail[:50], ensure_ascii=False)
            existing.last_observed_at = utc_now()
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        trail = [trace_id] if trace_id else []
        row = UserKnowledge(
            user_id=user_id,
            topic=topic,
            level=clamped_level,
            confidence=clamped_confidence,
            evidence_trail_json=json.dumps(trail, ensure_ascii=False),
            occurrence_count=1,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="user_knowledge_upsert_failed",
            payload={"user_id": user_id, "topic": topic, "error": str(exc)[:200]},
        )
        return None


# ---------------------------------------------------------------------------
# BeliefAttribution
# ---------------------------------------------------------------------------

def load_belief_attributions(
    session: Session,
    user_id: int,
    *,
    is_active: bool = True,
) -> list[BeliefAttribution]:
    """Return BeliefAttribution rows for user_id.

    Always filtered by user_id — isolation invariant.
    Returns empty list on any error.
    """
    try:
        stmt = (
            select(BeliefAttribution)
            .where(BeliefAttribution.user_id == user_id)
            .where(BeliefAttribution.is_active == is_active)  # noqa: E712
        )
        return list(session.exec(stmt).all())
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="belief_attribution_load_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return []


def add_belief_attribution(
    session: Session,
    *,
    user_id: int,
    proposition: str,
    confidence: float,
    source: str = "reflection",
    context_type: str = "",
    trace_id: str = "",
) -> BeliefAttribution | None:
    """Insert a new BeliefAttribution candidate.

    Confidence is capped at _MAX_BELIEF_CONFIDENCE (0.65) — sección 57 principle.
    Returns the saved row, or None on failure.
    """
    try:
        clamped = max(0.0, min(_MAX_BELIEF_CONFIDENCE, confidence))
        trail = [trace_id] if trace_id else []
        row = BeliefAttribution(
            user_id=user_id,
            proposition=proposition[:300],
            confidence=clamped,
            source=source,
            context_type=context_type,
            evidence_trail_json=json.dumps(trail, ensure_ascii=False),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="belief_attribution_add_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return None


# ---------------------------------------------------------------------------
# Expectation
# ---------------------------------------------------------------------------

def load_active_expectations(
    session: Session,
    *,
    user_id: int,
    context_type: str,
    min_probability: float = 0.60,
) -> list[Expectation]:
    """Return active Expectation rows for (user_id, context_type) above probability threshold.

    Always filtered by user_id — isolation invariant.
    Returns empty list on any error.
    """
    try:
        return list(session.exec(
            select(Expectation)
            .where(Expectation.user_id == user_id)
            .where(Expectation.context_type == context_type)
            .where(Expectation.is_active == True)  # noqa: E712
            .where(Expectation.probability >= min_probability)
        ).all())
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="expectation_load_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return []


def upsert_expectation(
    session: Session,
    *,
    user_id: int,
    context_type: str,
    expected_behavior: str,
    probability: float,
    trace_id: str = "",
) -> Expectation | None:
    """Create or update an Expectation for (user_id, context_type, expected_behavior).

    Returns the saved row, or None on failure.
    expected_behavior must be in VALID_EXPECTED_BEHAVIORS — returns None if unknown.
    """
    if expected_behavior not in VALID_EXPECTED_BEHAVIORS:
        write_log(
            level="WARN",
            module="cognition",
            event="expectation_unknown_behavior",
            payload={"user_id": user_id, "expected_behavior": expected_behavior},
        )
        return None

    try:
        clamped_prob = max(0.0, min(1.0, probability))

        existing = session.exec(
            select(Expectation)
            .where(Expectation.user_id == user_id)
            .where(Expectation.context_type == context_type)
            .where(Expectation.expected_behavior == expected_behavior)
            .where(Expectation.is_active == True)  # noqa: E712
        ).first()

        if existing is not None:
            old_trail: list[str] = json.loads(existing.evidence_trail_json)
            if trace_id and trace_id not in old_trail:
                old_trail.append(trace_id)
            existing.probability = clamped_prob
            existing.occurrence_count += 1
            existing.evidence_trail_json = json.dumps(old_trail[:50], ensure_ascii=False)
            existing.last_observed_at = utc_now()
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        trail = [trace_id] if trace_id else []
        row = Expectation(
            user_id=user_id,
            context_type=context_type,
            expected_behavior=expected_behavior,
            probability=clamped_prob,
            evidence_trail_json=json.dumps(trail, ensure_ascii=False),
            occurrence_count=1,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="expectation_upsert_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return None

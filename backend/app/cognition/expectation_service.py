"""expectation_service.py — Prediction error evaluation (MINI-REMAKE v2.0 Punto 5).

Evaluates all pending Expectations at the start of each turn, BEFORE Appraisal.
Produces prediction_error and surprise signals that feed:
  - salience boost (high surprise → more memorable turn)
  - trust_reliability adjustment (fulfilled direct expectations → +trust; expired → no change)

Architecture:
  Event expectations (type="event"):
    - Fulfilled: perception.context_type matches expected_behavior → resolve as "fulfilled"
    - Expired:   due_at is set AND due_at < now → resolve as "expired_unknown"
    - Never resolved as "violated" by silence (epistemic humility)

  Pattern expectations (type="pattern"):
    - Match:    perception.context_type == expectation.context_type → probability += 0.03
    - No match: perception.context_type != expectation.context_type → probability -= 0.02
    - NOT resolved (persistent, updated in-place)

Prediction error formula:  error = y − p  (y=1 if fulfilled, y=0 otherwise)
Surprise formula:          surprise = −log2(P(outcome))
  P(outcome) = probability if outcome=fulfilled, else (1 − probability)

Never raises — returns empty ExpectationEvalResult on any error.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.cognition.perception import PerceptionResult
from app.memory.models import Expectation, ExpectationResolution, SocialProfile, utc_now
from app.trace.logger import write_log

_PATTERN_PROB_HIT:  float = 0.03    # probability boost when pattern fires
_PATTERN_PROB_MISS: float = 0.02    # probability penalty when pattern doesn't fire
_TRUST_RELIABILITY_HIT:  float = 0.015  # nudge up when direct event fulfilled
_TRUST_RELIABILITY_MAX:  float = 1.0
_TRUST_RELIABILITY_MIN:  float = 0.0


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PredictionErrorEntry:
    expectation_id: int
    error: float            # y − p
    surprise: float         # −log2(P(outcome_observed))
    observability: str
    outcome: str            # "fulfilled" | "expired_unknown"


@dataclass
class ExpectationEvalResult:
    resolved_expectations: list[Expectation] = field(default_factory=list)
    prediction_errors: list[PredictionErrorEntry] = field(default_factory=list)

    @property
    def max_surprise(self) -> float:
        if not self.prediction_errors:
            return 0.0
        return max(e.surprise for e in self.prediction_errors)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_surprise(probability: float, fulfilled: bool) -> float:
    """−log2(P(observed_outcome)). Clamped to [0, 10]."""
    p_outcome = probability if fulfilled else max(0.001, 1.0 - probability)
    return min(10.0, -math.log2(max(0.001, p_outcome)))


def _load_pending_expectations(session: Session, user_id: int) -> list[Expectation]:
    """Load all active pending expectations for user_id regardless of context_type."""
    try:
        return list(session.exec(
            select(Expectation)
            .where(Expectation.user_id == user_id)
            .where(Expectation.is_active == True)  # noqa: E712
            .where(Expectation.status == "pending")
        ).all())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public: evaluate
# ---------------------------------------------------------------------------

def evaluate_pending_expectations(
    session: Session,
    *,
    user_id: int,
    perception: PerceptionResult,
    current_turn_id: str = "",
) -> ExpectationEvalResult:
    """Evaluate all pending Expectations for user_id against the current perception.

    Must be called BEFORE Appraisal in turn_cognition.py.
    Never raises — returns empty result on any error.
    """
    result = ExpectationEvalResult()
    now = utc_now()

    try:
        pending = _load_pending_expectations(session, user_id)
        if not pending:
            return result

        _had_changes = False
        for exp in pending:
            if exp.expectation_type == "event":
                _eval_event_expectation(
                    session, exp, perception, now, current_turn_id, result
                )
                if result.resolved_expectations:
                    _had_changes = True
            elif exp.expectation_type == "pattern":
                _eval_pattern_expectation(session, exp, perception)
                _had_changes = True

        if _had_changes:
            session.commit()

    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="expectation_eval_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )

    return result


def _eval_event_expectation(
    session: Session,
    exp: Expectation,
    perception: PerceptionResult,
    now,
    current_turn_id: str,
    result: ExpectationEvalResult,
) -> None:
    """Resolve an event expectation as fulfilled or expired_unknown."""
    # Fulfilled: current perception matches expected_behavior
    fulfilled = (perception.context_type == exp.expected_behavior)

    # Expired: due_at passed without fulfillment evidence
    expired = (
        not fulfilled
        and exp.due_at is not None
        and _aware(exp.due_at) < _aware(now)
    )

    if not (fulfilled or expired):
        return

    outcome = "fulfilled" if fulfilled else "expired_unknown"
    y = 1.0 if fulfilled else 0.0
    error = y - exp.probability
    surprise = _compute_surprise(exp.probability, fulfilled)

    exp.status = outcome
    exp.is_active = False
    session.add(exp)

    resolution = ExpectationResolution(
        expectation_id=exp.id,  # type: ignore[arg-type]
        turn_id=current_turn_id,
        outcome=outcome,
        predicted_probability=exp.probability,
        prediction_error=error,
        surprise=surprise,
        resolved_at=now,
    )
    session.add(resolution)

    result.resolved_expectations.append(exp)
    result.prediction_errors.append(PredictionErrorEntry(
        expectation_id=exp.id,  # type: ignore[arg-type]
        error=error,
        surprise=surprise,
        observability=exp.observability,
        outcome=outcome,
    ))

    write_log(
        level="INFO",
        module="cognition",
        event="expectation_resolved",
        payload={
            "expectation_id": exp.id,
            "outcome": outcome,
            "prediction_error": round(error, 3),
            "surprise": round(surprise, 3),
        },
    )


def _eval_pattern_expectation(
    session: Session,
    exp: Expectation,
    perception: PerceptionResult,
) -> None:
    """Update a pattern expectation probability based on current context_type match."""
    hit = (perception.context_type == exp.context_type)
    if hit:
        exp.probability = min(1.0, exp.probability + _PATTERN_PROB_HIT)
    else:
        exp.probability = max(0.0, exp.probability - _PATTERN_PROB_MISS)
    exp.last_observed_at = utc_now()
    session.add(exp)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Public: trust_reliability downstream
# ---------------------------------------------------------------------------

def apply_prediction_error_to_trust(
    profile: SocialProfile,
    prediction_errors: list[PredictionErrorEntry],
) -> None:
    """Nudge trust_reliability based on prediction error resolution.

    Rules (from spec):
    - prediction_error > 0 (fulfilled) AND observability="direct" → +trust_reliability
    - expired_unknown → no change (epistemic humility)

    Mutates profile in-place. Caller must session.add() + commit().
    """
    for entry in prediction_errors:
        if entry.outcome == "fulfilled" and entry.observability == "direct":
            profile.trust_reliability = min(
                _TRUST_RELIABILITY_MAX,
                profile.trust_reliability + _TRUST_RELIABILITY_HIT,
            )

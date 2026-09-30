"""Tests for Punto 5 — Expectation lifecycle (create, evaluate, resolve).

Properties verified:

Data model:
1.  New Expectation has status="pending" and expectation_type="event" by default.
2.  Expectation fields expectation_type, source, due_at, importance,
    observability, status, proposition persist to DB correctly.
3.  ExpectationResolution row is created with correct prediction_error and surprise.

Reflection → Expectation creation:
4.  _parse_reflection_response with future_commitments returns list of dicts.
5.  _parse_reflection_response with empty future_commitments returns [].
6.  _parse_reflection_response skips commitments without proposition.
7.  upsert_expectation with due_at and proposition stores them.
8.  upsert_expectation with new fields is backward-compatible (old call signature works).

ProceduralPattern → Expectation:
9.  _run_pattern_synthesis eligible (occurrence_count>=3, confidence>=0.55) creates Expectation.
10. _run_pattern_synthesis with non-VALID context_type skips Expectation creation.

evaluate_pending_expectations:
11. Fulfilled: perception.context_type matches expected_behavior → status="fulfilled",
    ExpectationResolution created, prediction_error = 1 - probability.
12. Expired: due_at < now, no match → status="expired_unknown",
    ExpectationResolution created, prediction_error = 0 - probability.
13. No match and not expired → status stays "pending", no resolution.
14. due_at in the future without match → NOT expired (status="pending").
15. Inactive expectations are skipped.
16. Already-resolved (status != "pending") are skipped.
17. User isolation: evaluating user A does not touch user B's expectations.
18. Pattern expectations: hit → probability increases by _PATTERN_PROB_HIT.
19. Pattern expectations: miss → probability decreases by _PATTERN_PROB_MISS.
20. evaluate_pending_expectations never raises (corrupted DB → returns empty result).

Prediction error math:
21. prediction_error for fulfilled = 1 - probability (approx).
22. prediction_error for expired_unknown = 0 - probability (approx).
23. surprise for fulfilled with probability=0.8 = -log2(0.8) ≈ 0.32.
24. surprise for expired with probability=0.8 = -log2(0.2) ≈ 2.32.
25. max_surprise returns 0.0 when no prediction errors.

Trust downstream:
26. apply_prediction_error_to_trust: fulfilled+direct → trust_reliability increases.
27. apply_prediction_error_to_trust: expired_unknown → trust_reliability unchanged.
28. apply_prediction_error_to_trust: fulfilled+indirect → trust_reliability unchanged.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, delete as sql_delete

from app.cognition.expectation_service import (
    ExpectationEvalResult,
    PredictionErrorEntry,
    _PATTERN_PROB_HIT,
    _PATTERN_PROB_MISS,
    apply_prediction_error_to_trust,
    evaluate_pending_expectations,
)
from app.cognition.perception import PerceptionResult
from app.cognition.reflection import _parse_reflection_response
from app.cognition.user_model_service import upsert_expectation
from app.memory.models import Expectation, ExpectationResolution, SocialProfile, utc_now


# ── Helpers ───────────────────────────────────────────────────────────────────

_UID = 970_000
_UID_B = 970_001
_NOW = datetime.now(timezone.utc)


def _clean(session: Session, *uids: int) -> None:
    for uid in uids:
        session.exec(sql_delete(Expectation).where(Expectation.user_id == uid))  # type: ignore[call-overload]
    # ExpectationResolution has no user_id — clean by expectation_id implicitly
    session.commit()


def _make_exp(
    session: Session,
    user_id: int = _UID,
    context_type: str = "plan_together",
    expected_behavior: str = "plan_together",
    probability: float = 0.70,
    expectation_type: str = "event",
    source: str = "reflection",
    status: str = "pending",
    is_active: bool = True,
    due_at: datetime | None = None,
    importance: float = 0.5,
    observability: str = "direct",
    proposition: str = "",
) -> Expectation:
    exp = Expectation(
        user_id=user_id,
        context_type=context_type,
        expected_behavior=expected_behavior,
        probability=probability,
        expectation_type=expectation_type,
        source=source,
        status=status,
        is_active=is_active,
        due_at=due_at,
        importance=importance,
        observability=observability,
        proposition=proposition,
    )
    session.add(exp)
    session.commit()
    session.refresh(exp)
    return exp


def _perception(context_type: str = "plan_together") -> PerceptionResult:
    return PerceptionResult(
        user_intent="test intent",
        tone="neutral",
        challenge=0.0,
        social_signal=0.5,
        novelty=0.3,
        context_type=context_type,
    )


def _social_profile(trust_reliability: float = 0.50) -> SocialProfile:
    sp = SocialProfile(user_id=_UID)
    sp.trust_reliability = trust_reliability
    return sp


# ── 1–3: Data model defaults ──────────────────────────────────────────────────

class TestExpectationDefaults:
    def test_default_status_pending(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session)
        assert exp.status == "pending"

    def test_default_expectation_type_event(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session)
        assert exp.expectation_type == "event"

    def test_all_new_fields_persist(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        due = _NOW + timedelta(days=1)
        exp = _make_exp(
            db_session,
            expectation_type="event",
            source="reflection",
            due_at=due,
            importance=0.8,
            observability="indirect",
            proposition="User will finish the report",
        )
        db_session.refresh(exp)
        assert exp.expectation_type == "event"
        assert exp.source == "reflection"
        assert exp.due_at is not None
        assert abs((exp.due_at.replace(tzinfo=timezone.utc) - due).total_seconds()) < 2
        assert exp.importance == pytest.approx(0.8)
        assert exp.observability == "indirect"
        assert exp.proposition == "User will finish the report"

    def test_expectation_resolution_fields(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, probability=0.70)
        res = ExpectationResolution(
            expectation_id=exp.id,
            turn_id="t001",
            outcome="fulfilled",
            predicted_probability=0.70,
            prediction_error=1.0 - 0.70,
            surprise=-math.log2(0.70),
            resolved_at=_NOW,
        )
        db_session.add(res)
        db_session.commit()
        db_session.refresh(res)
        assert res.outcome == "fulfilled"
        assert res.prediction_error == pytest.approx(0.30, abs=0.001)
        assert res.surprise == pytest.approx(-math.log2(0.70), abs=0.001)


# ── 4–8: Reflection parsing ───────────────────────────────────────────────────

class TestReflectionFutureCommitments:
    def test_parse_future_commitments_from_json(self) -> None:
        raw = """{
            "success_estimate": 0.8,
            "memory_candidates": [],
            "belief_updates": [],
            "relationship_evidence": [],
            "goal_updates": [],
            "self_model_updates": [],
            "user_belief_updates": [],
            "future_commitments": [
                {"proposition": "User will finish the retrieval module",
                 "due_at_hint": "mañana", "importance": 0.7, "observability": "direct"}
            ]
        }"""
        result = _parse_reflection_response(raw)
        assert result is not None
        assert len(result.future_commitments) == 1
        fc = result.future_commitments[0]
        assert fc["proposition"] == "User will finish the retrieval module"
        assert fc["due_at_hint"] == "mañana"
        assert fc["importance"] == pytest.approx(0.7)
        assert fc["observability"] == "direct"

    def test_parse_empty_future_commitments(self) -> None:
        raw = """{
            "success_estimate": 0.7,
            "memory_candidates": [], "belief_updates": [],
            "relationship_evidence": [], "goal_updates": [],
            "self_model_updates": [], "user_belief_updates": [],
            "future_commitments": []
        }"""
        result = _parse_reflection_response(raw)
        assert result is not None
        assert result.future_commitments == []

    def test_parse_skips_commitment_without_proposition(self) -> None:
        raw = """{
            "success_estimate": 0.7,
            "memory_candidates": [], "belief_updates": [],
            "relationship_evidence": [], "goal_updates": [],
            "self_model_updates": [], "user_belief_updates": [],
            "future_commitments": [
                {"due_at_hint": "mañana", "importance": 0.5, "observability": "direct"}
            ]
        }"""
        result = _parse_reflection_response(raw)
        assert result is not None
        assert result.future_commitments == []

    def test_upsert_expectation_stores_due_at_and_proposition(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        due = _NOW + timedelta(hours=24)
        exp = upsert_expectation(
            db_session,
            user_id=_UID,
            context_type="plan_together",
            expected_behavior="plan_together",
            probability=0.65,
            trace_id="t-test",
            expectation_type="event",
            source="reflection",
            due_at=due,
            importance=0.7,
            observability="direct",
            proposition="User will finish the retrieval module tomorrow",
        )
        assert exp is not None
        assert exp.proposition == "User will finish the retrieval module tomorrow"
        assert exp.expectation_type == "event"
        assert exp.due_at is not None

    def test_upsert_expectation_backward_compatible(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # Old call style — no new fields
        exp = upsert_expectation(
            db_session,
            user_id=_UID,
            context_type="ask_question",
            expected_behavior="ask_question",
            probability=0.60,
        )
        assert exp is not None
        assert exp.status == "pending"
        assert exp.expectation_type == "event"   # default


# ── 9–10: ProceduralPattern → Expectation ────────────────────────────────────

class TestProceduralPatternExpectation:
    def test_eligible_pattern_creates_expectation(self, db_session: Session) -> None:
        from app.memory.models import ProceduralObservation
        _clean(db_session, _UID)
        db_session.exec(sql_delete(ProceduralObservation).where(ProceduralObservation.user_id == _UID))  # type: ignore[call-overload]
        db_session.commit()
        # Create 3 unprocessed observations so synthesis fires
        for i in range(3):
            obs = ProceduralObservation(
                user_id=_UID, context_type="ask_question",
                user_message_excerpt=f"How does X work? {i}", trace_id=f"t{i}",
            )
            db_session.add(obs)
        db_session.commit()

        fake_strategy = "Ask one clarifying question before diving in"
        with patch("app.cognition.procedural_service._synthesise_strategy", return_value=fake_strategy):
            from app.cognition.procedural_service import _run_pattern_synthesis
            _run_pattern_synthesis(_UID, "ask_question", "test-trace")

        # Expectation should now exist
        exp = db_session.exec(
            __import__("sqlmodel").select(Expectation)
            .where(Expectation.user_id == _UID)
            .where(Expectation.context_type == "ask_question")
            .where(Expectation.expectation_type == "pattern")
        ).first()
        assert exp is not None
        assert exp.source == "procedural"

    def test_non_valid_context_type_skips_expectation(self, db_session: Session) -> None:
        from app.memory.models import ProceduralObservation
        _clean(db_session, _UID)
        db_session.exec(sql_delete(ProceduralObservation).where(ProceduralObservation.user_id == _UID))  # type: ignore[call-overload]
        db_session.commit()
        for i in range(3):
            obs = ProceduralObservation(
                user_id=_UID, context_type="unknown_context",
                user_message_excerpt=f"message {i}", trace_id=f"t{i}",
            )
            db_session.add(obs)
        db_session.commit()

        with patch("app.cognition.procedural_service._synthesise_strategy", return_value="some strategy"):
            from app.cognition.procedural_service import _run_pattern_synthesis
            _run_pattern_synthesis(_UID, "unknown_context", "test-trace")

        # No Expectation should have been created
        exps = db_session.exec(
            __import__("sqlmodel").select(Expectation)
            .where(Expectation.user_id == _UID)
            .where(Expectation.context_type == "unknown_context")
        ).all()
        assert len(exps) == 0


# ── 11–20: evaluate_pending_expectations ─────────────────────────────────────

class TestEvaluatePendingExpectations:
    def test_fulfilled_expectation_resolved(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, expected_behavior="plan_together", probability=0.70)
        perception = _perception("plan_together")  # matches expected_behavior

        result = evaluate_pending_expectations(
            db_session, user_id=_UID, perception=perception, current_turn_id="t1"
        )
        db_session.refresh(exp)
        assert exp.status == "fulfilled"
        assert exp.is_active is False
        assert len(result.resolved_expectations) == 1
        assert len(result.prediction_errors) == 1
        assert result.prediction_errors[0].outcome == "fulfilled"

    def test_expired_expectation_resolved(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        past_due = _NOW - timedelta(hours=2)
        exp = _make_exp(db_session, expected_behavior="plan_together",
                        probability=0.70, due_at=past_due)
        perception = _perception("ask_question")  # does NOT match

        result = evaluate_pending_expectations(
            db_session, user_id=_UID, perception=perception, current_turn_id="t2"
        )
        db_session.refresh(exp)
        assert exp.status == "expired_unknown"
        assert result.prediction_errors[0].outcome == "expired_unknown"

    def test_no_match_not_expired_stays_pending(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        future_due = _NOW + timedelta(days=1)
        exp = _make_exp(db_session, expected_behavior="plan_together",
                        probability=0.70, due_at=future_due)
        perception = _perception("ask_question")  # does not match

        evaluate_pending_expectations(
            db_session, user_id=_UID, perception=perception
        )
        db_session.refresh(exp)
        assert exp.status == "pending"

    def test_future_due_no_match_not_expired(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        future = _NOW + timedelta(days=3)
        exp = _make_exp(db_session, expected_behavior="ask_question",
                        probability=0.60, due_at=future)
        perception = _perception("casual_engagement")

        evaluate_pending_expectations(db_session, user_id=_UID, perception=perception)
        db_session.refresh(exp)
        assert exp.status == "pending"

    def test_inactive_expectations_skipped(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, expected_behavior="plan_together",
                        probability=0.70, is_active=False)
        perception = _perception("plan_together")

        result = evaluate_pending_expectations(db_session, user_id=_UID, perception=perception)
        assert len(result.resolved_expectations) == 0

    def test_already_resolved_skipped(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, expected_behavior="plan_together",
                        probability=0.70, status="fulfilled", is_active=False)
        perception = _perception("plan_together")

        result = evaluate_pending_expectations(db_session, user_id=_UID, perception=perception)
        assert len(result.resolved_expectations) == 0

    def test_user_isolation(self, db_session: Session) -> None:
        _clean(db_session, _UID, _UID_B)
        exp_a = _make_exp(db_session, user_id=_UID, expected_behavior="plan_together")
        exp_b = _make_exp(db_session, user_id=_UID_B, expected_behavior="plan_together")
        perception = _perception("plan_together")

        evaluate_pending_expectations(db_session, user_id=_UID, perception=perception)
        db_session.refresh(exp_a)
        db_session.refresh(exp_b)
        assert exp_a.status == "fulfilled"
        assert exp_b.status == "pending"   # untouched

    def test_pattern_expectation_hit_increases_probability(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, expectation_type="pattern",
                        context_type="ask_question", expected_behavior="ask_question",
                        probability=0.60)
        perception = _perception("ask_question")  # matches context_type

        evaluate_pending_expectations(db_session, user_id=_UID, perception=perception)
        db_session.refresh(exp)
        assert exp.probability == pytest.approx(0.60 + _PATTERN_PROB_HIT, abs=0.001)

    def test_pattern_expectation_miss_decreases_probability(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, expectation_type="pattern",
                        context_type="ask_question", expected_behavior="ask_question",
                        probability=0.60)
        perception = _perception("casual_engagement")  # different context_type

        evaluate_pending_expectations(db_session, user_id=_UID, perception=perception)
        db_session.refresh(exp)
        assert exp.probability == pytest.approx(0.60 - _PATTERN_PROB_MISS, abs=0.001)

    def test_never_raises_on_error(self, db_session: Session) -> None:
        perception = _perception()
        # Should not raise even with bogus user_id
        result = evaluate_pending_expectations(db_session, user_id=999_999_999, perception=perception)
        assert isinstance(result, ExpectationEvalResult)


# ── 21–25: Prediction error math ─────────────────────────────────────────────

class TestPredictionErrorMath:
    def test_prediction_error_fulfilled(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        exp = _make_exp(db_session, probability=0.70, expected_behavior="plan_together")
        result = evaluate_pending_expectations(
            db_session, user_id=_UID, perception=_perception("plan_together")
        )
        err = result.prediction_errors[0]
        assert err.error == pytest.approx(1.0 - 0.70, abs=0.001)

    def test_prediction_error_expired(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        past = _NOW - timedelta(hours=1)
        exp = _make_exp(db_session, probability=0.70, due_at=past, expected_behavior="plan_together")
        result = evaluate_pending_expectations(
            db_session, user_id=_UID, perception=_perception("ask_question")
        )
        err = result.prediction_errors[0]
        assert err.error == pytest.approx(0.0 - 0.70, abs=0.001)

    def test_surprise_fulfilled_high_prob(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        _make_exp(db_session, probability=0.80, expected_behavior="plan_together")
        result = evaluate_pending_expectations(
            db_session, user_id=_UID, perception=_perception("plan_together")
        )
        expected_surprise = -math.log2(0.80)
        assert result.prediction_errors[0].surprise == pytest.approx(expected_surprise, abs=0.001)

    def test_surprise_expired_high_prob(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        past = _NOW - timedelta(hours=1)
        _make_exp(db_session, probability=0.80, due_at=past, expected_behavior="plan_together")
        result = evaluate_pending_expectations(
            db_session, user_id=_UID, perception=_perception("ask_question")
        )
        # P(expired) = 1 - 0.80 = 0.20
        expected_surprise = -math.log2(0.20)
        assert result.prediction_errors[0].surprise == pytest.approx(expected_surprise, abs=0.001)

    def test_max_surprise_zero_when_empty(self) -> None:
        result = ExpectationEvalResult()
        assert result.max_surprise == 0.0


# ── 26–28: Trust downstream ───────────────────────────────────────────────────

class TestTrustDownstream:
    def test_fulfilled_direct_increases_trust_reliability(self) -> None:
        sp = _social_profile(0.50)
        errors = [PredictionErrorEntry(
            expectation_id=1, error=0.30, surprise=0.5,
            observability="direct", outcome="fulfilled",
        )]
        apply_prediction_error_to_trust(sp, errors)
        assert sp.trust_reliability > 0.50

    def test_expired_unknown_no_trust_change(self) -> None:
        sp = _social_profile(0.50)
        errors = [PredictionErrorEntry(
            expectation_id=1, error=-0.70, surprise=2.3,
            observability="direct", outcome="expired_unknown",
        )]
        apply_prediction_error_to_trust(sp, errors)
        assert sp.trust_reliability == pytest.approx(0.50)

    def test_fulfilled_indirect_no_trust_change(self) -> None:
        sp = _social_profile(0.50)
        errors = [PredictionErrorEntry(
            expectation_id=1, error=0.30, surprise=0.5,
            observability="indirect", outcome="fulfilled",
        )]
        apply_prediction_error_to_trust(sp, errors)
        assert sp.trust_reliability == pytest.approx(0.50)

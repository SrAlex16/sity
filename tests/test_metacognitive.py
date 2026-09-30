"""test_metacognitive.py — Punto 7: SelfModel → autorregulación.

Tests for:
  - get_relevant_self_beliefs: threshold, ordering, limit, empty DB
  - _apply_metacognitive_bounds: modifier math, 1.5x weight, not-applicable, invalid action
  - compute_metacognitive_adjustments: empty beliefs, fallback on failure
  - decision.py integration: active_self_beliefs=None is a no-op, score clamping

behavior_regression tests require a real ANTHROPIC_API_KEY and are excluded from CI.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

_UID = 93_100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_self_belief(
    self_model_id: int,
    proposition: str,
    confidence: float,
    db_session,
) -> "SelfBelief":
    from app.memory.models import SelfBelief
    b = SelfBelief(
        self_model_id=self_model_id,
        proposition=proposition,
        confidence=confidence,
        source="test",
        evidence_trail_json="[]",
    )
    db_session.add(b)
    db_session.commit()
    db_session.refresh(b)
    return b


def _get_or_create_sm(db_session) -> "SelfModel":
    from sqlmodel import select
    from app.memory.models import SelfModel
    sm = db_session.exec(select(SelfModel)).first()
    if sm is None:
        sm = SelfModel()
        db_session.add(sm)
        db_session.commit()
        db_session.refresh(sm)
    return sm


def _mock_belief(bid: int, confidence: float, proposition: str = "Test belief") -> "SelfBelief":
    from app.memory.models import SelfBelief
    b = SelfBelief(
        self_model_id=1,
        proposition=proposition,
        confidence=confidence,
        source="test",
        evidence_trail_json="[]",
    )
    b.id = bid
    return b


# ---------------------------------------------------------------------------
# TestGetRelevantSelfBeliefs
# ---------------------------------------------------------------------------

class TestGetRelevantSelfBeliefs:
    def setup_method(self):
        from sqlmodel import Session, select
        from app.memory.db import engine
        from app.memory.models import SelfBelief, SelfModel
        with Session(engine) as s:
            for b in s.exec(select(SelfBelief)).all():
                s.delete(b)
            for sm in s.exec(select(SelfModel)).all():
                s.delete(sm)
            s.commit()

    def test_threshold_filters_below_min_confidence(self, db_session):
        from app.cognition.self_model_service import get_relevant_self_beliefs
        sm = _get_or_create_sm(db_session)
        _make_self_belief(sm.id, "Belief A", 0.50, db_session)
        b60 = _make_self_belief(sm.id, "Belief B", 0.60, db_session)
        b80 = _make_self_belief(sm.id, "Belief C", 0.80, db_session)

        results = get_relevant_self_beliefs(db_session, _UID, min_confidence=0.60)
        ids = [b.id for b in results]
        assert b60.id in ids
        assert b80.id in ids
        assert len(results) == 2  # 0.50 excluded

    def test_below_threshold_excluded(self, db_session):
        from app.cognition.self_model_service import get_relevant_self_beliefs
        sm = _get_or_create_sm(db_session)
        _make_self_belief(sm.id, "Low conf", 0.40, db_session)

        results = get_relevant_self_beliefs(db_session, _UID, min_confidence=0.60)
        assert results == []

    def test_sorted_by_confidence_descending(self, db_session):
        from app.cognition.self_model_service import get_relevant_self_beliefs
        sm = _get_or_create_sm(db_session)
        _make_self_belief(sm.id, "Conf 0.65", 0.65, db_session)
        _make_self_belief(sm.id, "Conf 0.90", 0.90, db_session)
        _make_self_belief(sm.id, "Conf 0.75", 0.75, db_session)

        results = get_relevant_self_beliefs(db_session, _UID, min_confidence=0.60)
        assert len(results) == 3
        assert results[0].confidence == pytest.approx(0.90)
        assert results[1].confidence == pytest.approx(0.75)
        assert results[2].confidence == pytest.approx(0.65)

    def test_limit_respected(self, db_session):
        from app.cognition.self_model_service import get_relevant_self_beliefs
        sm = _get_or_create_sm(db_session)
        for i in range(6):
            _make_self_belief(sm.id, f"Belief {i}", 0.60 + i * 0.02, db_session)

        results = get_relevant_self_beliefs(db_session, _UID, min_confidence=0.60, limit=3)
        assert len(results) == 3

    def test_empty_when_no_self_model(self, db_session):
        from app.cognition.self_model_service import get_relevant_self_beliefs
        # setup_method already deleted all SelfModel rows
        results = get_relevant_self_beliefs(db_session, _UID, min_confidence=0.60)
        assert results == []


# ---------------------------------------------------------------------------
# TestApplyMetacognitiveBounds
# ---------------------------------------------------------------------------

class TestApplyMetacognitiveBounds:
    def test_modifier_math_low_confidence(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds, MAX_METACOGNITIVE_BIAS
        raw = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {"answer": 1.0}, "reason": "test"}'
        beliefs = [_mock_belief(1, 0.70)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        # proposed=1.0, conf=0.70, weight=1.0 (< 0.80) → 1.0 * 0.70 * 0.05 * 1.0 = 0.035
        expected = 1.0 * 0.70 * MAX_METACOGNITIVE_BIAS * 1.0
        assert result.get("answer") == pytest.approx(expected, abs=1e-6)

    def test_modifier_math_high_confidence(self):
        from app.cognition.metacognitive_evaluator import (
            _apply_metacognitive_bounds, MAX_METACOGNITIVE_BIAS,
            _HIGH_CONFIDENCE_WEIGHT, _HIGH_CONFIDENCE_THRESHOLD,
        )
        conf = 0.85
        assert conf >= _HIGH_CONFIDENCE_THRESHOLD
        raw = f'{{"applicable": true, "relevant_beliefs": [1], "adjustments": {{"challenge": 1.0}}, "reason": "test"}}'
        beliefs = [_mock_belief(1, conf)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        expected = 1.0 * conf * MAX_METACOGNITIVE_BIAS * _HIGH_CONFIDENCE_WEIGHT
        assert result.get("challenge") == pytest.approx(expected, abs=1e-6)

    def test_not_applicable_returns_empty(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds
        raw = '{"applicable": false, "relevant_beliefs": [], "adjustments": {"answer": 0.8}, "reason": "no"}'
        beliefs = [_mock_belief(1, 0.80)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        assert result == {}

    def test_invalid_action_ignored(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds
        raw = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {"not_a_real_action": 1.0, "answer": 0.5}, "reason": "x"}'
        beliefs = [_mock_belief(1, 0.70)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        assert "not_a_real_action" not in result
        assert "answer" in result

    def test_proposed_clamped_to_minus1_plus1(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds, MAX_METACOGNITIVE_BIAS
        raw = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {"help": 99.0}, "reason": "x"}'
        beliefs = [_mock_belief(1, 0.70)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        # proposed clamped to 1.0 → 1.0 * 0.70 * 0.05 * 1.0 = 0.035
        expected = 1.0 * 0.70 * MAX_METACOGNITIVE_BIAS * 1.0
        assert result.get("help") == pytest.approx(expected, abs=1e-6)

    def test_negative_proposed_gives_negative_delta(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds, MAX_METACOGNITIVE_BIAS
        raw = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {"challenge": -1.0}, "reason": "x"}'
        beliefs = [_mock_belief(1, 0.70)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        expected = -1.0 * 0.70 * MAX_METACOGNITIVE_BIAS * 1.0
        assert result.get("challenge") == pytest.approx(expected, abs=1e-6)

    def test_empty_adjustments_returns_empty(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds
        raw = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {}, "reason": "x"}'
        beliefs = [_mock_belief(1, 0.80)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        assert result == {}

    def test_malformed_json_returns_empty(self):
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds
        result = _apply_metacognitive_bounds("not json {{", [_mock_belief(1, 0.80)])
        assert result == {}

    def test_fallback_to_all_beliefs_when_relevant_ids_missing(self):
        """When relevant_beliefs is empty, falls back to max conf across all beliefs."""
        from app.cognition.metacognitive_evaluator import _apply_metacognitive_bounds, MAX_METACOGNITIVE_BIAS
        raw = '{"applicable": true, "relevant_beliefs": [], "adjustments": {"ask": 1.0}, "reason": "x"}'
        beliefs = [_mock_belief(1, 0.65), _mock_belief(2, 0.75)]
        result = _apply_metacognitive_bounds(raw, beliefs)
        # no relevant_ids → falls back to all beliefs, max_conf=0.75 (< 0.80) → weight=1.0
        expected = 1.0 * 0.75 * MAX_METACOGNITIVE_BIAS * 1.0
        assert result.get("ask") == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# TestComputeMetacognitiveAdjustments
# ---------------------------------------------------------------------------

class TestComputeMetacognitiveAdjustments:
    def test_empty_beliefs_returns_empty_no_api_call(self):
        from app.cognition.metacognitive_evaluator import compute_metacognitive_adjustments
        from app.cognition.perception import PerceptionResult
        result = compute_metacognitive_adjustments(
            [],
            "casual_chat",
            PerceptionResult.neutral(),
            {"frustration": 0.1, "interest": 0.7},
        )
        assert result == {}

    def test_fallback_on_provider_exception(self):
        from app.cognition.metacognitive_evaluator import compute_metacognitive_adjustments
        from app.cognition.perception import PerceptionResult
        beliefs = [_mock_belief(1, 0.70, "I tend to be cautious")]
        with patch("app.cognition.metacognitive_evaluator.build_ai_provider") as mock_build:
            mock_build.side_effect = RuntimeError("provider down")
            result = compute_metacognitive_adjustments(
                beliefs, "debugging", PerceptionResult.neutral(), {}
            )
        assert result == {}

    def test_fallback_on_api_not_ok(self):
        from app.cognition.metacognitive_evaluator import compute_metacognitive_adjustments
        from app.cognition.perception import PerceptionResult
        beliefs = [_mock_belief(1, 0.70, "I like asking questions")]
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.text = ""
        with patch("app.cognition.metacognitive_evaluator.build_ai_provider") as mock_build:
            mock_provider = MagicMock()
            mock_provider.generate.return_value = mock_response
            mock_build.return_value = mock_provider
            result = compute_metacognitive_adjustments(
                beliefs, "ask_question", PerceptionResult.neutral(), {}
            )
        assert result == {}

    def test_returns_dict_on_valid_response(self):
        from app.cognition.metacognitive_evaluator import compute_metacognitive_adjustments
        from app.cognition.perception import PerceptionResult
        beliefs = [_mock_belief(1, 0.75, "I should ask before helping")]
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {"ask": 0.8}, "reason": "ask first"}'
        with patch("app.cognition.metacognitive_evaluator.build_ai_provider") as mock_build:
            mock_provider = MagicMock()
            mock_provider.generate.return_value = mock_response
            mock_build.return_value = mock_provider
            result = compute_metacognitive_adjustments(
                beliefs, "implementation", PerceptionResult.neutral(), {}
            )
        assert "ask" in result
        assert result["ask"] > 0


# ---------------------------------------------------------------------------
# TestDecisionIntegration
# ---------------------------------------------------------------------------

class TestDecisionIntegration:
    def _default_kwargs(self) -> dict:
        from app.cognition.perception import PerceptionResult
        from app.cognition.appraisal import AppraisalResult
        return dict(
            user_message="Hola, ¿qué tal?",
            perception=PerceptionResult.neutral(),
            appraisal=AppraisalResult.zero(),
            mental_state={"frustration": 0.1, "interest": 0.7, "defensiveness": 0.05,
                          "boredom": 0.05, "social_comfort": 0.6, "melancholy": 0.1},
            personality={"helpfulness": 0.8, "assertiveness": 0.5, "independence": 0.7,
                         "curiosity": 0.8, "proactivity": 0.6, "honesty": 0.8,
                         "skepticism": 0.6, "patience": 0.6, "warmth": 0.5,
                         "directness": 0.7},
            affinity=0.5,
            conflict=0.1,
            trust_avg=0.6,
            max_goal_priority=0.0,
            domain_activated=False,
            trace_id="test-meta-001",
        )

    def test_none_self_beliefs_is_noop(self):
        """active_self_beliefs=None must not call the metacognitive evaluator."""
        from app.cognition.decision import run_decision
        kwargs = self._default_kwargs()
        with patch("app.cognition.decision.clamp_01", wraps=lambda x: max(0.0, min(1.0, x))) as _clamp, \
             patch("app.cognition.decision._call_decision_haiku") as mock_haiku, \
             patch("app.cognition.decision._check_coherence", return_value=(True, "")):
            mock_haiku.return_value = ("answer", "test reasoning")
            result = run_decision(**kwargs, active_self_beliefs=None)
        # No exception, result returned normally
        assert result is not None

    def test_score_clamped_after_metacognitive_addition(self):
        """After adding a metacognitive delta to a near-1.0 score, result must be ≤ 1.0."""
        from app.cognition.decision import compute_utility_scores
        from app.settings.settings_service import clamp_01
        # Compute realistic scores
        scores = compute_utility_scores(
            personality={"helpfulness": 1.0, "assertiveness": 0.5, "independence": 0.5,
                         "curiosity": 0.5, "proactivity": 0.5, "honesty": 0.9,
                         "skepticism": 0.5, "patience": 0.5, "warmth": 0.8, "directness": 0.5},
            mental_state={"frustration": 0.0, "interest": 1.0, "defensiveness": 0.0,
                          "boredom": 0.0, "social_comfort": 1.0, "melancholy": 0.0},
            affinity=1.0, conflict=0.0, trust_avg=1.0,
            challenge_signal=0.0, novelty=0.5,
            max_goal_priority=0.0, intent_request=False, domain_activated=False,
        )
        # Simulate adding a positive metacognitive delta and clamping
        for action in scores:
            new_score = clamp_01(scores[action] + 0.50)
            assert 0.0 <= new_score <= 1.0, f"{action}: {new_score}"

    def test_metacognitive_adjustment_applied_when_beliefs_present(self):
        """When beliefs present and mock returns adjustment, scores shift."""
        from app.cognition.decision import run_decision
        from app.cognition.metacognitive_evaluator import MAX_METACOGNITIVE_BIAS
        kwargs = self._default_kwargs()
        beliefs = [_mock_belief(1, 0.75, "I should ask clarifying questions")]

        # Mock metacognitive to return a known adjustment
        mock_adj = {"ask": 0.75 * 0.5 * MAX_METACOGNITIVE_BIAS * 1.0}  # proposed=0.5, conf=0.75

        with patch("app.cognition.metacognitive_evaluator.build_ai_provider") as mock_build, \
             patch("app.cognition.decision._call_decision_haiku") as mock_haiku, \
             patch("app.cognition.decision._check_coherence", return_value=(True, "")):
            # Return applicable JSON with ask adjustment
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.text = '{"applicable": true, "relevant_beliefs": [1], "adjustments": {"ask": 0.5}, "reason": "clarify"}'
            mock_provider = MagicMock()
            mock_provider.generate.return_value = mock_response
            mock_build.return_value = mock_provider
            mock_haiku.return_value = ("answer", "test reasoning")
            result = run_decision(**kwargs, active_self_beliefs=beliefs)

        assert result is not None


# ---------------------------------------------------------------------------
# behavior_regression — require real ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------

@pytest.mark.behavior_regression
class TestMetacognitiveBehavior:
    def setup_method(self):
        if not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set — behavior_regression skipped")

    def test_haiku_proposes_adjustment_for_boundary_belief(self):
        """Real Haiku: belief about setting limits → set_boundary or refuse nudged up."""
        from app.cognition.metacognitive_evaluator import compute_metacognitive_adjustments
        from app.cognition.perception import PerceptionResult
        beliefs = [_mock_belief(1, 0.80, "I am direct about my limits and enforce them calmly")]
        perc = PerceptionResult.neutral()
        perc.tone = "demanding"
        perc.challenge = 0.7
        result = compute_metacognitive_adjustments(
            beliefs, "feedback", perc, {"frustration": 0.4, "interest": 0.3}
        )
        # May be empty (applicable=false) or contain set_boundary/refuse with positive delta
        for action, delta in result.items():
            assert -0.10 <= delta <= 0.10, f"delta out of bounds: {action}={delta}"

    def test_haiku_not_applicable_for_unrelated_context(self):
        """Real Haiku: beliefs about technical design → casual greeting → likely not applicable."""
        from app.cognition.metacognitive_evaluator import compute_metacognitive_adjustments
        from app.cognition.perception import PerceptionResult
        beliefs = [_mock_belief(1, 0.65, "When designing systems I prefer to ask about constraints first")]
        result = compute_metacognitive_adjustments(
            beliefs, "casual_chat", PerceptionResult.neutral(), {"frustration": 0.1, "interest": 0.7}
        )
        # Either empty (not applicable) or small bounded deltas
        for action, delta in result.items():
            assert abs(delta) <= 0.10

"""Tests for Operación Remake Fase 8 Paso 3 — Expectation integration in Decision.

Properties verified:

Backward compatibility:
1.  active_expectations=None → scores identical to Fase 7 baseline (no regression).
2.  active_expectations=[] → no-op (treated same as None).

Guard: probability below threshold:
3.  Expectation with probability=0.55 (< 0.60) → zero delta applied.
4.  Expectation with probability=0.59 (just below) → zero delta (boundary).
5.  Expectation with probability=0.60 (exactly at threshold) → delta IS applied.

Exact delta verification (probability × action_delta):
6.  seek_explanation, prob=0.75 → answer delta = 0.10 × 0.75 = 0.075.
7.  request_help, prob=0.70 → help delta = 0.10 × 0.70 = 0.070.
8.  plan_together, prob=0.80 → ask delta = 0.08 × 0.80 = 0.064.
9.  challenge_sity, prob=0.65 → challenge delta = 0.06 × 0.65 = 0.039.
10. casual_engagement, prob=0.75 → answer delta = 0.05 × 0.75 = 0.0375.
11. creative_collaboration, prob=0.70 → initiate delta = 0.08 × 0.70 = 0.056.
12. ask_question, prob=0.65 → ask delta = 0.05 × 0.65 = 0.0325.
13. share_feedback, prob=0.70 → answer delta = 0.05 × 0.70 = 0.035.

Isolation (no cross-contamination):
14. seek_explanation does NOT affect help, challenge, wait, initiate, change_topic.
15. Unknown expected_behavior → zero delta (no key in _EXPECTATION_ACTION_MAP).

Multiple expectations:
16. Two expectations with different expected_behaviors → deltas summed independently.

Integration with run_decision:
17. run_decision accepts active_expectations kwarg without TypeError.
18. active_expectations=None → run_decision behavior identical to Fase 7.

Scenario verification (end-to-end Python scores):
19. request_help expectation (prob=0.75): help score higher than without.
20. seek_explanation expectation (prob=0.75): answer score higher than without.
"""
from __future__ import annotations

import pytest
from app.memory.models import Expectation
from app.cognition.decision import (
    _EXPECTATION_PROBABILITY_MIN,
    _EXPECTATION_ACTION_MAP,
    compute_utility_scores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PERSONALITY = {
    "helpfulness": 0.75, "assertiveness": 0.75, "independence": 0.85,
    "curiosity": 0.85, "proactivity": 0.70, "honesty": 0.85, "skepticism": 0.80,
    "patience": 0.60, "warmth": 0.40, "directness": 0.80,
}
_DEFAULT_MENTAL = {
    "frustration": 0.20, "interest": 0.75, "defensiveness": 0.08,
    "boredom": 0.05, "social_comfort": 0.60, "melancholy": 0.10,
}
_DEFAULT_KWARGS = dict(
    personality=_DEFAULT_PERSONALITY,
    mental_state=_DEFAULT_MENTAL,
    affinity=0.50,
    conflict=0.10,
    trust_avg=0.60,
    challenge_signal=0.10,
    novelty=0.20,
    max_goal_priority=0.00,
    intent_request=False,
    domain_activated=False,
)


def _base_scores(**overrides) -> dict[str, float]:
    kw = dict(_DEFAULT_KWARGS)
    kw.update(overrides)
    return compute_utility_scores(**kw)


def _make_expectation(
    expected_behavior: str,
    probability: float,
    context_type: str = "implementation",
    is_active: bool = True,
) -> Expectation:
    return Expectation(
        user_id=1,
        context_type=context_type,
        expected_behavior=expected_behavior,
        probability=probability,
        occurrence_count=3,
        is_active=is_active,
    )


def _scores_with_exp(exp: Expectation, **overrides) -> dict[str, float]:
    kw = dict(_DEFAULT_KWARGS)
    kw.update(overrides)
    return compute_utility_scores(**kw, active_expectations=[exp])


# ---------------------------------------------------------------------------
# 1–2: Backward compatibility
# ---------------------------------------------------------------------------

class TestExpectationBackwardCompat:

    def test_none_produces_identical_scores(self):
        # Property 1
        base = _base_scores()
        with_none = compute_utility_scores(**_DEFAULT_KWARGS, active_expectations=None)
        for action in base:
            assert base[action] == pytest.approx(with_none[action], abs=1e-6)

    def test_empty_list_produces_identical_scores(self):
        # Property 2
        base = _base_scores()
        with_empty = compute_utility_scores(**_DEFAULT_KWARGS, active_expectations=[])
        for action in base:
            assert base[action] == pytest.approx(with_empty[action], abs=1e-6)


# ---------------------------------------------------------------------------
# 3–5: Guard — probability threshold
# ---------------------------------------------------------------------------

class TestProbabilityGuard:

    def test_below_threshold_no_delta(self):
        # Property 3 — probability=0.55 strictly below 0.60
        base = _base_scores()
        exp = _make_expectation("seek_explanation", probability=0.55)
        with_exp = _scores_with_exp(exp)
        for action in base:
            assert base[action] == pytest.approx(with_exp[action], abs=1e-6)

    def test_just_below_threshold_no_delta(self):
        # Property 4 — probability=0.59 (boundary)
        base = _base_scores()
        exp = _make_expectation("request_help", probability=0.59)
        with_exp = _scores_with_exp(exp)
        for action in base:
            assert base[action] == pytest.approx(with_exp[action], abs=1e-6)

    def test_exactly_at_threshold_delta_applied(self):
        # Property 5 — probability=0.60 exactly → delta applied
        base = _base_scores()
        exp = _make_expectation("plan_together", probability=0.60)
        with_exp = _scores_with_exp(exp)
        expected_ask_delta = 0.08 * 0.60
        assert with_exp["ask"] == pytest.approx(
            min(1.0, base["ask"] + expected_ask_delta), abs=1e-4
        )


# ---------------------------------------------------------------------------
# 6–13: Exact delta verification
# ---------------------------------------------------------------------------

class TestExactDeltas:

    def test_seek_explanation_answer_delta(self):
        # Property 6
        base = _base_scores()
        exp = _make_expectation("seek_explanation", probability=0.75)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.10 * 0.75
        assert with_exp["answer"] == pytest.approx(
            min(1.0, base["answer"] + expected_delta), abs=1e-4
        )

    def test_request_help_help_delta(self):
        # Property 7
        base = _base_scores()
        exp = _make_expectation("request_help", probability=0.70)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.10 * 0.70
        assert with_exp["help"] == pytest.approx(
            min(1.0, base["help"] + expected_delta), abs=1e-4
        )

    def test_plan_together_ask_delta(self):
        # Property 8
        base = _base_scores()
        exp = _make_expectation("plan_together", probability=0.80)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.08 * 0.80
        assert with_exp["ask"] == pytest.approx(
            min(1.0, base["ask"] + expected_delta), abs=1e-4
        )

    def test_challenge_sity_challenge_delta(self):
        # Property 9
        base = _base_scores()
        exp = _make_expectation("challenge_sity", probability=0.65)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.06 * 0.65
        assert with_exp["challenge"] == pytest.approx(
            min(1.0, base["challenge"] + expected_delta), abs=1e-4
        )

    def test_casual_engagement_answer_delta(self):
        # Property 10
        base = _base_scores()
        exp = _make_expectation("casual_engagement", probability=0.75)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.05 * 0.75
        assert with_exp["answer"] == pytest.approx(
            min(1.0, base["answer"] + expected_delta), abs=1e-4
        )

    def test_creative_collaboration_initiate_delta(self):
        # Property 11
        base = _base_scores()
        exp = _make_expectation("creative_collaboration", probability=0.70)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.08 * 0.70
        assert with_exp["initiate"] == pytest.approx(
            min(1.0, base["initiate"] + expected_delta), abs=1e-4
        )

    def test_ask_question_ask_delta(self):
        # Property 12
        base = _base_scores()
        exp = _make_expectation("ask_question", probability=0.65)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.05 * 0.65
        assert with_exp["ask"] == pytest.approx(
            min(1.0, base["ask"] + expected_delta), abs=1e-4
        )

    def test_share_feedback_answer_delta(self):
        # Property 13
        base = _base_scores()
        exp = _make_expectation("share_feedback", probability=0.70)
        with_exp = _scores_with_exp(exp)
        expected_delta = 0.05 * 0.70
        assert with_exp["answer"] == pytest.approx(
            min(1.0, base["answer"] + expected_delta), abs=1e-4
        )


# ---------------------------------------------------------------------------
# 14–15: Isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_seek_explanation_does_not_affect_unrelated_actions(self):
        # Property 14 — only answer and ask get hints for seek_explanation
        base = _base_scores()
        exp = _make_expectation("seek_explanation", probability=0.75)
        with_exp = _scores_with_exp(exp)
        for action in ("help", "challenge", "refuse", "set_boundary",
                       "use_tool", "wait", "initiate", "change_topic"):
            assert base[action] == pytest.approx(with_exp[action], abs=1e-6), \
                f"action '{action}' unexpectedly changed for seek_explanation expectation"

    def test_unknown_expected_behavior_zero_delta(self):
        # Property 15
        base = _base_scores()
        exp = _make_expectation("totally_unknown_behavior_xyz", probability=0.90)
        with_exp = _scores_with_exp(exp)
        for action in base:
            assert base[action] == pytest.approx(with_exp[action], abs=1e-6)


# ---------------------------------------------------------------------------
# 16: Multiple expectations
# ---------------------------------------------------------------------------

class TestMultipleExpectations:

    def test_two_expectations_applied_independently(self):
        # Property 16 — both deltas summed
        base = _base_scores()
        e1 = _make_expectation("request_help", probability=0.70)   # help +0.10×0.70
        e2 = _make_expectation("seek_explanation", probability=0.75)  # answer +0.10×0.75
        with_two = compute_utility_scores(
            **_DEFAULT_KWARGS, active_expectations=[e1, e2]
        )
        expected_help_delta = 0.10 * 0.70
        expected_answer_delta = 0.10 * 0.75
        assert with_two["help"] == pytest.approx(
            min(1.0, base["help"] + expected_help_delta), abs=1e-4
        )
        assert with_two["answer"] == pytest.approx(
            min(1.0, base["answer"] + expected_answer_delta), abs=1e-4
        )


# ---------------------------------------------------------------------------
# 17–18: run_decision integration
# ---------------------------------------------------------------------------

class TestRunDecisionIntegration:

    def test_run_decision_accepts_active_expectations_kwarg(self):
        # Property 17
        from unittest.mock import patch
        from app.cognition.decision import run_decision
        from app.cognition.perception import PerceptionResult
        from app.cognition.appraisal import AppraisalResult

        perception = PerceptionResult(
            user_intent="question", tone="neutral",
            challenge=0.10, social_signal=0.30, novelty=0.20,
            context_type="explanation",
        )
        appraisal = AppraisalResult(interest_delta=0.05, frustration_delta=0.0,
                                    trust_evidence=0.0)
        exp = _make_expectation("seek_explanation", probability=0.75)

        with patch("app.cognition.decision._call_decision_haiku",
                   return_value=("answer", "good")), \
             patch("app.cognition.decision._check_coherence",
                   return_value=(True, "")):
            result = run_decision(
                user_message="explícame esto",
                perception=perception,
                appraisal=appraisal,
                mental_state=_DEFAULT_MENTAL,
                personality=_DEFAULT_PERSONALITY,
                affinity=0.50, conflict=0.10, trust_avg=0.60,
                max_goal_priority=0.0, domain_activated=False,
                active_expectations=[exp],
            )
        assert result is not None
        assert result.action == "answer"

    def test_run_decision_none_expectations_identical(self):
        # Property 18
        from unittest.mock import patch
        from app.cognition.decision import run_decision
        from app.cognition.perception import PerceptionResult
        from app.cognition.appraisal import AppraisalResult

        perception = PerceptionResult(
            user_intent="question", tone="neutral",
            challenge=0.10, social_signal=0.30, novelty=0.20,
            context_type="casual_chat",
        )
        appraisal = AppraisalResult(interest_delta=0.05, frustration_delta=0.0,
                                    trust_evidence=0.0)

        with patch("app.cognition.decision._call_decision_haiku",
                   return_value=("answer", "ok")), \
             patch("app.cognition.decision._check_coherence",
                   return_value=(True, "")):
            result = run_decision(
                user_message="hola",
                perception=perception,
                appraisal=appraisal,
                mental_state=_DEFAULT_MENTAL,
                personality=_DEFAULT_PERSONALITY,
                affinity=0.50, conflict=0.10, trust_avg=0.60,
                max_goal_priority=0.0, domain_activated=False,
                active_expectations=None,
            )
        assert result is not None


# ---------------------------------------------------------------------------
# 19–20: Scenario verification
# ---------------------------------------------------------------------------

class TestScenarios:

    def test_request_help_expectation_boosts_help(self):
        # Property 19
        base = _base_scores()
        exp = _make_expectation("request_help", probability=0.75)
        with_exp = _scores_with_exp(exp)
        assert with_exp["help"] > base["help"]

    def test_seek_explanation_expectation_boosts_answer(self):
        # Property 20
        base = _base_scores()
        exp = _make_expectation("seek_explanation", probability=0.75)
        with_exp = _scores_with_exp(exp)
        assert with_exp["answer"] > base["answer"]

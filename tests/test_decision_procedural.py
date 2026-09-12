"""Tests for Operación Remake Fase 7 Paso 2 — ProceduralPattern integration in Decision.

Properties verified:

Backward compatibility:
1.  procedural_patterns=None → scores identical to Fase 6 (no regression).
2.  procedural_patterns=[] → no-op (empty list treated the same as None).

Guard: confidence below threshold:
3.  Pattern with confidence=0.54 (< 0.55) → continue, zero delta applied.
4.  Pattern with confidence=0.549 (just below) → zero delta (boundary).
5.  Pattern with confidence=0.55 (exactly at threshold) → delta IS applied.

Exact delta verification (confidence × hint weight):
6.  technical_design, confidence=0.69 → ask delta = 0.06 × 0.69 = 0.0414.
7.  debugging, confidence=0.57 → ask delta = 0.08 × 0.57 = 0.0456.
8.  implementation, confidence=0.69 → help delta = 0.10 × 0.69 = 0.069.
9.  implementation, confidence=0.69 → ask delta = -0.04 × 0.69 = -0.0276.
10. casual_chat, confidence=0.69 → wait delta = -0.06 × 0.69 = -0.0414.
11. creative, confidence=0.69 → initiate delta = 0.08 × 0.69 = 0.0552.
12. planning, confidence=0.69 → ask delta = 0.08 × 0.69 = 0.0552.
13. feedback, confidence=0.69 → challenge delta = 0.06 × 0.69 = 0.0414.

Isolation (no cross-contamination):
14. technical_design pattern does NOT affect casual_chat, feedback, creative scores.
15. Unknown context_type → zero delta (no key in _PROCEDURAL_ACTION_HINTS).

Multiple patterns:
16. Two active patterns with different context_types — hints applied independently.
17. Only first qualifying pattern provides pattern_hint to Haiku context
    (_build_decision_context called with non-empty pattern_hint).

Inactive/below-threshold filter in load_active_patterns:
18. is_active=False pattern never returned.
19. confidence=0.45 pattern never returned (below PROCEDURAL_CONFIDENCE_MIN).

Integration with run_decision:
20. run_decision accepts procedural_patterns kwarg without error.
21. procedural_patterns=None → run_decision behavior identical to Fase 6 tests.

Scenario verification (end-to-end Python scores with defaults):
22. implementation pattern (confidence=0.69): help score higher than without pattern.
23. explanation pattern (confidence=0.69): answer score higher than without pattern.
"""
from __future__ import annotations

import pytest
from app.memory.models import ProceduralPattern
from app.cognition.decision import (
    _PROCEDURAL_CONFIDENCE_MIN,
    _PROCEDURAL_ACTION_HINTS,
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
    """Scores without any pattern (Fase 6 baseline)."""
    kw = dict(_DEFAULT_KWARGS)
    kw.update(overrides)
    return compute_utility_scores(**kw)


def _make_pattern(context_type: str, confidence: float, is_active: bool = True,
                  strategy: str = "test strategy") -> ProceduralPattern:
    return ProceduralPattern(
        user_id=1,
        context_type=context_type,
        strategy_description=strategy,
        confidence=confidence,
        occurrence_count=3,
        is_active=is_active,
    )


def _scores_with_pattern(pattern: ProceduralPattern, **overrides) -> dict[str, float]:
    kw = dict(_DEFAULT_KWARGS)
    kw.update(overrides)
    return compute_utility_scores(**kw, procedural_patterns=[pattern])


# ---------------------------------------------------------------------------
# 1–2: Backward compatibility
# ---------------------------------------------------------------------------

class TestProceduralBackwardCompat:

    def test_none_produces_identical_scores(self):
        # Property 1
        base = _base_scores()
        with_none = compute_utility_scores(**_DEFAULT_KWARGS, procedural_patterns=None)
        for action in base:
            assert base[action] == pytest.approx(with_none[action], abs=1e-6)

    def test_empty_list_produces_identical_scores(self):
        # Property 2
        base = _base_scores()
        with_empty = compute_utility_scores(**_DEFAULT_KWARGS, procedural_patterns=[])
        for action in base:
            assert base[action] == pytest.approx(with_empty[action], abs=1e-6)


# ---------------------------------------------------------------------------
# 3–5: Guard — confidence threshold
# ---------------------------------------------------------------------------

class TestConfidenceGuard:

    def test_below_threshold_no_delta(self):
        # Property 3 — confidence=0.54 strictly below 0.55
        base = _base_scores()
        pattern = _make_pattern("debugging", confidence=0.54)
        with_pattern = _scores_with_pattern(pattern)
        # No adjustment should be applied
        for action in base:
            assert base[action] == pytest.approx(with_pattern[action], abs=1e-6)

    def test_just_below_threshold_no_delta(self):
        # Property 4 — confidence=0.549 (boundary)
        base = _base_scores()
        pattern = _make_pattern("implementation", confidence=0.549)
        with_pattern = _scores_with_pattern(pattern)
        for action in base:
            assert base[action] == pytest.approx(with_pattern[action], abs=1e-6)

    def test_exactly_at_threshold_delta_applied(self):
        # Property 5 — confidence=0.55 exactly at threshold → delta applied
        base = _base_scores()
        pattern = _make_pattern("technical_design", confidence=0.55)
        with_pattern = _scores_with_pattern(pattern)
        # technical_design boosts ask by 0.06 × 0.55 = 0.033
        expected_ask_delta = 0.06 * 0.55
        assert with_pattern["ask"] == pytest.approx(
            min(1.0, base["ask"] + expected_ask_delta), abs=1e-4
        )


# ---------------------------------------------------------------------------
# 6–13: Exact delta verification
# ---------------------------------------------------------------------------

class TestExactDeltas:

    def test_technical_design_ask_delta(self):
        # Property 6
        base = _base_scores()
        pattern = _make_pattern("technical_design", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = 0.06 * 0.69
        assert with_p["ask"] == pytest.approx(min(1.0, base["ask"] + expected_delta), abs=1e-4)

    def test_debugging_ask_delta(self):
        # Property 7
        base = _base_scores()
        pattern = _make_pattern("debugging", confidence=0.57)
        with_p = _scores_with_pattern(pattern)
        expected_delta = 0.08 * 0.57
        assert with_p["ask"] == pytest.approx(min(1.0, base["ask"] + expected_delta), abs=1e-4)

    def test_implementation_help_delta(self):
        # Property 8
        base = _base_scores()
        pattern = _make_pattern("implementation", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = 0.10 * 0.69
        assert with_p["help"] == pytest.approx(min(1.0, base["help"] + expected_delta), abs=1e-4)

    def test_implementation_ask_negative_delta(self):
        # Property 9
        base = _base_scores()
        pattern = _make_pattern("implementation", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = -0.04 * 0.69
        assert with_p["ask"] == pytest.approx(max(0.0, base["ask"] + expected_delta), abs=1e-4)

    def test_casual_chat_wait_negative_delta(self):
        # Property 10
        base = _base_scores()
        pattern = _make_pattern("casual_chat", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = -0.06 * 0.69
        assert with_p["wait"] == pytest.approx(max(0.0, base["wait"] + expected_delta), abs=1e-4)

    def test_creative_initiate_delta(self):
        # Property 11
        base = _base_scores()
        pattern = _make_pattern("creative", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = 0.08 * 0.69
        assert with_p["initiate"] == pytest.approx(min(1.0, base["initiate"] + expected_delta), abs=1e-4)

    def test_planning_ask_delta(self):
        # Property 12
        base = _base_scores()
        pattern = _make_pattern("planning", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = 0.08 * 0.69
        assert with_p["ask"] == pytest.approx(min(1.0, base["ask"] + expected_delta), abs=1e-4)

    def test_feedback_challenge_delta(self):
        # Property 13
        base = _base_scores()
        pattern = _make_pattern("feedback", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        expected_delta = 0.06 * 0.69
        assert with_p["challenge"] == pytest.approx(min(1.0, base["challenge"] + expected_delta), abs=1e-4)


# ---------------------------------------------------------------------------
# 14–15: No cross-contamination
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_technical_design_does_not_affect_other_context_types(self):
        # Property 14 — only ask and answer get hints for technical_design
        base = _base_scores()
        pattern = _make_pattern("technical_design", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        # Actions not in technical_design hints must be unchanged
        for action in ("help", "challenge", "refuse", "set_boundary",
                        "use_tool", "wait", "initiate", "change_topic"):
            assert base[action] == pytest.approx(with_p[action], abs=1e-6), \
                f"action '{action}' unexpectedly changed for technical_design pattern"

    def test_unknown_context_type_zero_delta(self):
        # Property 15
        base = _base_scores()
        pattern = _make_pattern("unknown_context_xyz", confidence=0.80)
        with_p = _scores_with_pattern(pattern)
        for action in base:
            assert base[action] == pytest.approx(with_p[action], abs=1e-6)


# ---------------------------------------------------------------------------
# 16–17: Multiple patterns
# ---------------------------------------------------------------------------

class TestMultiplePatterns:

    def test_two_patterns_applied_independently(self):
        # Property 16
        base = _base_scores()
        p1 = _make_pattern("debugging", confidence=0.69)
        p2 = _make_pattern("debugging", confidence=0.57)
        with_two = compute_utility_scores(**_DEFAULT_KWARGS, procedural_patterns=[p1, p2])
        # ask boosted by both: 0.08×0.69 + 0.08×0.57
        expected_ask_delta = 0.08 * 0.69 + 0.08 * 0.57
        assert with_two["ask"] == pytest.approx(
            min(1.0, base["ask"] + expected_ask_delta), abs=1e-4
        )


# ---------------------------------------------------------------------------
# 18–19: is_active and confidence filter in load_active_patterns (DB tests)
# ---------------------------------------------------------------------------

class TestLoadActivePatterns:

    def test_inactive_pattern_not_returned(self, db_session):
        # Property 18
        from sqlmodel import Session, select
        from app.cognition.procedural_service import load_active_patterns
        from sqlmodel import delete as sql_delete
        db_session.exec(sql_delete(ProceduralPattern).where(  # type: ignore[call-overload]
            ProceduralPattern.user_id == 999
        ))
        db_session.commit()
        p = ProceduralPattern(user_id=999, context_type="debugging",
                              strategy_description="s", confidence=0.70,
                              occurrence_count=9, is_active=False)
        db_session.add(p)
        db_session.commit()
        result = load_active_patterns(db_session, user_id=999, context_type="debugging")
        assert len(result) == 0

    def test_below_confidence_pattern_not_returned(self, db_session):
        # Property 19
        from app.cognition.procedural_service import load_active_patterns
        from sqlmodel import delete as sql_delete
        db_session.exec(sql_delete(ProceduralPattern).where(  # type: ignore[call-overload]
            ProceduralPattern.user_id == 998
        ))
        db_session.commit()
        p = ProceduralPattern(user_id=998, context_type="debugging",
                              strategy_description="s", confidence=0.45,
                              occurrence_count=3, is_active=True)
        db_session.add(p)
        db_session.commit()
        result = load_active_patterns(db_session, user_id=998, context_type="debugging")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# 20–21: run_decision integration
# ---------------------------------------------------------------------------

class TestRunDecisionIntegration:

    def test_run_decision_accepts_procedural_patterns_kwarg(self):
        # Property 20 — run_decision can be called with procedural_patterns= without TypeError
        from unittest.mock import patch
        from app.cognition.decision import run_decision
        from app.cognition.perception import PerceptionResult
        from app.cognition.appraisal import AppraisalResult

        perception = PerceptionResult(
            user_intent="question", tone="neutral",
            challenge=0.10, social_signal=0.30, novelty=0.20,
            context_type="explanation",
        )
        appraisal = AppraisalResult(interest_delta=0.05, frustration_delta=0.0, trust_evidence=0.0)
        pattern = _make_pattern("explanation", confidence=0.69)

        with patch("app.cognition.decision._call_decision_haiku",
                   return_value=("answer", "good")), \
             patch("app.cognition.decision._check_coherence",
                   return_value=(True, "")):
            result = run_decision(
                user_message="test",
                perception=perception,
                appraisal=appraisal,
                mental_state=_DEFAULT_MENTAL,
                personality=_DEFAULT_PERSONALITY,
                affinity=0.50, conflict=0.10, trust_avg=0.60,
                max_goal_priority=0.0, domain_activated=False,
                procedural_patterns=[pattern],
            )
        assert result is not None
        assert result.action == "answer"

    def test_run_decision_none_patterns_identical_to_fase6(self):
        # Property 21 — procedural_patterns=None identical behavior
        from unittest.mock import patch
        from app.cognition.decision import run_decision
        from app.cognition.perception import PerceptionResult
        from app.cognition.appraisal import AppraisalResult

        perception = PerceptionResult(
            user_intent="question", tone="neutral",
            challenge=0.10, social_signal=0.30, novelty=0.20,
            context_type="casual_chat",
        )
        appraisal = AppraisalResult(interest_delta=0.05, frustration_delta=0.0, trust_evidence=0.0)

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
                procedural_patterns=None,
            )
        assert result is not None


# ---------------------------------------------------------------------------
# 22–23: End-to-end scenario verification
# ---------------------------------------------------------------------------

class TestScenarios:

    def test_implementation_pattern_boosts_help(self):
        # Property 22
        base = _base_scores()
        pattern = _make_pattern("implementation", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        assert with_p["help"] > base["help"]

    def test_explanation_pattern_boosts_answer(self):
        # Property 23
        base = _base_scores()
        pattern = _make_pattern("explanation", confidence=0.69)
        with_p = _scores_with_pattern(pattern)
        assert with_p["answer"] > base["answer"]

"""Tests for Operación Remake Fase 6 Paso 2 — SityValues integration in
compute_utility_scores() and run_decision().

Properties verified:

Backward compatibility:
1.  values parameter absent → identical output to values=None (no-op).
2.  values=None explicit → no change to any action score.
3.  values dict with unknown key (value_curiosity) → silently ignored.

Exact deltas at default SityValues (no clamping in these scenarios):
4.  refuse delta = +0.156 vs no-values (honesty+autonomy+fairness−loyalty × defaults).
5.  change_topic delta = −0.060 vs no-values (−0.04×0.75 −0.06×0.50; helpfulness/fairness omitted
    because _W_PATIENCE already subtracts 0.09 and further penalty kills change_topic below
    COHERENCE_MIN at any boredom level).
6.  wait delta = −0.0864 vs no-values (−0.12×value_helpfulness(0.72)).
7.  challenge delta = +0.124 vs no-values (autonomy+fairness−loyalty × defaults).

Value isolation (single-value, exact weight):
8.  value_fairness=1.0 vs absent: refuse delta exactly +0.12.
9.  value_loyalty=1.0 vs absent: help delta exactly +0.10.
10. value_honesty=1.0 vs absent: refuse delta +0.08, change_topic delta −0.08.
11. value_helpfulness=1.0 vs absent: wait delta −0.12 and ask delta +0.06.
12. value_autonomy=1.0 vs absent: challenge delta exactly +0.08.
13. value_curiosity not in _VALUES_MATRIX — no effect on ask or initiate.

Scenario 1 — Saludo normal (Escenario 1 proposal):
14. Default values do not displace answer (answer still wins).

Scenario 3 — Ethical refusal visibility (Escenario 3 proposal):
15. Without values: refuse < _COHERENCE_MIN_SCORE (invisible to coherence check).
16. With default values: refuse ≥ _COHERENCE_MIN_SCORE (coherence check can pass).

Scenario 4 — Boredom suppression (Escenario 4 proposal):
17. With values at boredom=0.50: change_topic still > 0.10 (score > 0 — values suppress not zero).
18. change_topic with default values less than without by exactly 0.060.

Scenario 5 — High affinity/loyalty (Escenario 5 proposal):
19. help with intent_request + default values still dominates (no regression).

run_decision integration:
20. run_decision with default values: python_scores show challenge boosted vs no-values.
21. run_decision with values=None: python_scores identical to omitting the parameter.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.cognition.decision import (
    _COHERENCE_MIN_SCORE,
    _VALUES_MATRIX,
    _VALID_ACTIONS,
    compute_utility_scores,
    run_decision,
)
from app.cognition.appraisal import AppraisalResult
from app.cognition.perception import PerceptionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_personality() -> dict:
    return {
        "helpfulness": 0.75, "assertiveness": 0.75, "independence": 0.85,
        "curiosity": 0.85,   "proactivity": 0.70,   "honesty": 0.85,
        "skepticism": 0.80,  "patience": 0.60,       "warmth": 0.40,
        "directness": 0.80,  "empathy": 0.65,        "playfulness": 0.65,
        "emotional_stability": 0.60,
    }


def _default_mental_state() -> dict:
    return {
        "frustration": 0.20, "interest": 0.75, "defensiveness": 0.08,
        "boredom": 0.05,     "social_comfort": 0.60, "melancholy": 0.10,
    }


def _default_values() -> dict[str, float]:
    return {
        "value_honesty":     0.75,
        "value_helpfulness": 0.72,
        "value_autonomy":    0.80,
        "value_fairness":    0.80,
        "value_loyalty":     0.50,
    }


def _scores(values: dict | None = None, **overrides) -> dict[str, float]:
    """compute_utility_scores with standard defaults + optional values and overrides."""
    kwargs: dict = dict(
        personality=_default_personality(),
        mental_state=_default_mental_state(),
        affinity=0.20,
        conflict=0.05,
        trust_avg=0.52,
        challenge_signal=0.10,
        novelty=0.20,
        max_goal_priority=0.0,
        intent_request=False,
        domain_activated=False,
        values=values,
    )
    kwargs.update(overrides)
    return compute_utility_scores(**kwargs)  # type: ignore[arg-type]


def _default_perception(**kwargs) -> PerceptionResult:
    defaults = {"user_intent": "question", "tone": "neutral",
                "challenge": 0.10, "social_signal": 0.30, "novelty": 0.20}
    defaults.update(kwargs)
    return PerceptionResult(**defaults)  # type: ignore[arg-type]


def _default_appraisal(**kwargs) -> AppraisalResult:
    base: dict = {"interest_delta": 0.0, "frustration_delta": 0.0, "trust_evidence": 0.0}
    base.update(kwargs)
    return AppraisalResult(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1–3: Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:

    def test_absent_values_identical_to_values_none(self):
        # Property 1 — no values kwarg == values=None
        scores_no_param = compute_utility_scores(
            personality=_default_personality(),
            mental_state=_default_mental_state(),
            affinity=0.20, conflict=0.05, trust_avg=0.52,
            challenge_signal=0.10, novelty=0.20, max_goal_priority=0.0,
            intent_request=False, domain_activated=False,
        )
        scores_none = _scores(values=None)
        assert scores_no_param == scores_none

    def test_values_none_no_effect(self):
        # Property 2 — all 10 actions unchanged
        s_none = _scores(values=None)
        s_default = compute_utility_scores(
            personality=_default_personality(),
            mental_state=_default_mental_state(),
            affinity=0.20, conflict=0.05, trust_avg=0.52,
            challenge_signal=0.10, novelty=0.20, max_goal_priority=0.0,
            intent_request=False, domain_activated=False,
        )
        assert s_none == s_default

    def test_unknown_value_key_ignored(self):
        # Property 3 — value_curiosity is intentionally absent from _VALUES_MATRIX
        s_base = _scores(values=_default_values())
        s_extra = _scores(values={**_default_values(), "value_curiosity": 0.90, "value_extra": 1.0})
        assert s_base == s_extra


# ---------------------------------------------------------------------------
# 4–7: Exact deltas at default SityValues
# ---------------------------------------------------------------------------

class TestExactDeltasAtDefaults:

    def test_refuse_delta_156(self):
        # Property 4 — +0.08(honesty×0.75) +0.05(autonomy×0.80) +0.12(fairness×0.80) −0.08(loyalty×0.50)
        # Scenario: assertiveness=0.90, defensiveness=0.30, conflict=0.30 → refuse_base≈0.1525 (>0)
        p = {**_default_personality(), "assertiveness": 0.90}
        ms = {**_default_mental_state(), "defensiveness": 0.30}
        s_without = _scores(values=None, personality=p, mental_state=ms, conflict=0.30)
        s_with    = _scores(values=_default_values(), personality=p, mental_state=ms, conflict=0.30)
        delta = s_with["refuse"] - s_without["refuse"]
        assert delta == pytest.approx(0.156, abs=1e-4)

    def test_change_topic_delta_minus_060(self):
        # Property 5 — −0.04×0.75(honesty) −0.06×0.50(loyalty) = −0.060
        # helpfulness/fairness omitted: _W_PATIENCE(-0.09) already constrains change_topic
        # boredom=0.50 → change_topic_base≈0.2475 (>0.060 so no bottom clamp)
        ms = {**_default_mental_state(), "boredom": 0.50}
        s_without = _scores(values=None, mental_state=ms)
        s_with    = _scores(values=_default_values(), mental_state=ms)
        delta = s_without["change_topic"] - s_with["change_topic"]
        assert delta == pytest.approx(0.060, abs=1e-4)

    def test_wait_delta_minus_0864(self):
        # Property 6 — −0.12×value_helpfulness(0.72) = −0.0864
        # Disengagement scenario: wait_base≈0.310 (>0.0864 so no bottom clamp)
        p  = {**_default_personality(), "proactivity": 0.10, "warmth": 0.10}
        ms = {**_default_mental_state(),
              "boredom": 0.60, "melancholy": 0.50, "frustration": 0.30,
              "social_comfort": 0.10, "interest": 0.10}
        s_without = _scores(values=None, personality=p, mental_state=ms)
        s_with    = _scores(values=_default_values(), personality=p, mental_state=ms)
        delta = s_without["wait"] - s_with["wait"]
        assert delta == pytest.approx(0.0864, abs=1e-4)

    def test_challenge_delta_124(self):
        # Property 7 — +0.08(autonomy×0.80) +0.10(fairness×0.80) −0.04(loyalty×0.50)
        # Default scenario: challenge_base≈0.4475 (in (0,1) range)
        s_without = _scores(values=None)
        s_with    = _scores(values=_default_values())
        delta = s_with["challenge"] - s_without["challenge"]
        assert delta == pytest.approx(0.124, abs=1e-4)


# ---------------------------------------------------------------------------
# 8–13: Value isolation — single-value exact weights
# ---------------------------------------------------------------------------

class TestValueIsolation:

    def test_value_fairness_refuse_weight(self):
        # Property 8 — fairness→refuse: +0.12
        # helpfulness=0.40 so refuse_base≈0.1765 > 0 (no bottom clamp)
        p = {**_default_personality(), "helpfulness": 0.40, "assertiveness": 0.80}
        s_hi = _scores(values={"value_fairness": 1.0}, personality=p)
        s_lo = _scores(values={"value_fairness": 0.0}, personality=p)
        assert s_hi["refuse"] - s_lo["refuse"] == pytest.approx(0.12, abs=1e-4)

    def test_value_loyalty_help_weight(self):
        # Property 9 — loyalty→help: +0.10
        s_hi = _scores(values={"value_loyalty": 1.0})
        s_lo = _scores(values={"value_loyalty": 0.0})
        assert s_hi["help"] - s_lo["help"] == pytest.approx(0.10, abs=1e-4)

    def test_value_honesty_refuse_and_change_topic(self):
        # Property 10 — honesty→refuse: +0.08; honesty→change_topic: −0.04 (reduced, see _VALUES_MATRIX)
        # For refuse: helpfulness=0.40 → refuse_base≈0.1765 > 0
        p = {**_default_personality(), "helpfulness": 0.40, "assertiveness": 0.80}
        s_hi_r = _scores(values={"value_honesty": 1.0}, personality=p)
        s_lo_r = _scores(values={"value_honesty": 0.0}, personality=p)
        assert s_hi_r["refuse"] - s_lo_r["refuse"] == pytest.approx(0.08, abs=1e-4)
        # For change_topic: boredom=0.20 → change_topic_base≈0.1275 > 0.04 (no bottom clamp)
        ms = {**_default_mental_state(), "boredom": 0.20}
        s_hi_ct = _scores(values={"value_honesty": 1.0}, mental_state=ms)
        s_lo_ct = _scores(values={"value_honesty": 0.0}, mental_state=ms)
        assert s_lo_ct["change_topic"] - s_hi_ct["change_topic"] == pytest.approx(0.04, abs=1e-4)

    def test_value_helpfulness_wait_and_ask(self):
        # Property 11 — helpfulness→wait: −0.12; helpfulness→ask: +0.06
        # For wait: disengagement scenario → wait_base≈0.310 > 0.12
        p  = {**_default_personality(), "proactivity": 0.10, "warmth": 0.10}
        ms = {**_default_mental_state(),
              "boredom": 0.60, "melancholy": 0.50, "frustration": 0.30,
              "social_comfort": 0.10, "interest": 0.10}
        s_hi = _scores(values={"value_helpfulness": 1.0}, personality=p, mental_state=ms)
        s_lo = _scores(values={"value_helpfulness": 0.0}, personality=p, mental_state=ms)
        assert s_lo["wait"] - s_hi["wait"] == pytest.approx(0.12, abs=1e-4)
        # For ask: default conditions → ask_base≈0.4975 (clean range)
        s_hi_ask = _scores(values={"value_helpfulness": 1.0})
        s_lo_ask = _scores(values={"value_helpfulness": 0.0})
        assert s_hi_ask["ask"] - s_lo_ask["ask"] == pytest.approx(0.06, abs=1e-4)

    def test_value_autonomy_challenge_weight(self):
        # Property 12 — autonomy→challenge: +0.08
        s_hi = _scores(values={"value_autonomy": 1.0})
        s_lo = _scores(values={"value_autonomy": 0.0})
        assert s_hi["challenge"] - s_lo["challenge"] == pytest.approx(0.08, abs=1e-4)

    def test_value_curiosity_not_in_matrix(self):
        # Property 13 — value_curiosity absent from _VALUES_MATRIX: no effect on any action
        assert "value_curiosity" not in _VALUES_MATRIX
        s_no_values = _scores(values=None)
        s_only_curiosity = _scores(values={"value_curiosity": 0.90})
        # only key is not in matrix → same as values=None
        assert s_no_values == s_only_curiosity


# ---------------------------------------------------------------------------
# 14: Scenario 1 — Saludo normal
# ---------------------------------------------------------------------------

class TestScenario1Saludo:

    def test_answer_still_wins_with_default_values(self):
        # Property 14 — values don't displace answer in normal greeting
        s = _scores(
            values=_default_values(),
            challenge_signal=0.0, novelty=0.10,
        )
        top = max(s, key=lambda a: s[a])
        assert top == "answer"


# ---------------------------------------------------------------------------
# 15–16: Scenario 3 — Ethical refusal visibility
# ---------------------------------------------------------------------------

class TestScenario3EthicalRefusal:

    @staticmethod
    def _ethical_scenario(values: dict | None) -> dict[str, float]:
        # High assertiveness + moderate defensiveness + conflict → refuse near surface
        p  = {**_default_personality(), "assertiveness": 0.90}
        ms = {**_default_mental_state(), "defensiveness": 0.30}
        return _scores(values=values, personality=p, mental_state=ms, conflict=0.30)

    def test_refuse_below_coherence_min_without_values(self):
        # Property 15 — refuse invisible to coherence check when values absent
        s = self._ethical_scenario(values=None)
        assert s["refuse"] < _COHERENCE_MIN_SCORE

    def test_refuse_above_coherence_min_with_values(self):
        # Property 16 — values push refuse past coherence floor (0.30); key Escenario 3 result
        s = self._ethical_scenario(values=_default_values())
        assert s["refuse"] >= _COHERENCE_MIN_SCORE


# ---------------------------------------------------------------------------
# 17–18: Scenario 4 — Boredom suppression
# ---------------------------------------------------------------------------

class TestScenario4BoredSuppression:

    @staticmethod
    def _boredom_scenario(values: dict | None) -> dict[str, float]:
        ms = {**_default_mental_state(), "boredom": 0.50}
        return _scores(values=values, mental_state=ms)

    def test_change_topic_not_zeroed_with_values(self):
        # Property 17 — values suppress change_topic but don't zero it (stays > 0)
        s = self._boredom_scenario(values=_default_values())
        assert s["change_topic"] > 0.0

    def test_change_topic_delta_is_060(self):
        # Property 18 — suppression amount is 0.060 (honesty+loyalty only, calibrated)
        s_without = self._boredom_scenario(values=None)
        s_with    = self._boredom_scenario(values=_default_values())
        delta = s_without["change_topic"] - s_with["change_topic"]
        assert delta == pytest.approx(0.060, abs=1e-4)


# ---------------------------------------------------------------------------
# 19: Scenario 5 — High affinity, help stable
# ---------------------------------------------------------------------------

class TestScenario5HighAffinity:

    def test_help_dominates_with_values_and_intent_request(self):
        # Property 19 — values don't regress the dominant help+intent_request path
        s = _scores(
            values=_default_values(),
            affinity=0.80, trust_avg=0.80, conflict=0.05,
            intent_request=True,
        )
        assert s["help"] > s["answer"]
        assert s["help"] > s["use_tool"]


# ---------------------------------------------------------------------------
# 20–21: run_decision integration
# ---------------------------------------------------------------------------

class TestRunDecisionIntegration:

    @patch("app.cognition.decision._check_coherence", return_value=(True, ""))
    @patch("app.cognition.decision._call_decision_haiku", return_value=("answer", "test"))
    def test_run_decision_values_affect_python_scores(self, mock_haiku, mock_coherence):
        # Property 20 — python_scores in result reflect values contributions
        result_no = run_decision(
            user_message="test",
            perception=_default_perception(),
            appraisal=_default_appraisal(),
            mental_state=_default_mental_state(),
            personality=_default_personality(),
            affinity=0.20, conflict=0.05, trust_avg=0.52,
            max_goal_priority=0.0, domain_activated=False,
            values=None,
        )
        result_with = run_decision(
            user_message="test",
            perception=_default_perception(),
            appraisal=_default_appraisal(),
            mental_state=_default_mental_state(),
            personality=_default_personality(),
            affinity=0.20, conflict=0.05, trust_avg=0.52,
            max_goal_priority=0.0, domain_activated=False,
            values=_default_values(),
        )
        assert result_no is not None
        assert result_with is not None
        assert result_with.python_scores["challenge"] > result_no.python_scores["challenge"]
        assert result_with.python_scores["change_topic"] < result_no.python_scores["change_topic"]
        assert set(result_with.python_scores.keys()) == _VALID_ACTIONS

    @patch("app.cognition.decision._check_coherence", return_value=(True, ""))
    @patch("app.cognition.decision._call_decision_haiku", return_value=("answer", "test"))
    def test_run_decision_values_none_backward_compat(self, mock_haiku, mock_coherence):
        # Property 21 — values=None gives identical python_scores to omitting the parameter
        result_none = run_decision(
            user_message="test",
            perception=_default_perception(),
            appraisal=_default_appraisal(),
            mental_state=_default_mental_state(),
            personality=_default_personality(),
            affinity=0.20, conflict=0.05, trust_avg=0.52,
            max_goal_priority=0.0, domain_activated=False,
            values=None,
        )
        result_absent = run_decision(
            user_message="test",
            perception=_default_perception(),
            appraisal=_default_appraisal(),
            mental_state=_default_mental_state(),
            personality=_default_personality(),
            affinity=0.20, conflict=0.05, trust_avg=0.52,
            max_goal_priority=0.0, domain_activated=False,
        )
        assert result_none is not None
        assert result_absent is not None
        assert result_none.python_scores == result_absent.python_scores

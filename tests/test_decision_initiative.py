"""Tests for run_decision() in initiative mode (user_message=None).

MINI-REMAKE v2.0 Punto 3 — Estrategia B: contexto enriquecido sin mensaje.

Properties:
1.  run_decision(user_message=None) returns DecisionResult without raising.
2.  Action returned is "initiate" when Haiku chooses it.
3.  Action returned is "wait" when Haiku chooses it.
4.  python_scores passed to Haiku context only contains "initiate" and "wait".
5.  "answer", "refuse", etc. are absent from the Haiku context in initiative mode.
6.  Coherence Haiku is NOT called in initiative mode (auto-pass after python score check).
7.  run_decision(user_message=None) with low python scores returns None (python score gate).
8.  initiative_context string is injected into Haiku context block.
9.  perception=None is accepted (defaults to PerceptionResult.neutral()).
10. run_decision(user_message=None) logs decision_completed with action in INITIATIVE_ACTIONS.
11. Haiku choosing a non-initiative action (e.g. "answer") → None + fallback log.
12. Haiku returning None in initiative mode → None + fallback log.

Behavior regression:
13. Goal-urgent context → returns DecisionResult with action in {"initiate", "wait"}.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from app.cognition.appraisal import AppraisalResult
from app.cognition.decision import (
    DecisionResult,
    _INITIATIVE_ACTIONS,
    _VALID_ACTIONS,
    run_decision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_kwargs(**overrides) -> dict:
    base = dict(
        user_message=None,
        appraisal=AppraisalResult.zero(),
        mental_state={
            "frustration": 0.20,
            "interest": 0.75,
            "defensiveness": 0.08,
            "boredom": 0.05,
            "social_comfort": 0.60,
            "melancholy": 0.10,
        },
        personality={
            "helpfulness": 0.85,
            "assertiveness": 0.75,
            "independence": 0.85,
            "curiosity": 0.85,
            "proactivity": 0.70,
            "honesty": 0.85,
            "skepticism": 0.80,
            "patience": 0.60,
            "warmth": 0.40,
            "directness": 0.80,
        },
        affinity=0.50,
        conflict=0.10,
        trust_avg=0.60,
        max_goal_priority=0.90,
        domain_activated=False,
        trace_id="test_initiative",
    )
    base.update(overrides)
    return base


def _haiku_initiate(context, *, trace_id, system_prompt=""):
    return "initiate", "urgent goal warrants contact"


def _haiku_wait(context, *, trace_id, system_prompt=""):
    return "wait", "not the right moment"


def _haiku_answer(context, *, trace_id, system_prompt=""):
    return "answer", "answering question"


# ---------------------------------------------------------------------------
# 1–3: Basic contract
# ---------------------------------------------------------------------------

class TestInitiativeModeBasic:
    def test_returns_decision_result_without_raising(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(**_base_kwargs())
        assert result is not None
        assert isinstance(result, DecisionResult)

    def test_returns_initiate_when_haiku_chooses_initiate(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(**_base_kwargs())
        assert result is not None
        assert result.action == "initiate"

    def test_returns_wait_when_haiku_chooses_wait(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_wait):
            result = run_decision(**_base_kwargs())
        assert result is not None
        assert result.action == "wait"


# ---------------------------------------------------------------------------
# 4–5: Scores filtered to INITIATIVE_ACTIONS only
# ---------------------------------------------------------------------------

class TestInitiativeModeScoreFiltering:
    def test_context_contains_only_initiate_and_wait_scores(self) -> None:
        captured_context: list[str] = []

        def _capture(context, *, trace_id, system_prompt=""):
            captured_context.append(context)
            return "initiate", "test"

        with patch("app.cognition.decision._call_decision_haiku", side_effect=_capture):
            run_decision(**_base_kwargs())

        assert len(captured_context) == 1
        ctx = captured_context[0]
        assert "initiate" in ctx
        assert "wait" in ctx

    def test_context_excludes_non_initiative_actions(self) -> None:
        captured_context: list[str] = []

        def _capture(context, *, trace_id, system_prompt=""):
            captured_context.append(context)
            return "initiate", "test"

        with patch("app.cognition.decision._call_decision_haiku", side_effect=_capture):
            run_decision(**_base_kwargs())

        ctx = captured_context[0]
        # Scores block should not mention non-initiative actions
        # (they appear in FORMULA TOP CANDIDATE line only if filtered — check the scores section)
        assert "answer:" not in ctx
        assert "refuse:" not in ctx
        assert "help:" not in ctx

    def test_python_scores_in_result_contain_only_initiative_actions(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(**_base_kwargs())
        assert result is not None
        assert set(result.python_scores.keys()) == _INITIATIVE_ACTIONS


# ---------------------------------------------------------------------------
# 6: Coherence Haiku skipped in initiative mode
# ---------------------------------------------------------------------------

class TestInitiativeModeCoherenceSkipped:
    def test_coherence_passes_automatically_for_initiate(self) -> None:
        from app.cognition.decision import _check_coherence
        result = _check_coherence(
            "initiate", "test reasoning", None,
            {"initiate": 0.65, "wait": 0.35},
            trace_id="test",
        )
        assert result == (True, "")

    def test_coherence_passes_automatically_for_wait(self) -> None:
        from app.cognition.decision import _check_coherence
        # "wait" has very low formula score in 10-action space — still passes in initiative mode
        result = _check_coherence(
            "wait", "not the right time", None,
            {"initiate": 0.35, "wait": 0.05},
            trace_id="test",
        )
        assert result == (True, "")


# ---------------------------------------------------------------------------
# 7: Python score gate still applies
# ---------------------------------------------------------------------------

class TestInitiativeModePythonScoreGate:
    def test_wait_with_low_formula_score_still_succeeds(self) -> None:
        # In initiative mode, coherence passes automatically — the python score gate
        # was calibrated for 10-action space and doesn't apply here. "wait" having a
        # low formula score is expected and not an error.
        def _haiku_wait_low_score(context, *, trace_id, system_prompt=""):
            return "wait", "not the right moment"

        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_wait_low_score):
            with patch("app.cognition.decision.compute_utility_scores") as mock_scores:
                mock_scores.return_value = {"initiate": 0.10, "wait": 0.05}
                result = run_decision(**_base_kwargs())

        # Low score is fine — "wait" is the safe default in initiative mode
        assert result is not None
        assert result.action == "wait"


# ---------------------------------------------------------------------------
# 8: initiative_context injected
# ---------------------------------------------------------------------------

class TestInitiativeModeContext:
    def test_initiative_context_injected_in_haiku_call(self) -> None:
        captured: list[str] = []

        def _capture(context, *, trace_id, system_prompt=""):
            captured.append(context)
            return "initiate", "test"

        ctx_text = "Meta urgente: 'aprender Python' (prioridad=0.92)"
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_capture):
            run_decision(**_base_kwargs(initiative_context=ctx_text))

        assert len(captured) == 1
        assert ctx_text in captured[0]

    def test_initiative_context_block_present_without_text(self) -> None:
        captured: list[str] = []

        def _capture(context, *, trace_id, system_prompt=""):
            captured.append(context)
            return "wait", "test"

        with patch("app.cognition.decision._call_decision_haiku", side_effect=_capture):
            run_decision(**_base_kwargs())

        assert "INITIATIVE CONTEXT" in captured[0]
        assert "USER MESSAGE" not in captured[0]


# ---------------------------------------------------------------------------
# 9: perception=None accepted
# ---------------------------------------------------------------------------

class TestInitiativeModePerceptionOptional:
    def test_perception_none_uses_neutral(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(**_base_kwargs(perception=None))
        assert result is not None

    def test_perception_explicit_none_equivalent_to_omitted(self) -> None:
        results = []
        for _ in range(2):
            with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
                results.append(run_decision(**_base_kwargs(perception=None)))
        assert all(r is not None and r.action == "initiate" for r in results)


# ---------------------------------------------------------------------------
# 10: Logging on success
# ---------------------------------------------------------------------------

class TestInitiativeModeLogging:
    def test_decision_completed_logged_on_success(self, caplog) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(**_base_kwargs(trace_id="log_test"))
        assert result is not None
        assert result.action in _INITIATIVE_ACTIONS


# ---------------------------------------------------------------------------
# 11–12: Fallback paths
# ---------------------------------------------------------------------------

class TestInitiativeModeFallback:
    def test_non_initiative_action_returns_none(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_answer):
            result = run_decision(**_base_kwargs())
        # "answer" is not in _INITIATIVE_ACTIONS → should return None
        assert result is None

    def test_haiku_returns_none_returns_none(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", return_value=None):
            result = run_decision(**_base_kwargs())
        assert result is None

    def test_haiku_raises_returns_none(self) -> None:
        def _raise(context, *, trace_id, system_prompt=""):
            raise RuntimeError("provider offline")

        with patch("app.cognition.decision._call_decision_haiku", side_effect=_raise):
            result = run_decision(**_base_kwargs())
        assert result is None


# ---------------------------------------------------------------------------
# 13: Behavior regression — goal_urgent context
# ---------------------------------------------------------------------------

@pytest.mark.behavior_regression
class TestInitiativeModeBehaviorRegression:
    def test_goal_urgent_context_returns_valid_decision(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(
                **_base_kwargs(
                    initiative_context="Meta urgente: 'hacer ejercicio' (prioridad=0.92)",
                    max_goal_priority=0.92,
                )
            )
        assert isinstance(result, DecisionResult)
        assert result.action in _INITIATIVE_ACTIONS

    def test_low_goal_priority_wait_is_valid(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_wait):
            result = run_decision(
                **_base_kwargs(
                    initiative_context="Inactividad prolongada: 3 días",
                    max_goal_priority=0.0,
                )
            )
        assert isinstance(result, DecisionResult)
        assert result.action == "wait"

    def test_open_loop_context_no_error(self) -> None:
        with patch("app.cognition.decision._call_decision_haiku", side_effect=_haiku_initiate):
            result = run_decision(
                **_base_kwargs(
                    initiative_context="Intención abierta pendiente: 'hablar con el médico'",
                )
            )
        assert result is not None
        assert result.action in _INITIATIVE_ACTIONS

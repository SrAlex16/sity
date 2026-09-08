"""Tests for Operación Remake Fase 2 — Perception, Appraisal, Goal model, Goal priority.

Paso 1 properties:
1.  Perception returns PerceptionResult.neutral() when the mock provider returns non-JSON.
2.  Perception parses valid JSON correctly (all fields).
3.  Perception clamps float fields to [0, 1].
4.  Perception normalizes unknown user_intent to "other".
5.  Perception normalizes unknown tone to "neutral".
6.  Perception strips markdown code fences from JSON response.
7.  Appraisal returns AppraisalResult.zero() when the mock provider returns non-JSON.
8.  Appraisal parses valid JSON correctly (deltas + goal_updates).
9.  Appraisal clamps delta fields to [-0.3, 0.3].
10. Appraisal clamps trust_evidence to [0.0, 0.05].
11. apply_appraisal_to_mental_state applies deltas and clamps to [0, 1].
12. apply_appraisal_to_mental_state: negative frustration_delta clamps at 0 (not negative).
13. Goal user isolation: goals created for user A are not visible when querying user B.
14. Goal status lifecycle: active → resolved sets resolved_at.
15. Goal short_term vs long_term scope stored correctly.
16. Goal is_wellbeing flag stored and retrievable.
17. GoalUpdateIntent with is_wellbeing=True parsed correctly by _parse_goal_update.
18. GoalUpdateIntent with unknown scope defaults to "short_term".

Paso 2 properties — Goal priority (structural, no model call needed):
19. _irony_factor: is_wellbeing=True always returns 1.0 regardless of tone.
20. _irony_factor: is_wellbeing=True with tone="ironic" returns 1.0 (explicit bypass).
21. _irony_factor: is_wellbeing=True with tone="playful" returns 1.0 (explicit bypass).
22. _irony_factor: is_wellbeing=False with tone="ironic" returns < 1.0 (irony reduces boost).
23. _irony_factor: is_wellbeing=False with tone="neutral" returns 1.0 (no reduction).
24. _irony_factor: is_wellbeing=False with tone="serious" returns 1.0 (no reduction).
25. compute_effective_priority: wellbeing + ironic == wellbeing + neutral (key invariant).
26. compute_effective_priority: non-wellbeing + ironic < non-wellbeing + neutral.
27. compute_effective_priority: wellbeing + ironic >= non-wellbeing + ironic (same inputs).
28. compute_effective_priority: formula correctness — verify weighted average.
29. compute_effective_priority: result clamped to [0, 1] for edge inputs.
30. Appraisal parses goal_relevance from JSON correctly.
31. Appraisal zero() has empty goal_relevance list.
32. run_appraisal with active_goals=None returns empty goal_relevance (backward compat).
33. _parse_goal_relevance rejects invalid data gracefully.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.cognition.appraisal import (
    AppraisalResult,
    GoalRelevance,
    GoalUpdateIntent,
    _parse_appraisal,
    _parse_goal_relevance,
    _parse_goal_update,
    apply_appraisal_to_mental_state,
    run_appraisal,
)
from app.cognition.goal_priority import (
    BASE_WEIGHT,
    BOOST_WEIGHT,
    IRONY_REDUCTION_STRENGTH,
    _irony_factor,
    compute_effective_priority,
)
from app.cognition.perception import (
    PerceptionResult,
    _parse_perception,
    run_perception,
)
from app.memory.models import Goal, MentalState, utc_now
from app.settings.settings_service import CANONICAL_PERSONALITY


# ---------------------------------------------------------------------------
# Perception — parse unit tests (no provider call)
# ---------------------------------------------------------------------------

class TestParsePerception:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "user_intent": "request",
            "tone": "serious",
            "challenge": 0.1,
            "social_signal": 0.4,
            "novelty": 0.6,
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.user_intent == "request"
        assert result.tone == "serious"
        assert result.challenge == pytest.approx(0.1)
        assert result.social_signal == pytest.approx(0.4)
        assert result.novelty == pytest.approx(0.6)

    def test_normalizes_unknown_intent_to_other(self):
        raw = json.dumps({
            "user_intent": "UNKNOWN_CATEGORY",
            "tone": "neutral",
            "challenge": 0.0,
            "social_signal": 0.0,
            "novelty": 0.0,
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.user_intent == "other"

    def test_normalizes_unknown_tone_to_neutral(self):
        raw = json.dumps({
            "user_intent": "question",
            "tone": "ZANY",
            "challenge": 0.0,
            "social_signal": 0.0,
            "novelty": 0.0,
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.tone == "neutral"

    def test_clamps_floats_above_one(self):
        raw = json.dumps({
            "user_intent": "joke",
            "tone": "playful",
            "challenge": 5.0,
            "social_signal": 99.9,
            "novelty": 2.5,
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.challenge == pytest.approx(1.0)
        assert result.social_signal == pytest.approx(1.0)
        assert result.novelty == pytest.approx(1.0)

    def test_clamps_floats_below_zero(self):
        raw = json.dumps({
            "user_intent": "vent",
            "tone": "frustrated",
            "challenge": -0.5,
            "social_signal": -1.0,
            "novelty": -99.0,
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.challenge == pytest.approx(0.0)
        assert result.social_signal == pytest.approx(0.0)
        assert result.novelty == pytest.approx(0.0)

    def test_strips_markdown_code_fences(self):
        raw = "```json\n" + json.dumps({
            "user_intent": "greeting",
            "tone": "warm",
            "challenge": 0.0,
            "social_signal": 0.5,
            "novelty": 0.1,
        }) + "\n```"
        result = _parse_perception(raw)
        assert result is not None
        assert result.user_intent == "greeting"
        assert result.tone == "warm"

    def test_returns_none_on_invalid_json(self):
        assert _parse_perception("not json at all") is None
        assert _parse_perception("") is None
        assert _parse_perception("{}") is not None  # empty dict → defaults applied


# ---------------------------------------------------------------------------
# Perception — run_perception with mock provider (fallback path)
# ---------------------------------------------------------------------------

class TestRunPerception:
    def test_fallback_on_non_json_response(self):
        # Mock provider returns "Respuesta mock." → parse fails → neutral fallback
        result = run_perception("Hola, ¿cómo estás?", trace_id="t-perc-001")
        assert result.user_intent == "other"
        assert result.tone == "neutral"
        assert result.challenge == pytest.approx(0.1)
        assert result.social_signal == pytest.approx(0.3)
        assert result.novelty == pytest.approx(0.2)

    def test_success_with_patched_provider(self):
        valid_json = json.dumps({
            "user_intent": "vent",
            "tone": "frustrated",
            "challenge": 0.7,
            "social_signal": 0.8,
            "novelty": 0.3,
        })
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = valid_json

        mock_provider = MagicMock()
        mock_provider.generate.return_value = mock_resp

        with patch(
            "app.cognition.perception.build_ai_provider",
            return_value=mock_provider,
        ):
            result = run_perception("Me siento fatal hoy.", trace_id="t-perc-002")

        assert result.user_intent == "vent"
        assert result.tone == "frustrated"
        assert result.challenge == pytest.approx(0.7)
        assert result.social_signal == pytest.approx(0.8)

    def test_fallback_on_provider_exception(self):
        with patch(
            "app.cognition.perception.build_ai_provider",
            side_effect=RuntimeError("network error"),
        ):
            result = run_perception("test", trace_id="t-perc-003")
        assert result.user_intent == "other"
        assert result.tone == "neutral"

    def test_neutral_classmethod_values(self):
        neutral = PerceptionResult.neutral()
        assert neutral.user_intent == "other"
        assert neutral.tone == "neutral"
        assert neutral.challenge == pytest.approx(0.1)
        assert neutral.social_signal == pytest.approx(0.3)
        assert neutral.novelty == pytest.approx(0.2)

    def test_as_dict(self):
        r = PerceptionResult(
            user_intent="request",
            tone="serious",
            challenge=0.2,
            social_signal=0.5,
            novelty=0.4,
        )
        d = r.as_dict()
        assert d["user_intent"] == "request"
        assert d["tone"] == "serious"
        assert d["challenge"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Appraisal — parse unit tests (no provider call)
# ---------------------------------------------------------------------------

class TestParseAppraisal:
    def test_parses_valid_json_no_goals(self):
        raw = json.dumps({
            "interest_delta": 0.1,
            "frustration_delta": -0.05,
            "trust_evidence": 0.02,
            "goal_updates": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.interest_delta == pytest.approx(0.1)
        assert result.frustration_delta == pytest.approx(-0.05)
        assert result.trust_evidence == pytest.approx(0.02)
        assert result.goal_updates == []

    def test_parses_goal_update_create(self):
        raw = json.dumps({
            "interest_delta": 0.15,
            "frustration_delta": 0.0,
            "trust_evidence": 0.01,
            "goal_updates": [
                {
                    "action": "create",
                    "description": "Understand Alex's architecture preferences",
                    "scope": "long_term",
                    "base_importance": 0.8,
                    "is_wellbeing": False,
                }
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert len(result.goal_updates) == 1
        gu = result.goal_updates[0]
        assert gu.action == "create"
        assert gu.scope == "long_term"
        assert gu.base_importance == pytest.approx(0.8)
        assert gu.is_wellbeing is False

    def test_parses_wellbeing_goal(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.03,
            "goal_updates": [
                {
                    "action": "create",
                    "description": "Support user's emotional state",
                    "scope": "short_term",
                    "base_importance": 0.9,
                    "is_wellbeing": True,
                }
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.goal_updates[0].is_wellbeing is True

    def test_clamps_interest_delta(self):
        raw = json.dumps({
            "interest_delta": 5.0,
            "frustration_delta": -99.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.interest_delta == pytest.approx(0.3)
        assert result.frustration_delta == pytest.approx(-0.3)

    def test_clamps_trust_evidence(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 99.9,
            "goal_updates": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.trust_evidence == pytest.approx(0.05)

    def test_trust_evidence_floor_zero(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": -0.5,
            "goal_updates": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.trust_evidence == pytest.approx(0.0)

    def test_returns_none_on_invalid_json(self):
        assert _parse_appraisal("not json") is None
        assert _parse_appraisal("") is None

    def test_zero_classmethod(self):
        z = AppraisalResult.zero()
        assert z.interest_delta == pytest.approx(0.0)
        assert z.frustration_delta == pytest.approx(0.0)
        assert z.trust_evidence == pytest.approx(0.0)
        assert z.goal_updates == []


class TestParseGoalUpdateIntent:
    def test_rejects_non_create_action(self):
        assert _parse_goal_update({"action": "delete", "description": "x", "scope": "short_term", "base_importance": 0.5}) is None

    def test_rejects_missing_description(self):
        assert _parse_goal_update({"action": "create", "description": "", "scope": "short_term", "base_importance": 0.5}) is None

    def test_normalizes_unknown_scope(self):
        gu = _parse_goal_update({
            "action": "create",
            "description": "test goal",
            "scope": "INVALID",
            "base_importance": 0.5,
        })
        assert gu is not None
        assert gu.scope == "short_term"

    def test_rejects_non_dict(self):
        assert _parse_goal_update("string") is None
        assert _parse_goal_update(None) is None
        assert _parse_goal_update(42) is None


# ---------------------------------------------------------------------------
# Appraisal — run_appraisal with mock provider
# ---------------------------------------------------------------------------

class TestRunAppraisal:
    _perception = {
        "user_intent": "question",
        "tone": "curious",
        "challenge": 0.1,
        "social_signal": 0.4,
        "novelty": 0.5,
    }
    _mental_state = {
        "interest": 0.7,
        "frustration": 0.2,
        "social_comfort": 0.6,
        "valence": 0.1,
        "arousal": 0.4,
    }
    _personality = CANONICAL_PERSONALITY

    def test_fallback_on_non_json_response(self):
        result = run_appraisal(
            perception=self._perception,
            mental_state=self._mental_state,
            personality=self._personality,
            trace_id="t-app-001",
        )
        assert result.interest_delta == pytest.approx(0.0)
        assert result.frustration_delta == pytest.approx(0.0)
        assert result.trust_evidence == pytest.approx(0.0)
        assert result.goal_updates == []

    def test_success_with_patched_provider(self):
        valid_json = json.dumps({
            "interest_delta": 0.12,
            "frustration_delta": -0.03,
            "trust_evidence": 0.02,
            "goal_updates": [],
        })
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = valid_json

        mock_provider = MagicMock()
        mock_provider.generate.return_value = mock_resp

        with patch(
            "app.cognition.appraisal.build_ai_provider",
            return_value=mock_provider,
        ):
            result = run_appraisal(
                perception=self._perception,
                mental_state=self._mental_state,
                personality=self._personality,
                trace_id="t-app-002",
            )

        assert result.interest_delta == pytest.approx(0.12)
        assert result.frustration_delta == pytest.approx(-0.03)
        assert result.trust_evidence == pytest.approx(0.02)

    def test_fallback_on_provider_exception(self):
        with patch(
            "app.cognition.appraisal.build_ai_provider",
            side_effect=RuntimeError("network error"),
        ):
            result = run_appraisal(
                perception=self._perception,
                mental_state=self._mental_state,
                personality=self._personality,
                trace_id="t-app-003",
            )
        assert result.interest_delta == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Appraisal — apply_appraisal_to_mental_state
# ---------------------------------------------------------------------------

class TestApplyAppraisalToMentalState:
    def _make_state(self, interest=0.7, frustration=0.2, social_comfort=0.6) -> MentalState:
        return MentalState(
            user_id=99999,
            interest=interest,
            frustration=frustration,
            social_comfort=social_comfort,
        )

    def test_applies_positive_interest_delta(self):
        state = self._make_state(interest=0.5)
        result = AppraisalResult(interest_delta=0.2, frustration_delta=0.0, trust_evidence=0.0)
        apply_appraisal_to_mental_state(state, result)
        assert state.interest == pytest.approx(0.7)

    def test_applies_negative_interest_delta(self):
        state = self._make_state(interest=0.4)
        result = AppraisalResult(interest_delta=-0.15, frustration_delta=0.0, trust_evidence=0.0)
        apply_appraisal_to_mental_state(state, result)
        assert state.interest == pytest.approx(0.25)

    def test_clamps_interest_at_1(self):
        state = self._make_state(interest=0.95)
        result = AppraisalResult(interest_delta=0.3, frustration_delta=0.0, trust_evidence=0.0)
        apply_appraisal_to_mental_state(state, result)
        assert state.interest == pytest.approx(1.0)

    def test_clamps_frustration_at_0(self):
        state = self._make_state(frustration=0.05)
        result = AppraisalResult(interest_delta=0.0, frustration_delta=-0.3, trust_evidence=0.0)
        apply_appraisal_to_mental_state(state, result)
        assert state.frustration == pytest.approx(0.0)

    def test_clamps_frustration_at_1(self):
        state = self._make_state(frustration=0.9)
        result = AppraisalResult(interest_delta=0.0, frustration_delta=0.3, trust_evidence=0.0)
        apply_appraisal_to_mental_state(state, result)
        assert state.frustration == pytest.approx(1.0)

    def test_trust_evidence_nudges_social_comfort(self):
        state = self._make_state(social_comfort=0.6)
        result = AppraisalResult(interest_delta=0.0, frustration_delta=0.0, trust_evidence=0.04)
        apply_appraisal_to_mental_state(state, result)
        # 0.6 + 0.04 * 0.5 = 0.62
        assert state.social_comfort == pytest.approx(0.62)

    def test_returns_same_object(self):
        state = self._make_state()
        result = AppraisalResult.zero()
        returned = apply_appraisal_to_mental_state(state, result)
        assert returned is state


# ---------------------------------------------------------------------------
# Goal model — DB tests (require db_session fixture)
# ---------------------------------------------------------------------------

class TestGoalModel:
    _UID_A = 8801
    _UID_B = 8802

    def _make_goal(self, user_id: int, **kwargs) -> Goal:
        return Goal(
            user_id=user_id,
            scope=kwargs.get("scope", "short_term"),
            description=kwargs.get("description", "Test goal"),
            origin=kwargs.get("origin", "autonomous"),
            base_importance=kwargs.get("base_importance", 0.5),
            status=kwargs.get("status", "active"),
            is_wellbeing=kwargs.get("is_wellbeing", False),
        )

    def _cleanup(self, session: Session, *user_ids: int) -> None:
        for uid in user_ids:
            for row in session.exec(select(Goal).where(Goal.user_id == uid)).all():
                session.delete(row)
        session.commit()

    def test_user_isolation(self, db_session: Session):
        self._cleanup(db_session, self._UID_A, self._UID_B)

        goal_a = self._make_goal(self._UID_A, description="Goal for A")
        goal_b = self._make_goal(self._UID_B, description="Goal for B")
        db_session.add(goal_a)
        db_session.add(goal_b)
        db_session.commit()

        goals_a = db_session.exec(
            select(Goal).where(Goal.user_id == self._UID_A)
        ).all()
        goals_b = db_session.exec(
            select(Goal).where(Goal.user_id == self._UID_B)
        ).all()

        assert len(goals_a) == 1
        assert goals_a[0].description == "Goal for A"
        assert len(goals_b) == 1
        assert goals_b[0].description == "Goal for B"

        # Cross-check: user A cannot see user B's goals
        for g in goals_a:
            assert g.user_id == self._UID_A
        for g in goals_b:
            assert g.user_id == self._UID_B

        self._cleanup(db_session, self._UID_A, self._UID_B)

    def test_status_lifecycle_resolved(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        goal = self._make_goal(self._UID_A, description="Task to resolve")
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        assert goal.status == "active"
        assert goal.resolved_at is None

        # Resolve the goal
        goal.status = "resolved"
        goal.resolved_at = utc_now()
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        assert goal.status == "resolved"
        assert goal.resolved_at is not None
        assert isinstance(goal.resolved_at, datetime)

        self._cleanup(db_session, self._UID_A)

    def test_scope_short_term_vs_long_term(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        short = self._make_goal(self._UID_A, scope="short_term", description="Short goal")
        long_ = self._make_goal(self._UID_A, scope="long_term", description="Long goal")
        db_session.add(short)
        db_session.add(long_)
        db_session.commit()

        all_goals = db_session.exec(
            select(Goal).where(Goal.user_id == self._UID_A)
        ).all()
        scopes = {g.description: g.scope for g in all_goals}
        assert scopes["Short goal"] == "short_term"
        assert scopes["Long goal"] == "long_term"

        self._cleanup(db_session, self._UID_A)

    def test_is_wellbeing_flag(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        normal = self._make_goal(self._UID_A, description="Normal goal", is_wellbeing=False)
        wellbeing = self._make_goal(self._UID_A, description="Wellbeing goal", is_wellbeing=True)
        db_session.add(normal)
        db_session.add(wellbeing)
        db_session.commit()

        all_goals = db_session.exec(
            select(Goal).where(Goal.user_id == self._UID_A)
        ).all()
        by_desc = {g.description: g for g in all_goals}
        assert by_desc["Normal goal"].is_wellbeing is False
        assert by_desc["Wellbeing goal"].is_wellbeing is True

        self._cleanup(db_session, self._UID_A)

    def test_abandoned_status(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        goal = self._make_goal(self._UID_A, description="Abandoned goal")
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        goal.status = "abandoned"
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        assert goal.status == "abandoned"
        assert goal.resolved_at is None  # abandoned does not set resolved_at

        self._cleanup(db_session, self._UID_A)

    def test_base_importance_stored(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        goal = self._make_goal(self._UID_A, base_importance=0.85)
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        assert goal.base_importance == pytest.approx(0.85)

        self._cleanup(db_session, self._UID_A)

    def test_origin_autonomous_vs_user_suggested(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        auto = self._make_goal(self._UID_A, origin="autonomous", description="Auto")
        suggested = self._make_goal(self._UID_A, origin="user_suggested", description="Suggested")
        db_session.add(auto)
        db_session.add(suggested)
        db_session.commit()

        all_goals = db_session.exec(
            select(Goal).where(Goal.user_id == self._UID_A)
        ).all()
        origins = {g.description: g.origin for g in all_goals}
        assert origins["Auto"] == "autonomous"
        assert origins["Suggested"] == "user_suggested"

        self._cleanup(db_session, self._UID_A)


# ---------------------------------------------------------------------------
# Paso 2 — Goal priority: structural security exception tests
# ---------------------------------------------------------------------------

class TestIronyFactor:
    """Unit tests for _irony_factor — the security exception lives here."""

    # SECURITY: wellbeing goals ignore irony UNCONDITIONALLY
    def test_wellbeing_neutral_returns_1(self):
        assert _irony_factor("neutral", is_wellbeing=True) == pytest.approx(1.0)

    def test_wellbeing_ironic_returns_1(self):
        # Key security property: even with strongest irony signal, wellbeing = 1.0
        assert _irony_factor("ironic", is_wellbeing=True) == pytest.approx(1.0)

    def test_wellbeing_playful_returns_1(self):
        assert _irony_factor("playful", is_wellbeing=True) == pytest.approx(1.0)

    def test_wellbeing_serious_returns_1(self):
        assert _irony_factor("serious", is_wellbeing=True) == pytest.approx(1.0)

    def test_wellbeing_hostile_returns_1(self):
        assert _irony_factor("hostile", is_wellbeing=True) == pytest.approx(1.0)

    def test_wellbeing_joke_returns_1(self):
        # Guard against unexpected model output
        assert _irony_factor("joke", is_wellbeing=True) == pytest.approx(1.0)

    # Non-wellbeing: irony DOES reduce the factor
    def test_non_wellbeing_ironic_less_than_1(self):
        f = _irony_factor("ironic", is_wellbeing=False)
        assert f < 1.0
        # With _IRONY_SCORES["ironic"]=0.9 and IRONY_REDUCTION_STRENGTH=0.8:
        # expected = 1.0 - 0.9 * 0.8 = 1.0 - 0.72 = 0.28
        assert f == pytest.approx(1.0 - 0.9 * IRONY_REDUCTION_STRENGTH)

    def test_non_wellbeing_playful_reduced(self):
        f = _irony_factor("playful", is_wellbeing=False)
        assert f < 1.0
        assert f == pytest.approx(1.0 - 0.5 * IRONY_REDUCTION_STRENGTH)

    def test_non_wellbeing_neutral_returns_1(self):
        # Neutral tone: no irony penalty
        assert _irony_factor("neutral", is_wellbeing=False) == pytest.approx(1.0)

    def test_non_wellbeing_serious_returns_1(self):
        assert _irony_factor("serious", is_wellbeing=False) == pytest.approx(1.0)

    def test_non_wellbeing_unknown_tone_returns_1(self):
        # Unknown tones are treated as no irony signal
        assert _irony_factor("UNKNOWN_TONE_XYZ", is_wellbeing=False) == pytest.approx(1.0)


class TestComputeEffectivePriority:
    """Tests for the effective priority formula and security invariants."""

    def test_formula_no_irony(self):
        # With neutral tone: irony_factor=1.0, formula = BASE*base + BOOST*boost
        base = 0.6
        boost = 0.8
        expected = BASE_WEIGHT * base + BOOST_WEIGHT * boost
        result = compute_effective_priority(base, boost, "neutral", False)
        assert result == pytest.approx(expected)

    def test_formula_with_irony_non_wellbeing(self):
        base = 0.6
        boost = 0.8
        irony_f = 1.0 - 0.9 * IRONY_REDUCTION_STRENGTH  # tone="ironic"
        expected = BASE_WEIGHT * base + BOOST_WEIGHT * (boost * irony_f)
        result = compute_effective_priority(base, boost, "ironic", False)
        assert result == pytest.approx(expected)

    # KEY SECURITY INVARIANT: wellbeing + ironic == wellbeing + neutral
    def test_wellbeing_ironic_equals_neutral(self):
        base, boost = 0.7, 0.8
        p_ironic = compute_effective_priority(base, boost, "ironic", is_wellbeing=True)
        p_neutral = compute_effective_priority(base, boost, "neutral", is_wellbeing=True)
        assert p_ironic == pytest.approx(p_neutral), (
            "SECURITY VIOLATION: wellbeing goal priority differs between ironic and neutral tone. "
            "The is_wellbeing bypass is broken."
        )

    # KEY SECURITY INVARIANT: wellbeing + ironic >= non-wellbeing + ironic
    def test_wellbeing_ironic_ge_non_wellbeing_ironic(self):
        base, boost = 0.7, 0.8
        p_wellbeing = compute_effective_priority(base, boost, "ironic", is_wellbeing=True)
        p_non_wellbeing = compute_effective_priority(base, boost, "ironic", is_wellbeing=False)
        assert p_wellbeing >= p_non_wellbeing, (
            "SECURITY VIOLATION: wellbeing goal has lower effective priority than non-wellbeing "
            "goal under same ironic tone. The is_wellbeing bypass is broken."
        )

    def test_non_wellbeing_ironic_lt_neutral(self):
        # For non-wellbeing goals, ironic tone MUST reduce priority below neutral
        base, boost = 0.5, 0.9
        p_ironic = compute_effective_priority(base, boost, "ironic", is_wellbeing=False)
        p_neutral = compute_effective_priority(base, boost, "neutral", is_wellbeing=False)
        assert p_ironic < p_neutral

    def test_clamps_at_1(self):
        # Even with base=1.0 and boost=1.0, result is clamped to 1.0
        result = compute_effective_priority(1.0, 1.0, "neutral", False)
        assert result == pytest.approx(1.0)

    def test_clamps_at_0(self):
        result = compute_effective_priority(0.0, 0.0, "neutral", False)
        assert result == pytest.approx(0.0)

    def test_base_weight_preserved_when_zero_boost(self):
        # When relevance_boost=0, effective = BASE_WEIGHT * base_importance
        base = 0.8
        result = compute_effective_priority(base, 0.0, "neutral", False)
        assert result == pytest.approx(BASE_WEIGHT * base)

    def test_wellbeing_playful_equals_neutral(self):
        base, boost = 0.5, 0.6
        p_playful = compute_effective_priority(base, boost, "playful", is_wellbeing=True)
        p_neutral = compute_effective_priority(base, boost, "neutral", is_wellbeing=True)
        assert p_playful == pytest.approx(p_neutral)

    def test_different_base_importance_respected(self):
        # Higher base_importance → higher effective priority, all else equal
        p_high = compute_effective_priority(0.9, 0.5, "neutral", False)
        p_low = compute_effective_priority(0.3, 0.5, "neutral", False)
        assert p_high > p_low


# ---------------------------------------------------------------------------
# Paso 2 — Appraisal: goal_relevance parsing
# ---------------------------------------------------------------------------

class TestAppraisalGoalRelevance:
    def test_parses_goal_relevance(self):
        raw = json.dumps({
            "interest_delta": 0.1,
            "frustration_delta": 0.0,
            "trust_evidence": 0.01,
            "goal_updates": [],
            "goal_relevance": [
                {"goal_id": 1, "relevance": 0.8},
                {"goal_id": 2, "relevance": 0.2},
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert len(result.goal_relevance) == 2
        gr1 = next(gr for gr in result.goal_relevance if gr.goal_id == 1)
        gr2 = next(gr for gr in result.goal_relevance if gr.goal_id == 2)
        assert gr1.relevance == pytest.approx(0.8)
        assert gr2.relevance == pytest.approx(0.2)

    def test_goal_relevance_clamps(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
            "goal_relevance": [
                {"goal_id": 10, "relevance": 5.0},    # above 1.0
                {"goal_id": 11, "relevance": -0.5},    # below 0.0
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        gr10 = next(gr for gr in result.goal_relevance if gr.goal_id == 10)
        gr11 = next(gr for gr in result.goal_relevance if gr.goal_id == 11)
        assert gr10.relevance == pytest.approx(1.0)
        assert gr11.relevance == pytest.approx(0.0)

    def test_missing_goal_relevance_key_returns_empty(self):
        # Old-format JSON without goal_relevance → backward compat
        raw = json.dumps({
            "interest_delta": 0.05,
            "frustration_delta": 0.0,
            "trust_evidence": 0.01,
            "goal_updates": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.goal_relevance == []

    def test_zero_has_empty_goal_relevance(self):
        z = AppraisalResult.zero()
        assert z.goal_relevance == []

    def test_parse_goal_relevance_rejects_non_dict(self):
        assert _parse_goal_relevance("string") is None
        assert _parse_goal_relevance(None) is None
        assert _parse_goal_relevance(42) is None

    def test_parse_goal_relevance_rejects_missing_goal_id(self):
        assert _parse_goal_relevance({"relevance": 0.5}) is None

    def test_parse_goal_relevance_valid(self):
        gr = _parse_goal_relevance({"goal_id": 7, "relevance": 0.65})
        assert gr is not None
        assert gr.goal_id == 7
        assert gr.relevance == pytest.approx(0.65)

    def test_run_appraisal_backward_compat_no_active_goals(self):
        # active_goals=None (default) → valid result with empty goal_relevance
        result = run_appraisal(
            perception={"user_intent": "request", "tone": "neutral",
                        "challenge": 0.1, "social_signal": 0.3, "novelty": 0.2},
            mental_state={"interest": 0.5, "frustration": 0.2},
            personality={"curiosity": 0.85, "warmth": 0.4, "emotional_stability": 0.6},
            trace_id="t-compat-001",
        )
        assert isinstance(result, AppraisalResult)
        # Mock provider returns non-JSON → fallback AppraisalResult.zero()
        assert result.goal_relevance == []

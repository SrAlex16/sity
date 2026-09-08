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

Paso 3 properties — GoalService, build_active_goals_block, run_cognition_turn:
34. get_active_goals returns only active goals (not resolved/abandoned).
35. get_active_goals scope_filter restricts by scope.
36. get_active_goals isolates by user_id.
37. create_goal_from_intent creates a Goal row with correct fields.
38. apply_goal_intents creates multiple goals from a list of intents.
39. build_active_goals_block returns empty string for empty goals list.
40. build_active_goals_block excludes goals below priority threshold 0.5.
41. build_active_goals_block includes qualifying goals in formatted block.
42. build_active_goals_block caps output at 3 goals.
43. build_active_goals_block marks wellbeing goals with [bienestar].
44. build_active_goals_block shows correct scope label for long_term goals.
45. build_active_goals_block sorts by priority descending.
46. run_cognition_turn returns CognitionTurnResult with correct structure.
47. run_cognition_turn persists MentalState changes to DB.
48. run_cognition_turn creates Goal rows when appraisal returns goal intents.

Initiative evaluator — goal injection:
49. _build_user_message includes long-term goals when present.
50. _build_user_message works without goals (backward compat).
51. _get_active_long_term_goals returns empty list for non-user: session.

Paso 4 Part 1 — state machine (GoalStateChange):
52. _parse_goal_state_change parses valid "resolved".
53. _parse_goal_state_change parses valid "abandoned".
54. _parse_goal_state_change rejects non-dict.
55. _parse_goal_state_change rejects invalid new_status.
56. _parse_goal_state_change rejects missing goal_id.
57. _parse_appraisal includes goal_state_changes when present.
58. AppraisalResult.zero() has empty goal_state_changes.
59. apply_goal_state_changes: active → resolved sets status and resolved_at.
60. apply_goal_state_changes: active → abandoned sets status, resolved_at stays None.
61. apply_goal_state_changes: ignores non-active goals.
62. apply_goal_state_changes: ignores goals belonging to another user.
63. run_cognition_turn applies goal_state_changes from Appraisal to DB.

Paso 4 Part 2 — milestone system (MilestoneIntent, GoalMilestone):
64. _parse_milestone_intent: add_milestone with valid fields.
65. _parse_milestone_intent: complete with valid milestone_id.
66. _parse_milestone_intent: rejects non-dict.
67. _parse_milestone_intent: add_milestone rejects missing goal_id.
68. _parse_milestone_intent: add_milestone rejects empty description.
69. _parse_milestone_intent: complete rejects missing milestone_id.
70. _parse_milestone_intent: rejects unknown action.
71. _parse_appraisal includes milestone_updates when present.
72. _parse_appraisal filters invalid milestone_updates.
73. _parse_appraisal backward compat: missing field returns empty list.
74. AppraisalResult.zero() has empty milestone_updates.
75. _parse_goal_update parses initial_milestones list.
76. _parse_goal_update: initial_milestones defaults to [] when absent.
77. get_milestones_for_goal returns milestones ordered by order_index.
78. create_goal_from_intent creates initial milestones when provided.
79. create_goal_from_intent creates goal without milestones (simple goal).
80. apply_milestone_updates add_milestone appends new GoalMilestone.
81. apply_milestone_updates add_milestone order_index continues from existing.
82. apply_milestone_updates add_milestone ignores goals of other users.
83. apply_milestone_updates complete sets status and completed_at.
84. apply_milestone_updates complete ignores milestones of other users.
85. GoalMilestone user isolation: milestone cannot be completed via other user.
86. run_cognition_turn applies milestone_updates from Appraisal to DB.

Paso 4 Part 4 — short_term auto-expiry:
87. resolve_expired_short_term_goals: active short_term goal older than threshold → expired.
88. resolve_expired_short_term_goals: long_term goal older than threshold → NOT expired.
89. resolve_expired_short_term_goals: short_term goal within threshold → NOT expired.
90. resolve_expired_short_term_goals: already-resolved goal → NOT changed.
91. resolve_expired_short_term_goals: user isolation — other user's goals not affected.
92. resolve_expired_short_term_goals: returns count of expired goals.
93. run_cognition_turn expires stale short_term goals before building context.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.cognition.appraisal import (
    AppraisalResult,
    GoalRelevance,
    GoalStateChange,
    GoalUpdateIntent,
    MilestoneIntent,
    _parse_appraisal,
    _parse_goal_relevance,
    _parse_goal_state_change,
    _parse_goal_update,
    _parse_milestone_intent,
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
from app.cognition.goal_service import (
    apply_goal_intents,
    apply_goal_state_changes,
    apply_milestone_updates,
    build_active_goals_block,
    create_goal_from_intent,
    get_active_goals,
    get_milestones_for_goal,
    resolve_expired_short_term_goals,
)
from app.memory.models import Goal, GoalMilestone, MentalState, utc_now
from app.cognition.perception import (
    PerceptionResult,
    _parse_perception,
    run_perception,
)
from app.cognition.turn_cognition import CognitionTurnResult, run_cognition_turn
from app.initiative.evaluator import _build_user_message, _get_active_long_term_goals
from app.settings.settings_service import CANONICAL_PERSONALITY, SettingsService


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


# ---------------------------------------------------------------------------
# Paso 3 — GoalService DB tests
# ---------------------------------------------------------------------------

class TestGoalService:
    _UID_A = 8901
    _UID_B = 8902

    def _cleanup(self, session: Session, *user_ids: int) -> None:
        for uid in user_ids:
            for row in session.exec(select(Goal).where(Goal.user_id == uid)).all():
                session.delete(row)
        session.commit()

    def _make_intent(self, **kwargs) -> GoalUpdateIntent:
        return GoalUpdateIntent(
            action="create",
            description=kwargs.get("description", "Test intent"),
            scope=kwargs.get("scope", "short_term"),
            base_importance=kwargs.get("base_importance", 0.5),
            is_wellbeing=kwargs.get("is_wellbeing", False),
        )

    def test_get_active_goals_returns_only_active(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        active = Goal(user_id=self._UID_A, scope="short_term", description="Active",
                      origin="autonomous", status="active")
        resolved = Goal(user_id=self._UID_A, scope="short_term", description="Resolved",
                        origin="autonomous", status="resolved")
        db_session.add(active)
        db_session.add(resolved)
        db_session.commit()

        results = get_active_goals(db_session, self._UID_A)
        assert len(results) == 1
        assert results[0].description == "Active"

        self._cleanup(db_session, self._UID_A)

    def test_get_active_goals_scope_filter(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        short = Goal(user_id=self._UID_A, scope="short_term", description="Short",
                     origin="autonomous", status="active")
        long_ = Goal(user_id=self._UID_A, scope="long_term", description="Long",
                     origin="autonomous", status="active")
        db_session.add(short)
        db_session.add(long_)
        db_session.commit()

        long_only = get_active_goals(db_session, self._UID_A, scope_filter="long_term")
        assert len(long_only) == 1
        assert long_only[0].scope == "long_term"

        short_only = get_active_goals(db_session, self._UID_A, scope_filter="short_term")
        assert len(short_only) == 1
        assert short_only[0].scope == "short_term"

        self._cleanup(db_session, self._UID_A)

    def test_get_active_goals_user_isolation(self, db_session: Session):
        self._cleanup(db_session, self._UID_A, self._UID_B)

        db_session.add(Goal(user_id=self._UID_A, scope="short_term", description="A goal",
                            origin="autonomous", status="active"))
        db_session.add(Goal(user_id=self._UID_B, scope="short_term", description="B goal",
                            origin="autonomous", status="active"))
        db_session.commit()

        goals_a = get_active_goals(db_session, self._UID_A)
        goals_b = get_active_goals(db_session, self._UID_B)

        assert all(g.user_id == self._UID_A for g in goals_a)
        assert all(g.user_id == self._UID_B for g in goals_b)

        self._cleanup(db_session, self._UID_A, self._UID_B)

    def test_create_goal_from_intent_creates_row(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        intent = self._make_intent(
            description="Aprender inglés",
            scope="long_term",
            base_importance=0.8,
            is_wellbeing=False,
        )
        goal = create_goal_from_intent(db_session, self._UID_A, intent)

        assert goal.id is not None
        assert goal.user_id == self._UID_A
        assert goal.description == "Aprender inglés"
        assert goal.scope == "long_term"
        assert goal.origin == "autonomous"
        assert goal.base_importance == pytest.approx(0.8)
        assert goal.status == "active"
        assert goal.is_wellbeing is False

        self._cleanup(db_session, self._UID_A)

    def test_apply_goal_intents_creates_multiple(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        intents = [
            self._make_intent(description="Meta 1", scope="short_term"),
            self._make_intent(description="Meta 2", scope="long_term", is_wellbeing=True),
        ]
        apply_goal_intents(db_session, self._UID_A, intents)

        goals = get_active_goals(db_session, self._UID_A)
        assert len(goals) == 2
        descriptions = {g.description for g in goals}
        assert "Meta 1" in descriptions
        assert "Meta 2" in descriptions

        wellbeing_goals = [g for g in goals if g.is_wellbeing]
        assert len(wellbeing_goals) == 1
        assert wellbeing_goals[0].description == "Meta 2"

        self._cleanup(db_session, self._UID_A)


# ---------------------------------------------------------------------------
# Paso 3 — build_active_goals_block (pure, no DB)
# ---------------------------------------------------------------------------

def _make_goal_obj(
    goal_id: int,
    base_importance: float,
    scope: str = "short_term",
    is_wellbeing: bool = False,
    description: str = "Test goal",
) -> Goal:
    """Build an unsaved Goal object with a known id for unit tests."""
    g = Goal(
        user_id=99,
        scope=scope,
        description=description,
        origin="autonomous",
        base_importance=base_importance,
        status="active",
        is_wellbeing=is_wellbeing,
    )
    g.id = goal_id
    return g


class TestBuildActiveGoalsBlock:
    def test_empty_list_returns_empty_string(self):
        result = build_active_goals_block([], AppraisalResult.zero(), "neutral")
        assert result == ""

    def test_no_goals_meet_threshold(self):
        # base_importance=0.5, no relevance_boost → priority = 0.6*0.5 + 0.4*0 = 0.30 < 0.5
        goal = _make_goal_obj(1, base_importance=0.5)
        result = build_active_goals_block([goal], AppraisalResult.zero(), "neutral")
        assert result == ""

    def test_qualifying_goal_included(self):
        # base_importance=0.9 → priority = 0.6*0.9 + 0.4*0 = 0.54 >= 0.5
        goal = _make_goal_obj(1, base_importance=0.9, description="Aprender guitarra")
        result = build_active_goals_block([goal], AppraisalResult.zero(), "neutral")
        assert "Aprender guitarra" in result
        assert "METAS ACTIVAS" in result

    def test_max_3_goals_capped(self):
        # Create 5 goals all with high base_importance
        goals = [
            _make_goal_obj(i, base_importance=0.9, description=f"Meta {i}")
            for i in range(1, 6)
        ]
        result = build_active_goals_block(goals, AppraisalResult.zero(), "neutral")
        # Count the bullet lines (each starts with "- [")
        bullet_count = result.count("- [")
        assert bullet_count == 3

    def test_wellbeing_goal_marked(self):
        goal = _make_goal_obj(1, base_importance=0.9, is_wellbeing=True,
                              description="Gestionar ansiedad")
        result = build_active_goals_block([goal], AppraisalResult.zero(), "neutral")
        assert "[bienestar]" in result

    def test_long_term_scope_label(self):
        goal = _make_goal_obj(1, base_importance=0.9, scope="long_term",
                              description="Objetivo largo")
        result = build_active_goals_block([goal], AppraisalResult.zero(), "neutral")
        assert "largo plazo" in result

    def test_short_term_scope_label(self):
        goal = _make_goal_obj(1, base_importance=0.9, scope="short_term",
                              description="Objetivo corto")
        result = build_active_goals_block([goal], AppraisalResult.zero(), "neutral")
        assert "corto plazo" in result

    def test_sorted_by_priority_descending(self):
        low = _make_goal_obj(1, base_importance=0.6, description="Low priority")
        high = _make_goal_obj(2, base_importance=0.95, description="High priority")
        result = build_active_goals_block([low, high], AppraisalResult.zero(), "neutral")
        lines = result.splitlines()
        # First bullet should be the high-priority goal
        first_bullet = next(l for l in lines if l.startswith("- ["))
        assert "High priority" in first_bullet

    def test_relevance_boost_from_appraisal_applied(self):
        # Goal with low base_importance but high relevance_boost should qualify
        # base_importance=0.5 alone → priority 0.30 (excluded)
        # with relevance_boost=1.0 → priority = 0.6*0.5 + 0.4*1.0 = 0.70 (included)
        goal = _make_goal_obj(42, base_importance=0.5, description="Boosted goal")
        appraisal = AppraisalResult(
            interest_delta=0.0,
            frustration_delta=0.0,
            trust_evidence=0.0,
            goal_relevance=[GoalRelevance(goal_id=42, relevance=1.0)],
        )
        result = build_active_goals_block([goal], appraisal, "neutral")
        assert "Boosted goal" in result

    def test_goals_without_id_skipped(self):
        # Goal with id=None should not cause an error or appear in output
        goal = Goal(
            user_id=99, scope="short_term", description="No id goal",
            origin="autonomous", base_importance=0.9, status="active",
        )
        # id is None by default (not persisted)
        result = build_active_goals_block([goal], AppraisalResult.zero(), "neutral")
        assert result == ""


# ---------------------------------------------------------------------------
# Paso 3 — run_cognition_turn (DB + mock provider)
# ---------------------------------------------------------------------------

class TestRunCognitionTurn:
    _UID = 8950

    def _cleanup(self, session: Session) -> None:
        for row in session.exec(select(Goal).where(Goal.user_id == self._UID)).all():
            session.delete(row)
        for row in session.exec(
            select(MentalState).where(MentalState.user_id == self._UID)
        ).all():
            session.delete(row)
        session.commit()

    def test_returns_cognition_turn_result(self, db_session: Session):
        self._cleanup(db_session)
        svc = SettingsService(db_session)

        result = run_cognition_turn(
            session=db_session,
            user_id=self._UID,
            user_message="Hola, ¿cómo estás?",
            settings_service=svc,
            personality=CANONICAL_PERSONALITY,
            trace_id="t-ctr-001",
        )

        assert isinstance(result, CognitionTurnResult)
        assert isinstance(result.perception, PerceptionResult)
        assert isinstance(result.appraisal, AppraisalResult)
        assert isinstance(result.active_goals, list)

        self._cleanup(db_session)

    def test_mental_state_row_created_in_db(self, db_session: Session):
        self._cleanup(db_session)
        svc = SettingsService(db_session)

        run_cognition_turn(
            session=db_session,
            user_id=self._UID,
            user_message="Hola",
            settings_service=svc,
            personality=CANONICAL_PERSONALITY,
            trace_id="t-ctr-002",
        )

        row = db_session.exec(
            select(MentalState).where(MentalState.user_id == self._UID)
        ).first()
        assert row is not None

        self._cleanup(db_session)

    def test_creates_goal_when_appraisal_returns_intent(self, db_session: Session):
        self._cleanup(db_session)
        svc = SettingsService(db_session)

        fake_appraisal = AppraisalResult(
            interest_delta=0.1,
            frustration_delta=0.0,
            trust_evidence=0.02,
            goal_updates=[
                GoalUpdateIntent(
                    action="create",
                    description="Practicar meditación",
                    scope="long_term",
                    base_importance=0.7,
                    is_wellbeing=True,
                )
            ],
            goal_relevance=[],
        )

        with patch("app.cognition.turn_cognition.run_appraisal", return_value=fake_appraisal):
            run_cognition_turn(
                session=db_session,
                user_id=self._UID,
                user_message="Quiero empezar a meditar",
                settings_service=svc,
                personality=CANONICAL_PERSONALITY,
                trace_id="t-ctr-003",
            )

        goals = get_active_goals(db_session, self._UID)
        assert len(goals) == 1
        assert goals[0].description == "Practicar meditación"
        assert goals[0].is_wellbeing is True
        assert goals[0].scope == "long_term"

        self._cleanup(db_session)

    def test_no_goals_created_when_goal_updates_empty(self, db_session: Session):
        self._cleanup(db_session)
        svc = SettingsService(db_session)

        run_cognition_turn(
            session=db_session,
            user_id=self._UID,
            user_message="¿Qué hora es?",
            settings_service=svc,
            personality=CANONICAL_PERSONALITY,
            trace_id="t-ctr-004",
        )
        # Mock provider returns non-JSON → appraisal zero → no goal_updates
        goals = get_active_goals(db_session, self._UID)
        assert goals == []

        self._cleanup(db_session)


# ---------------------------------------------------------------------------
# Paso 3 — Initiative evaluator goal injection
# ---------------------------------------------------------------------------

class TestEvaluatorGoalInjection:
    """Tests for _build_user_message and _get_active_long_term_goals in evaluator.py."""

    _UID = 8960

    def _cleanup(self, session: Session) -> None:
        for row in session.exec(select(Goal).where(Goal.user_id == self._UID)).all():
            session.delete(row)
        session.commit()

    def _make_candidate(self) -> object:
        from app.initiative.detector import TriggerCandidate
        return TriggerCandidate(
            session_id=f"user:{self._UID}",
            trigger_type="long_inactivity",
            context={"days_since_last_message": 5, "last_message_role": "user",
                     "last_message_text": "hasta mañana"},
            open_loop_id=None,
        )

    def test_build_user_message_includes_goals(self):
        goal1 = Goal(id=1, user_id=self._UID, scope="long_term", description="Aprender piano",
                     origin="autonomous", status="active", base_importance=0.8)
        goal2 = Goal(id=2, user_id=self._UID, scope="long_term", description="Correr 5km",
                     origin="autonomous", status="active", base_importance=0.7)
        goal1.id = 1
        goal2.id = 2

        candidate = self._make_candidate()
        msg = _build_user_message(candidate, None, [goal1, goal2])

        assert "Aprender piano" in msg
        assert "Correr 5km" in msg
        assert "Metas a largo plazo" in msg

    def test_build_user_message_no_goals_backward_compat(self):
        candidate = self._make_candidate()
        msg = _build_user_message(candidate, None, [])
        assert "Metas" not in msg
        assert "Días sin actividad" in msg

    def test_build_user_message_none_goals_backward_compat(self):
        candidate = self._make_candidate()
        msg = _build_user_message(candidate, None, None)
        assert "Metas" not in msg

    def test_get_active_long_term_goals_returns_empty_for_non_user_session(
        self, db_session: Session
    ):
        result = _get_active_long_term_goals("default", db_session)
        assert result == []

    def test_get_active_long_term_goals_returns_long_term_only(self, db_session: Session):
        self._cleanup(db_session)

        db_session.add(Goal(user_id=self._UID, scope="long_term", description="LT goal",
                            origin="autonomous", status="active"))
        db_session.add(Goal(user_id=self._UID, scope="short_term", description="ST goal",
                            origin="autonomous", status="active"))
        db_session.commit()

        results = _get_active_long_term_goals(f"user:{self._UID}", db_session)
        assert len(results) == 1
        assert results[0].scope == "long_term"

        self._cleanup(db_session)


# ---------------------------------------------------------------------------
# Paso 4 Part 1 — GoalStateChange: parse unit tests + apply_goal_state_changes
# ---------------------------------------------------------------------------

class TestParseGoalStateChange:
    def test_parses_resolved(self):
        gsc = _parse_goal_state_change({"goal_id": 5, "new_status": "resolved"})
        assert gsc is not None
        assert gsc.goal_id == 5
        assert gsc.new_status == "resolved"

    def test_parses_abandoned(self):
        gsc = _parse_goal_state_change({"goal_id": 12, "new_status": "abandoned"})
        assert gsc is not None
        assert gsc.goal_id == 12
        assert gsc.new_status == "abandoned"

    def test_rejects_non_dict(self):
        assert _parse_goal_state_change("resolved") is None
        assert _parse_goal_state_change(None) is None
        assert _parse_goal_state_change(42) is None

    def test_rejects_invalid_status(self):
        assert _parse_goal_state_change({"goal_id": 1, "new_status": "active"}) is None
        assert _parse_goal_state_change({"goal_id": 1, "new_status": "expired"}) is None
        assert _parse_goal_state_change({"goal_id": 1, "new_status": ""}) is None

    def test_rejects_missing_goal_id(self):
        assert _parse_goal_state_change({"new_status": "resolved"}) is None

    def test_parse_appraisal_includes_state_changes(self):
        raw = json.dumps({
            "interest_delta": 0.1,
            "frustration_delta": 0.0,
            "trust_evidence": 0.01,
            "goal_updates": [],
            "goal_relevance": [],
            "goal_state_changes": [
                {"goal_id": 7, "new_status": "resolved"},
                {"goal_id": 9, "new_status": "abandoned"},
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert len(result.goal_state_changes) == 2
        assert result.goal_state_changes[0].goal_id == 7
        assert result.goal_state_changes[0].new_status == "resolved"
        assert result.goal_state_changes[1].goal_id == 9
        assert result.goal_state_changes[1].new_status == "abandoned"

    def test_parse_appraisal_filters_invalid_state_changes(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
            "goal_relevance": [],
            "goal_state_changes": [
                {"goal_id": 1, "new_status": "active"},   # invalid — filtered
                {"goal_id": 2, "new_status": "resolved"},  # valid
                "not-a-dict",                              # invalid — filtered
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert len(result.goal_state_changes) == 1
        assert result.goal_state_changes[0].goal_id == 2

    def test_parse_appraisal_missing_field_returns_empty(self):
        # Old Appraisal response without goal_state_changes — backward compat
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
            "goal_relevance": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.goal_state_changes == []

    def test_zero_has_empty_goal_state_changes(self):
        z = AppraisalResult.zero()
        assert z.goal_state_changes == []


class TestApplyGoalStateChanges:
    _UID_A = 8970
    _UID_B = 8971

    def _cleanup(self, session: Session, *user_ids: int) -> None:
        for uid in user_ids:
            for row in session.exec(select(Goal).where(Goal.user_id == uid)).all():
                session.delete(row)
        session.commit()

    def _make_active_goal(self, session: Session, user_id: int, description: str = "Goal") -> Goal:
        g = Goal(user_id=user_id, scope="short_term", description=description,
                 origin="autonomous", status="active")
        session.add(g)
        session.commit()
        session.refresh(g)
        return g

    def test_resolved_sets_status_and_resolved_at(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_active_goal(db_session, self._UID_A, "Finish the book")

        changes = [GoalStateChange(goal_id=goal.id, new_status="resolved")]
        apply_goal_state_changes(db_session, self._UID_A, changes)

        db_session.refresh(goal)
        assert goal.status == "resolved"
        assert goal.resolved_at is not None

        self._cleanup(db_session, self._UID_A)

    def test_abandoned_sets_status_resolved_at_stays_none(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_active_goal(db_session, self._UID_A, "Abandoned goal")

        changes = [GoalStateChange(goal_id=goal.id, new_status="abandoned")]
        apply_goal_state_changes(db_session, self._UID_A, changes)

        db_session.refresh(goal)
        assert goal.status == "abandoned"
        assert goal.resolved_at is None

        self._cleanup(db_session, self._UID_A)

    def test_ignores_already_resolved_goal(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = Goal(user_id=self._UID_A, scope="short_term", description="Already done",
                    origin="autonomous", status="resolved", resolved_at=utc_now())
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        original_resolved_at = goal.resolved_at
        changes = [GoalStateChange(goal_id=goal.id, new_status="abandoned")]
        apply_goal_state_changes(db_session, self._UID_A, changes)

        db_session.refresh(goal)
        # Status must not change — already resolved
        assert goal.status == "resolved"
        assert goal.resolved_at == original_resolved_at

        self._cleanup(db_session, self._UID_A)

    def test_ignores_goal_belonging_to_other_user(self, db_session: Session):
        self._cleanup(db_session, self._UID_A, self._UID_B)
        goal_b = self._make_active_goal(db_session, self._UID_B, "User B goal")

        # Try to resolve UID_B's goal as UID_A — must be ignored
        changes = [GoalStateChange(goal_id=goal_b.id, new_status="resolved")]
        apply_goal_state_changes(db_session, self._UID_A, changes)

        db_session.refresh(goal_b)
        assert goal_b.status == "active"

        self._cleanup(db_session, self._UID_A, self._UID_B)

    def test_run_cognition_turn_applies_state_changes(self, db_session: Session):
        _UID = 8972
        # Cleanup
        for row in db_session.exec(select(Goal).where(Goal.user_id == _UID)).all():
            db_session.delete(row)
        from app.memory.models import MentalState as _MS
        for row in db_session.exec(select(_MS).where(_MS.user_id == _UID)).all():
            db_session.delete(row)
        db_session.commit()

        # Create an active goal
        goal = Goal(user_id=_UID, scope="short_term", description="Learn Python",
                    origin="autonomous", status="active")
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        svc = SettingsService(db_session)
        fake_appraisal = AppraisalResult(
            interest_delta=0.0,
            frustration_delta=0.0,
            trust_evidence=0.0,
            goal_state_changes=[GoalStateChange(goal_id=goal.id, new_status="resolved")],
        )

        with patch("app.cognition.turn_cognition.run_appraisal", return_value=fake_appraisal):
            run_cognition_turn(
                session=db_session,
                user_id=_UID,
                user_message="Ya aprendí Python!",
                settings_service=svc,
                personality=CANONICAL_PERSONALITY,
                trace_id="t-sc-001",
            )

        db_session.refresh(goal)
        assert goal.status == "resolved"
        assert goal.resolved_at is not None

        # Cleanup
        for row in db_session.exec(select(Goal).where(Goal.user_id == _UID)).all():
            db_session.delete(row)
        for row in db_session.exec(select(_MS).where(_MS.user_id == _UID)).all():
            db_session.delete(row)
        db_session.commit()


# ---------------------------------------------------------------------------
# Paso 4 Part 2 — MilestoneIntent: parse unit tests
# ---------------------------------------------------------------------------

class TestParseMilestoneIntent:
    def test_add_milestone_valid(self):
        mi = _parse_milestone_intent({
            "action": "add_milestone",
            "goal_id": 3,
            "description": "Buscar un profesor",
        })
        assert mi is not None
        assert mi.action == "add_milestone"
        assert mi.goal_id == 3
        assert mi.description == "Buscar un profesor"
        assert mi.milestone_id is None

    def test_complete_valid(self):
        mi = _parse_milestone_intent({"action": "complete", "milestone_id": 17})
        assert mi is not None
        assert mi.action == "complete"
        assert mi.milestone_id == 17
        assert mi.goal_id is None

    def test_rejects_non_dict(self):
        assert _parse_milestone_intent("add_milestone") is None
        assert _parse_milestone_intent(None) is None

    def test_add_milestone_rejects_missing_goal_id(self):
        assert _parse_milestone_intent({
            "action": "add_milestone", "description": "Step 1"
        }) is None

    def test_add_milestone_rejects_empty_description(self):
        assert _parse_milestone_intent({
            "action": "add_milestone", "goal_id": 1, "description": "  "
        }) is None

    def test_complete_rejects_missing_milestone_id(self):
        assert _parse_milestone_intent({"action": "complete"}) is None

    def test_rejects_unknown_action(self):
        assert _parse_milestone_intent({
            "action": "update", "goal_id": 1, "description": "X"
        }) is None

    def test_parse_appraisal_includes_milestone_updates(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
            "goal_relevance": [],
            "goal_state_changes": [],
            "milestone_updates": [
                {"action": "add_milestone", "goal_id": 5, "description": "Primer hito"},
                {"action": "complete", "milestone_id": 12},
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert len(result.milestone_updates) == 2
        assert result.milestone_updates[0].action == "add_milestone"
        assert result.milestone_updates[0].goal_id == 5
        assert result.milestone_updates[1].action == "complete"
        assert result.milestone_updates[1].milestone_id == 12

    def test_parse_appraisal_filters_invalid_milestone_updates(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
            "goal_relevance": [],
            "goal_state_changes": [],
            "milestone_updates": [
                {"action": "add_milestone", "goal_id": 1, "description": "Valid"},
                {"action": "add_milestone", "description": "No goal_id"},   # invalid
                "not-a-dict",                                                # invalid
            ],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert len(result.milestone_updates) == 1

    def test_parse_appraisal_missing_milestone_field_returns_empty(self):
        raw = json.dumps({
            "interest_delta": 0.0,
            "frustration_delta": 0.0,
            "trust_evidence": 0.0,
            "goal_updates": [],
            "goal_relevance": [],
        })
        result = _parse_appraisal(raw)
        assert result is not None
        assert result.milestone_updates == []

    def test_zero_has_empty_milestone_updates(self):
        z = AppraisalResult.zero()
        assert z.milestone_updates == []

    def test_parse_goal_update_with_initial_milestones(self):
        raw = {
            "action": "create",
            "description": "Leer Don Quijote",
            "scope": "long_term",
            "base_importance": 0.6,
            "is_wellbeing": False,
            "initial_milestones": ["Conseguir el libro", "Leer la primera parte"],
        }
        gu = _parse_goal_update(raw)
        assert gu is not None
        assert gu.initial_milestones == ["Conseguir el libro", "Leer la primera parte"]

    def test_parse_goal_update_initial_milestones_defaults_to_empty(self):
        raw = {
            "action": "create",
            "description": "Meta simple",
            "scope": "short_term",
            "base_importance": 0.5,
            "is_wellbeing": False,
        }
        gu = _parse_goal_update(raw)
        assert gu is not None
        assert gu.initial_milestones == []


# ---------------------------------------------------------------------------
# Paso 4 Part 2 — GoalMilestone DB operations
# ---------------------------------------------------------------------------

class TestMilestoneOperations:
    _UID_A = 8980
    _UID_B = 8981

    def _cleanup(self, session: Session, *user_ids: int) -> None:
        for uid in user_ids:
            for g in session.exec(select(Goal).where(Goal.user_id == uid)).all():
                for m in session.exec(
                    select(GoalMilestone).where(GoalMilestone.goal_id == g.id)
                ).all():
                    session.delete(m)
                session.delete(g)
        session.commit()

    def _make_goal(self, session: Session, user_id: int, description: str = "Goal") -> Goal:
        g = Goal(user_id=user_id, scope="short_term", description=description,
                 origin="autonomous", status="active")
        session.add(g)
        session.commit()
        session.refresh(g)
        return g

    def test_get_milestones_ordered_by_order_index(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A)

        for i, desc in enumerate(["Tercero", "Primero", "Segundo"]):
            db_session.add(GoalMilestone(
                goal_id=goal.id, description=desc, status="pending", order_index=i
            ))
        db_session.commit()

        milestones = get_milestones_for_goal(db_session, goal.id)
        assert [m.description for m in milestones] == ["Tercero", "Primero", "Segundo"]
        assert [m.order_index for m in milestones] == [0, 1, 2]

        self._cleanup(db_session, self._UID_A)

    def test_create_goal_from_intent_creates_initial_milestones(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        intent = GoalUpdateIntent(
            action="create",
            description="Aprender cocina italiana",
            scope="long_term",
            base_importance=0.7,
            is_wellbeing=False,
            initial_milestones=["Comprar ingredientes", "Hacer pasta casera"],
        )
        goal = create_goal_from_intent(db_session, self._UID_A, intent)

        milestones = get_milestones_for_goal(db_session, goal.id)
        assert len(milestones) == 2
        assert milestones[0].description == "Comprar ingredientes"
        assert milestones[0].order_index == 0
        assert milestones[0].status == "pending"
        assert milestones[1].description == "Hacer pasta casera"
        assert milestones[1].order_index == 1

        self._cleanup(db_session, self._UID_A)

    def test_create_goal_from_intent_no_milestones(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)

        intent = GoalUpdateIntent(
            action="create", description="Meta simple", scope="short_term",
            base_importance=0.5, is_wellbeing=False,
        )
        goal = create_goal_from_intent(db_session, self._UID_A, intent)
        assert get_milestones_for_goal(db_session, goal.id) == []

        self._cleanup(db_session, self._UID_A)

    def test_apply_milestone_updates_add_appends_milestone(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A, "Goal with milestones")

        updates = [MilestoneIntent(action="add_milestone", goal_id=goal.id,
                                   description="Nuevo hito")]
        apply_milestone_updates(db_session, self._UID_A, updates)

        milestones = get_milestones_for_goal(db_session, goal.id)
        assert len(milestones) == 1
        assert milestones[0].description == "Nuevo hito"
        assert milestones[0].status == "pending"
        assert milestones[0].order_index == 0

        self._cleanup(db_session, self._UID_A)

    def test_apply_milestone_updates_add_order_continues_from_existing(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A)

        # Add two initial milestones
        db_session.add(GoalMilestone(goal_id=goal.id, description="Hito 0",
                                     status="pending", order_index=0))
        db_session.add(GoalMilestone(goal_id=goal.id, description="Hito 1",
                                     status="pending", order_index=1))
        db_session.commit()

        # Add a third via apply_milestone_updates
        apply_milestone_updates(
            db_session, self._UID_A,
            [MilestoneIntent(action="add_milestone", goal_id=goal.id, description="Hito 2")]
        )

        milestones = get_milestones_for_goal(db_session, goal.id)
        assert len(milestones) == 3
        assert milestones[2].order_index == 2
        assert milestones[2].description == "Hito 2"

        self._cleanup(db_session, self._UID_A)

    def test_apply_milestone_updates_add_ignores_other_users_goal(self, db_session: Session):
        self._cleanup(db_session, self._UID_A, self._UID_B)
        goal_b = self._make_goal(db_session, self._UID_B)

        # UID_A tries to add a milestone to UID_B's goal — must be ignored
        apply_milestone_updates(
            db_session, self._UID_A,
            [MilestoneIntent(action="add_milestone", goal_id=goal_b.id, description="Intruso")]
        )

        assert get_milestones_for_goal(db_session, goal_b.id) == []

        self._cleanup(db_session, self._UID_A, self._UID_B)

    def test_apply_milestone_updates_complete_sets_status_and_completed_at(
        self, db_session: Session
    ):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A)
        ms = GoalMilestone(goal_id=goal.id, description="Hito completable",
                           status="pending", order_index=0)
        db_session.add(ms)
        db_session.commit()
        db_session.refresh(ms)

        apply_milestone_updates(
            db_session, self._UID_A,
            [MilestoneIntent(action="complete", milestone_id=ms.id)]
        )

        db_session.refresh(ms)
        assert ms.status == "completed"
        assert ms.completed_at is not None

        self._cleanup(db_session, self._UID_A)

    def test_apply_milestone_updates_complete_ignores_other_users_milestone(
        self, db_session: Session
    ):
        self._cleanup(db_session, self._UID_A, self._UID_B)
        goal_b = self._make_goal(db_session, self._UID_B)
        ms = GoalMilestone(goal_id=goal_b.id, description="Hito de B",
                           status="pending", order_index=0)
        db_session.add(ms)
        db_session.commit()
        db_session.refresh(ms)

        # UID_A tries to complete UID_B's milestone — must be ignored
        apply_milestone_updates(
            db_session, self._UID_A,
            [MilestoneIntent(action="complete", milestone_id=ms.id)]
        )

        db_session.refresh(ms)
        assert ms.status == "pending"
        assert ms.completed_at is None

        self._cleanup(db_session, self._UID_A, self._UID_B)

    def test_run_cognition_turn_applies_milestone_add(self, db_session: Session):
        _UID = 8982
        for g in db_session.exec(select(Goal).where(Goal.user_id == _UID)).all():
            for m in db_session.exec(
                select(GoalMilestone).where(GoalMilestone.goal_id == g.id)
            ).all():
                db_session.delete(m)
            db_session.delete(g)
        for row in db_session.exec(
            select(MentalState).where(MentalState.user_id == _UID)
        ).all():
            db_session.delete(row)
        db_session.commit()

        goal = Goal(user_id=_UID, scope="long_term", description="Correr maratón",
                    origin="autonomous", status="active")
        db_session.add(goal)
        db_session.commit()
        db_session.refresh(goal)

        svc = SettingsService(db_session)
        fake_appraisal = AppraisalResult(
            interest_delta=0.1,
            frustration_delta=0.0,
            trust_evidence=0.0,
            milestone_updates=[
                MilestoneIntent(action="add_milestone", goal_id=goal.id,
                                description="Empezar a correr 5km")
            ],
        )

        with patch("app.cognition.turn_cognition.run_appraisal", return_value=fake_appraisal):
            run_cognition_turn(
                session=db_session,
                user_id=_UID,
                user_message="Quiero preparar una maratón este año",
                settings_service=svc,
                personality=CANONICAL_PERSONALITY,
                trace_id="t-ms-001",
            )

        milestones = get_milestones_for_goal(db_session, goal.id)
        assert len(milestones) == 1
        assert milestones[0].description == "Empezar a correr 5km"
        assert milestones[0].status == "pending"

        # Cleanup
        for m in db_session.exec(
            select(GoalMilestone).where(GoalMilestone.goal_id == goal.id)
        ).all():
            db_session.delete(m)
        db_session.delete(goal)
        for row in db_session.exec(
            select(MentalState).where(MentalState.user_id == _UID)
        ).all():
            db_session.delete(row)
        db_session.commit()


# ---------------------------------------------------------------------------
# Paso 4 Part 4 — resolve_expired_short_term_goals
# ---------------------------------------------------------------------------

class TestResolveExpiredShortTermGoals:
    _UID_A = 8990
    _UID_B = 8991

    def _cleanup(self, session: Session, *user_ids: int) -> None:
        for uid in user_ids:
            for row in session.exec(select(Goal).where(Goal.user_id == uid)).all():
                session.delete(row)
        session.commit()

    def _make_goal(
        self,
        session: Session,
        user_id: int,
        scope: str = "short_term",
        status: str = "active",
        age_hours: float = 0.0,
    ) -> Goal:
        from datetime import timezone
        created = utc_now() - timedelta(hours=age_hours)
        g = Goal(
            user_id=user_id, scope=scope, description=f"Goal uid={user_id}",
            origin="autonomous", status=status, created_at=created,
        )
        session.add(g)
        session.commit()
        session.refresh(g)
        return g

    def test_active_short_term_older_than_threshold_is_expired(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A, scope="short_term", age_hours=25)

        count = resolve_expired_short_term_goals(db_session, self._UID_A, max_age_hours=24)

        db_session.refresh(goal)
        assert goal.status == "expired"
        assert count == 1

        self._cleanup(db_session, self._UID_A)

    def test_long_term_goal_older_than_threshold_not_expired(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A, scope="long_term", age_hours=48)

        count = resolve_expired_short_term_goals(db_session, self._UID_A, max_age_hours=24)

        db_session.refresh(goal)
        assert goal.status == "active"
        assert count == 0

        self._cleanup(db_session, self._UID_A)

    def test_short_term_within_threshold_not_expired(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(db_session, self._UID_A, scope="short_term", age_hours=1)

        count = resolve_expired_short_term_goals(db_session, self._UID_A, max_age_hours=24)

        db_session.refresh(goal)
        assert goal.status == "active"
        assert count == 0

        self._cleanup(db_session, self._UID_A)

    def test_already_resolved_goal_not_changed(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        goal = self._make_goal(
            db_session, self._UID_A, scope="short_term", status="resolved", age_hours=48
        )
        goal.resolved_at = utc_now()
        db_session.add(goal)
        db_session.commit()

        resolve_expired_short_term_goals(db_session, self._UID_A, max_age_hours=24)

        db_session.refresh(goal)
        assert goal.status == "resolved"

        self._cleanup(db_session, self._UID_A)

    def test_user_isolation_other_users_goals_not_affected(self, db_session: Session):
        self._cleanup(db_session, self._UID_A, self._UID_B)
        goal_b = self._make_goal(db_session, self._UID_B, scope="short_term", age_hours=48)

        # Expire UID_A's goals — must not touch UID_B's
        resolve_expired_short_term_goals(db_session, self._UID_A, max_age_hours=24)

        db_session.refresh(goal_b)
        assert goal_b.status == "active"

        self._cleanup(db_session, self._UID_A, self._UID_B)

    def test_returns_count_of_expired_goals(self, db_session: Session):
        self._cleanup(db_session, self._UID_A)
        self._make_goal(db_session, self._UID_A, scope="short_term", age_hours=48)
        self._make_goal(db_session, self._UID_A, scope="short_term", age_hours=36)
        self._make_goal(db_session, self._UID_A, scope="short_term", age_hours=1)  # fresh

        count = resolve_expired_short_term_goals(db_session, self._UID_A, max_age_hours=24)
        assert count == 2

        self._cleanup(db_session, self._UID_A)

    def test_run_cognition_turn_expires_stale_short_term_before_building_context(
        self, db_session: Session
    ):
        _UID = 8992
        for row in db_session.exec(select(Goal).where(Goal.user_id == _UID)).all():
            db_session.delete(row)
        for row in db_session.exec(
            select(MentalState).where(MentalState.user_id == _UID)
        ).all():
            db_session.delete(row)
        db_session.commit()

        # Stale short_term goal — 48h old
        stale_created = utc_now() - timedelta(hours=48)
        stale_goal = Goal(
            user_id=_UID, scope="short_term", description="Stale goal",
            origin="autonomous", status="active", created_at=stale_created,
        )
        db_session.add(stale_goal)
        db_session.commit()
        db_session.refresh(stale_goal)

        svc = SettingsService(db_session)
        result = run_cognition_turn(
            session=db_session,
            user_id=_UID,
            user_message="Hola de nuevo",
            settings_service=svc,
            personality=CANONICAL_PERSONALITY,
            trace_id="t-exp-001",
        )

        # Stale goal must be expired
        db_session.refresh(stale_goal)
        assert stale_goal.status == "expired"
        # The active_goals returned should NOT include it
        assert not any(g.id == stale_goal.id for g in result.active_goals)

        # Cleanup
        for row in db_session.exec(select(Goal).where(Goal.user_id == _UID)).all():
            db_session.delete(row)
        for row in db_session.exec(
            select(MentalState).where(MentalState.user_id == _UID)
        ).all():
            db_session.delete(row)
        db_session.commit()

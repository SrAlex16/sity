"""Tests for goal_urgent trigger — initiative ajuste for Memoria Prospectiva (sección 28).

Covers:
  - _check_goal_urgent: above threshold → candidate returned with correct context
  - _check_goal_urgent: below threshold → None
  - _check_goal_urgent: multiple goals → picks highest effective_priority
  - _check_goal_urgent: is_wellbeing=True → same behavior as normal goal
  - _check_goal_urgent: scope=short_term or status!=active → excluded
  - _check_goal_urgent: no long_term active goals → None
  - settings toggle trigger_goal_urgent=False → _check_goal_urgent not called
  - _PRIORITY ordering: goal_urgent=1 between open_loop=0 and conversation_abandoned=2
  - _build_user_message: goal_urgent branch includes goal_description and importance
  - _build_user_message: is_wellbeing=True adds sensitivity note
  - _call_haiku: uses _SYSTEM_GOAL_URGENT for goal_urgent trigger
  - effective_priority formula with relevance_boost=1.0, tone="neutral"
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _add_goal(
    db: Session,
    user_id: int,
    base_importance: float = 0.75,
    scope: str = "long_term",
    status: str = "active",
    is_wellbeing: bool = False,
    description: str = "Aprender a tocar la guitarra",
) -> None:
    from app.memory.models import Goal
    db.add(Goal(
        user_id=user_id,
        scope=scope,
        description=description,
        origin="autonomous",
        base_importance=base_importance,
        status=status,
        is_wellbeing=is_wellbeing,
    ))
    db.commit()


def _candidate(trigger_type: str, context: dict | None = None):
    from app.initiative.detector import TriggerCandidate
    return TriggerCandidate(
        trigger_type=trigger_type,
        session_id="user:1",
        context=context or {},
    )


# ---------------------------------------------------------------------------
# _check_goal_urgent — threshold logic
# ---------------------------------------------------------------------------

class TestCheckGoalUrgentThreshold:
    """ep = 0.6*bi + 0.4  (relevance_boost=1.0, tone="neutral").
    Threshold 0.85 → requires base_importance >= 0.75.
    """

    def test_above_threshold_returns_candidate(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.75)  # ep = 0.85 exactly

        result = _check_goal_urgent("user:1", db)

        assert result is not None
        assert result.trigger_type == "goal_urgent"
        assert result.session_id == "user:1"

    def test_context_contains_goal_description_and_priority(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.80, description="Correr una maratón")

        result = _check_goal_urgent("user:1", db)

        assert result is not None
        assert result.context["goal_description"] == "Correr una maratón"
        assert result.context["base_importance"] == 0.80
        assert result.context["effective_priority"] >= 0.85

    def test_below_threshold_returns_none(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.70)  # ep = 0.82 < 0.85

        result = _check_goal_urgent("user:1", db)

        assert result is None

    def test_no_long_term_active_goals_returns_none(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()

        result = _check_goal_urgent("user:1", db)

        assert result is None

    def test_invalid_session_id_returns_none(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()

        result = _check_goal_urgent("guest:abc", db)

        assert result is None


# ---------------------------------------------------------------------------
# _check_goal_urgent — scope and status filters
# ---------------------------------------------------------------------------

class TestCheckGoalUrgentFilters:

    def test_short_term_goal_excluded(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.80, scope="short_term")

        result = _check_goal_urgent("user:1", db)

        assert result is None

    def test_resolved_goal_excluded(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.80, status="resolved")

        result = _check_goal_urgent("user:1", db)

        assert result is None

    def test_abandoned_goal_excluded(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.90, status="abandoned")

        result = _check_goal_urgent("user:1", db)

        assert result is None

    def test_multiple_goals_picks_highest_priority(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.75, description="Meta A")  # ep=0.85
        _add_goal(db, user_id=1, base_importance=0.90, description="Meta B")  # ep=0.94

        result = _check_goal_urgent("user:1", db)

        assert result is not None
        assert result.context["goal_description"] == "Meta B"
        assert result.context["effective_priority"] > 0.90

    def test_session_isolation(self):
        """Goal from user:2 must not appear in user:1 check."""
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=2, base_importance=0.90)

        result = _check_goal_urgent("user:1", db)

        assert result is None


# ---------------------------------------------------------------------------
# _check_goal_urgent — is_wellbeing
# ---------------------------------------------------------------------------

class TestCheckGoalUrgentWellbeing:

    def test_wellbeing_goal_above_threshold_returns_candidate(self):
        """is_wellbeing=True has same trigger behavior — irony never applies here anyway."""
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.80, is_wellbeing=True)

        result = _check_goal_urgent("user:1", db)

        assert result is not None
        assert result.context["is_wellbeing"] is True

    def test_wellbeing_goal_below_threshold_returns_none(self):
        from app.initiative.detector import _check_goal_urgent
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.70, is_wellbeing=True)

        result = _check_goal_urgent("user:1", db)

        assert result is None


# ---------------------------------------------------------------------------
# Settings toggle
# ---------------------------------------------------------------------------

class TestGoalUrgentToggle:

    def test_toggle_disabled_skips_check(self):
        """With trigger_goal_urgent=False, _check_goal_urgent is never called."""
        from app.initiative.detector import get_trigger_candidates
        from app.initiative.settings import InitiativeSettings, set_initiative_settings
        db = _make_db()
        _add_goal(db, user_id=1, base_importance=0.90)

        with patch("app.initiative.detector.get_initiative_settings") as mock_settings:
            mock_settings.return_value = InitiativeSettings(
                enabled=True,
                trigger_conversation_abandoned=False,
                trigger_long_inactivity=False,
                trigger_open_loop=False,
                trigger_goal_urgent=False,
            )
            with patch("app.initiative.detector._check_goal_urgent") as mock_check:
                get_trigger_candidates("user:1", db)
                mock_check.assert_not_called()

    def test_toggle_enabled_calls_check(self):
        """With trigger_goal_urgent=True (default), _check_goal_urgent IS called."""
        from app.initiative.detector import get_trigger_candidates
        from app.initiative.settings import InitiativeSettings
        db = _make_db()

        with patch("app.initiative.detector.get_initiative_settings") as mock_settings:
            mock_settings.return_value = InitiativeSettings(
                enabled=True,
                trigger_conversation_abandoned=False,
                trigger_long_inactivity=False,
                trigger_open_loop=False,
                trigger_goal_urgent=True,
            )
            with patch("app.initiative.detector._check_goal_urgent", return_value=None) as mock_check:
                get_trigger_candidates("user:1", db)
                mock_check.assert_called_once()

    def test_default_toggle_is_true(self):
        from app.initiative.settings import InitiativeSettings
        settings = InitiativeSettings()
        assert settings.trigger_goal_urgent is True


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:

    def test_goal_urgent_priority_between_open_loop_and_conversation_abandoned(self):
        from app.initiative.runner import _PRIORITY
        assert _PRIORITY["open_loop"] < _PRIORITY["goal_urgent"]
        assert _PRIORITY["goal_urgent"] < _PRIORITY["conversation_abandoned"]
        assert _PRIORITY["conversation_abandoned"] < _PRIORITY["long_inactivity"]

    def test_goal_urgent_wins_over_conversation_abandoned(self):
        from app.initiative.detector import TriggerCandidate
        from app.initiative.runner import _pick_candidate
        candidates = [
            TriggerCandidate(trigger_type="conversation_abandoned", session_id="user:1"),
            TriggerCandidate(trigger_type="goal_urgent", session_id="user:1"),
        ]
        picked = _pick_candidate(candidates)
        assert picked.trigger_type == "goal_urgent"

    def test_open_loop_wins_over_goal_urgent(self):
        from app.initiative.detector import TriggerCandidate
        from app.initiative.runner import _pick_candidate
        candidates = [
            TriggerCandidate(trigger_type="goal_urgent", session_id="user:1"),
            TriggerCandidate(trigger_type="open_loop", session_id="user:1"),
        ]
        picked = _pick_candidate(candidates)
        assert picked.trigger_type == "open_loop"


# ---------------------------------------------------------------------------
# _build_user_message — goal_urgent branch
# ---------------------------------------------------------------------------

class TestBuildUserMessageGoalUrgent:

    def test_includes_goal_description(self):
        from app.initiative.evaluator import _build_user_message
        c = _candidate(
            "goal_urgent",
            context={
                "goal_description": "Empezar a meditar cada mañana",
                "base_importance": 0.80,
                "effective_priority": 0.88,
                "is_wellbeing": False,
            },
        )
        msg = _build_user_message(c, social=None)
        assert "Empezar a meditar cada mañana" in msg
        assert "0.8" in msg
        assert "0.88" in msg

    def test_wellbeing_adds_sensitivity_note(self):
        from app.initiative.evaluator import _build_user_message
        c = _candidate(
            "goal_urgent",
            context={
                "goal_description": "Gestionar el estrés laboral",
                "base_importance": 0.80,
                "effective_priority": 0.88,
                "is_wellbeing": True,
            },
        )
        msg = _build_user_message(c, social=None)
        assert "bienestar" in msg.lower() or "sensibilidad" in msg.lower()

    def test_non_wellbeing_no_sensitivity_note(self):
        from app.initiative.evaluator import _build_user_message
        c = _candidate(
            "goal_urgent",
            context={
                "goal_description": "Aprender fotografía",
                "base_importance": 0.75,
                "effective_priority": 0.85,
                "is_wellbeing": False,
            },
        )
        msg = _build_user_message(c, social=None)
        assert "sensibilidad" not in msg.lower()


# ---------------------------------------------------------------------------
# _call_haiku — system prompt selection
# ---------------------------------------------------------------------------

class TestCallHaikuSystemPrompt:

    def test_goal_urgent_uses_goal_urgent_system(self):
        from app.initiative.evaluator import _SYSTEM_GOAL_URGENT, _call_haiku
        c = _candidate(
            "goal_urgent",
            context={
                "goal_description": "Terminar el proyecto",
                "base_importance": 0.80,
                "effective_priority": 0.88,
                "is_wellbeing": False,
            },
        )
        resp = MagicMock()
        resp.ok = True
        resp.text = '{"decision": "skip", "reasoning": "no context"}'
        mock_provider = MagicMock()
        mock_provider.generate.return_value = resp

        with patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider):
            _call_haiku(c, social=None)

        call_args = mock_provider.generate.call_args[0][0]
        assert call_args.system_prompt == _SYSTEM_GOAL_URGENT

    def test_standard_trigger_does_not_use_goal_urgent_system(self):
        from app.initiative.evaluator import _SYSTEM_GOAL_URGENT, _call_haiku
        c = _candidate("long_inactivity", context={"days_since_last_message": 7, "last_message_role": "user", "last_message_text": "ok"})
        resp = MagicMock()
        resp.ok = True
        resp.text = '{"decision": "skip", "reasoning": "inactive"}'
        mock_provider = MagicMock()
        mock_provider.generate.return_value = resp

        with patch("app.initiative.evaluator.build_ai_provider", return_value=mock_provider):
            _call_haiku(c, social=None)

        call_args = mock_provider.generate.call_args[0][0]
        assert call_args.system_prompt != _SYSTEM_GOAL_URGENT


# ---------------------------------------------------------------------------
# Effective priority formula verification
# ---------------------------------------------------------------------------

class TestEffectivePriorityFormula:

    def test_exactly_at_threshold(self):
        """base_importance=0.75, boost=1.0, neutral → ep=0.85 (threshold hit)."""
        from app.cognition.goal_priority import compute_effective_priority
        ep = compute_effective_priority(
            base_importance=0.75,
            relevance_boost=1.0,
            tone="neutral",
            is_wellbeing=False,
        )
        assert abs(ep - 0.85) < 1e-9

    def test_just_below_threshold(self):
        """base_importance=0.74, boost=1.0, neutral → ep=0.844 (below threshold)."""
        from app.cognition.goal_priority import compute_effective_priority
        ep = compute_effective_priority(
            base_importance=0.74,
            relevance_boost=1.0,
            tone="neutral",
            is_wellbeing=False,
        )
        assert ep < 0.85

    def test_wellbeing_irony_bypass_gives_same_ep(self):
        """is_wellbeing=True with neutral tone should give same result as False (no irony either way)."""
        from app.cognition.goal_priority import compute_effective_priority
        ep_normal = compute_effective_priority(0.80, 1.0, "neutral", False)
        ep_wellbeing = compute_effective_priority(0.80, 1.0, "neutral", True)
        assert ep_normal == ep_wellbeing

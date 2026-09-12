"""Tests for Operación Remake Fase 8 Paso 2 — BeliefAttribution from Reflection Step.

Properties verified:

JSON parsing:
1.  _parse_reflection_response with user_belief_updates → populated field.
2.  _parse_reflection_response without user_belief_updates key → defaults to [].
3.  _parse_reflection_response: entries capped to 200 chars (same as other list fields).

Backward compatibility:
4.  run_reflection with empty user_belief_updates → no BeliefAttribution rows created.
5.  ReflectionLog.user_belief_updates_json stored correctly.

BeliefAttribution creation (salience-gated):
6.  Non-empty user_belief_updates → BeliefAttribution rows created for correct user_id.
7.  BeliefAttribution rows have confidence=0.35, source="reflection".
8.  BeliefAttribution.context_type matches perception.context_type.
9.  Multiple user_belief_updates → multiple BeliefAttribution rows.
10. user_belief_updates with blank strings → no rows created (stripped).

Isolation:
11. user_belief_updates from user A do not appear for user B.

Salience gate:
12. user_belief_updates only processed when run_reflection is called
    (salience gate is caller's responsibility — reflection itself always processes).
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch

from sqlmodel import Session, delete as sql_delete

from app.cognition.reflection import (
    ReflectionResult,
    _parse_reflection_response,
    run_reflection,
)
from app.cognition.appraisal import AppraisalResult
from app.cognition.perception import PerceptionResult
from app.memory.models import BeliefAttribution, ReflectionLog


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_perception(context_type: str = "implementation") -> PerceptionResult:
    return PerceptionResult(
        user_intent="request",
        tone="neutral",
        challenge=0.10,
        social_signal=0.20,
        novelty=0.30,
        context_type=context_type,
    )


def _make_appraisal() -> AppraisalResult:
    return AppraisalResult(interest_delta=0.05, frustration_delta=0.0, trust_evidence=0.0)


def _mock_result(user_belief_updates: list[str]) -> ReflectionResult:
    return ReflectionResult(
        success_estimate=0.70,
        memory_candidates=[],
        belief_updates=[],
        relationship_evidence=[],
        goal_updates=[],
        self_model_updates=[],
        user_belief_updates=user_belief_updates,
    )


def _clean_beliefs(session, user_id: int) -> None:
    session.exec(sql_delete(BeliefAttribution).where(BeliefAttribution.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


def _clean_logs(session, user_id: int) -> None:
    session.exec(sql_delete(ReflectionLog).where(ReflectionLog.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


# ---------------------------------------------------------------------------
# 1–3: JSON parsing
# ---------------------------------------------------------------------------

class TestParseUserBeliefUpdates:

    def test_parses_user_belief_updates(self):
        # Property 1
        raw = json.dumps({
            "success_estimate": 0.70,
            "memory_candidates": [],
            "belief_updates": [],
            "relationship_evidence": [],
            "goal_updates": [],
            "self_model_updates": [],
            "user_belief_updates": ["User believes Python is easier than Rust"],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert len(result.user_belief_updates) == 1
        assert result.user_belief_updates[0] == "User believes Python is easier than Rust"

    def test_missing_key_defaults_to_empty(self):
        # Property 2 — old JSON without user_belief_updates key → []
        raw = json.dumps({
            "success_estimate": 0.70,
            "memory_candidates": [],
            "belief_updates": [],
            "relationship_evidence": [],
            "goal_updates": [],
            "self_model_updates": [],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert result.user_belief_updates == []

    def test_entries_capped_at_200_chars(self):
        # Property 3
        long_entry = "x" * 250
        raw = json.dumps({
            "success_estimate": 0.70,
            "memory_candidates": [],
            "belief_updates": [],
            "relationship_evidence": [],
            "goal_updates": [],
            "self_model_updates": [],
            "user_belief_updates": [long_entry],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert len(result.user_belief_updates[0]) == 200


# ---------------------------------------------------------------------------
# 4–5: Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:

    def test_empty_user_beliefs_no_attribution_rows(self, db_session):
        # Property 4
        _clean_beliefs(db_session, 901)
        _clean_logs(db_session, 901)
        mock_result = _mock_result(user_belief_updates=[])
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=901,
                user_message="test",
                perception=_make_perception(),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.60,
                trace_id="t-compat-1",
            )
        rows = db_session.exec(
            __import__("sqlmodel").select(BeliefAttribution)
            .where(BeliefAttribution.user_id == 901)
        ).all()
        assert len(rows) == 0

    def test_user_belief_updates_json_stored_in_log(self, db_session):
        # Property 5
        _clean_beliefs(db_session, 902)
        _clean_logs(db_session, 902)
        beliefs = ["User believes Sity remembers all conversations"]
        mock_result = _mock_result(user_belief_updates=beliefs)
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=902,
                user_message="test",
                perception=_make_perception(),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.65,
                trace_id="t-log-902",
            )
        from sqlmodel import select
        row = db_session.exec(
            select(ReflectionLog).where(ReflectionLog.user_id == 902)
        ).first()
        assert row is not None
        stored = json.loads(row.user_belief_updates_json)
        assert stored == beliefs


# ---------------------------------------------------------------------------
# 6–10: BeliefAttribution creation
# ---------------------------------------------------------------------------

class TestBeliefAttributionCreation:

    def test_non_empty_creates_attribution_rows(self, db_session):
        # Property 6
        _clean_beliefs(db_session, 911)
        _clean_logs(db_session, 911)
        mock_result = _mock_result(
            user_belief_updates=["User believes testing is less important than shipping"]
        )
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=911,
                user_message="let's ship it",
                perception=_make_perception("implementation"),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.55,
            )
        from sqlmodel import select
        rows = db_session.exec(
            select(BeliefAttribution).where(BeliefAttribution.user_id == 911)
        ).all()
        assert len(rows) == 1
        assert "testing" in rows[0].proposition

    def test_attribution_confidence_and_source(self, db_session):
        # Property 7 — confidence=0.35, source="reflection"
        _clean_beliefs(db_session, 912)
        _clean_logs(db_session, 912)
        mock_result = _mock_result(user_belief_updates=["User believes X"])
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=912,
                user_message="test",
                perception=_make_perception(),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.55,
            )
        from sqlmodel import select
        row = db_session.exec(
            select(BeliefAttribution).where(BeliefAttribution.user_id == 912)
        ).first()
        assert row is not None
        assert row.confidence == pytest.approx(0.35, abs=1e-6)
        assert row.source == "reflection"

    def test_attribution_context_type_matches_perception(self, db_session):
        # Property 8
        _clean_beliefs(db_session, 913)
        _clean_logs(db_session, 913)
        mock_result = _mock_result(user_belief_updates=["User believes X"])
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=913,
                user_message="test",
                perception=_make_perception("debugging"),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.55,
            )
        from sqlmodel import select
        row = db_session.exec(
            select(BeliefAttribution).where(BeliefAttribution.user_id == 913)
        ).first()
        assert row is not None
        assert row.context_type == "debugging"

    def test_multiple_beliefs_create_multiple_rows(self, db_session):
        # Property 9
        _clean_beliefs(db_session, 914)
        _clean_logs(db_session, 914)
        mock_result = _mock_result(user_belief_updates=[
            "User believes A",
            "User believes B",
            "User believes C",
        ])
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=914,
                user_message="test",
                perception=_make_perception(),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.55,
            )
        from sqlmodel import select
        rows = db_session.exec(
            select(BeliefAttribution).where(BeliefAttribution.user_id == 914)
        ).all()
        assert len(rows) == 3

    def test_blank_entries_not_persisted(self, db_session):
        # Property 10
        _clean_beliefs(db_session, 915)
        _clean_logs(db_session, 915)
        mock_result = _mock_result(user_belief_updates=["   ", "", "  "])
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=915,
                user_message="test",
                perception=_make_perception(),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.55,
            )
        from sqlmodel import select
        rows = db_session.exec(
            select(BeliefAttribution).where(BeliefAttribution.user_id == 915)
        ).all()
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# 11: Isolation
# ---------------------------------------------------------------------------

class TestIsolation:

    def test_user_a_beliefs_not_visible_to_user_b(self, db_session):
        # Property 11
        _clean_beliefs(db_session, 921)
        _clean_beliefs(db_session, 922)
        _clean_logs(db_session, 921)
        mock_result = _mock_result(user_belief_updates=["User 921 believes X"])
        with patch("app.cognition.reflection._call_reflection_haiku", return_value=mock_result):
            run_reflection(
                db_session,
                user_id=921,
                user_message="test",
                perception=_make_perception(),
                appraisal=_make_appraisal(),
                decision=None,
                salience_total=0.55,
            )
        from sqlmodel import select
        rows_b = db_session.exec(
            select(BeliefAttribution).where(BeliefAttribution.user_id == 922)
        ).all()
        assert len(rows_b) == 0

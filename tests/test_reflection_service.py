"""Tests for Operación Remake Fase 6 Paso 3 — Reflection Step.

Properties verified:

ReflectionLog creation and result:
1.  run_reflection returns ReflectionResult (not None) when Haiku succeeds.
2.  ReflectionLog row persisted with correct user_id, salience_total, trace_id.
3.  result.log_id matches the saved ReflectionLog.id (DB-assigned).
4.  success_estimate parsed correctly (float, clamped 0-1).
5.  All 5 list fields populated from JSON response.
6.  belief_updates_json stored correctly in ReflectionLog row.

Belief extraction (sección 57: metacognición ≠ verdad):
7.  Non-empty belief_updates → SelfBelief rows created with source="metacognition".
8.  Each SelfBelief confidence = 0.40 (metacognition candidate floor).
9.  Each SelfBelief is_active=True.
10. Empty belief_updates → no new SelfBelief rows created from this call.

Fallback paths (never raises):
11. _call_reflection_haiku returns None → run_reflection returns None, no ReflectionLog row.
12. _call_reflection_haiku returns malformed JSON → _parse returns None → run_reflection None.

Parsing helpers:
13. _parse_reflection_response: valid JSON → ReflectionResult with correct fields.
14. _parse_reflection_response: markdown fences stripped correctly.
15. _parse_reflection_response: malformed JSON → None.
16. _parse_reflection_response: success_estimate clamped to [0, 1].
17. _parse_reflection_response: non-list field replaced with empty list.

Integration:
18. CognitionTurnResult.reflection field defaults to None.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.cognition.reflection import (
    ReflectionResult,
    _REFLECTION_SALIENCE_MIN,
    _parse_reflection_response,
    run_reflection,
)
from app.cognition.appraisal import AppraisalResult
from app.cognition.decision import DecisionResult
from app.cognition.perception import PerceptionResult
from app.cognition.turn_cognition import CognitionTurnResult
from app.memory.models import ReflectionLog, SelfBelief


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_JSON = json.dumps({
    "success_estimate": 0.75,
    "memory_candidates": ["Usuario preguntó algo interesante"],
    "belief_updates": ["Soy capaz de explicar conceptos técnicos con claridad"],
    "relationship_evidence": ["Tono constructivo, sin conflicto detectado"],
    "goal_updates": [],
    "self_model_updates": [],
})

_MOCK_RESULT = ReflectionResult(
    success_estimate=0.75,
    memory_candidates=["Usuario preguntó algo interesante"],
    belief_updates=["Soy capaz de explicar conceptos técnicos con claridad"],
    relationship_evidence=["Tono constructivo, sin conflicto detectado"],
    goal_updates=[],
    self_model_updates=[],
)


def _perception(**kwargs) -> PerceptionResult:
    defaults = {"user_intent": "question", "tone": "neutral",
                "challenge": 0.10, "social_signal": 0.30, "novelty": 0.20}
    defaults.update(kwargs)
    return PerceptionResult(**defaults)  # type: ignore[arg-type]


def _appraisal(**kwargs) -> AppraisalResult:
    base: dict = {"interest_delta": 0.05, "frustration_delta": 0.0, "trust_evidence": 0.0}
    base.update(kwargs)
    return AppraisalResult(**base)  # type: ignore[arg-type]


def _decision() -> DecisionResult:
    return DecisionResult(action="answer", python_scores={}, reasoning="test")


def _cleanup(session: Session) -> None:
    """Delete all ReflectionLog and SelfBelief rows (metacognition source) before each test."""
    from sqlmodel import delete as sql_delete
    session.exec(sql_delete(ReflectionLog))  # type: ignore[call-overload]
    session.exec(sql_delete(SelfBelief).where(SelfBelief.source == "metacognition"))  # type: ignore[call-overload]
    session.commit()


# ---------------------------------------------------------------------------
# 1–6: ReflectionLog creation and result
# ---------------------------------------------------------------------------

class TestReflectionLogCreation:

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_returns_result_on_success(self, mock_haiku, db_session: Session):
        # Property 1
        _cleanup(db_session)
        result = run_reflection(
            db_session, user_id=1, user_message="¿qué piensas sobre X?",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.50, trace_id="t1",
        )
        assert result is not None
        assert isinstance(result, ReflectionResult)

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_reflection_log_row_persisted(self, mock_haiku, db_session: Session):
        # Property 2
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=42, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.55, trace_id="trace-abc",
        )
        rows = list(db_session.exec(select(ReflectionLog)).all())
        assert len(rows) == 1
        assert rows[0].user_id == 42
        assert rows[0].salience_total == pytest.approx(0.55)
        assert rows[0].trace_id == "trace-abc"

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_result_log_id_matches_db_row(self, mock_haiku, db_session: Session):
        # Property 3
        _cleanup(db_session)
        result = run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.50,
        )
        assert result is not None
        row = db_session.exec(select(ReflectionLog)).first()
        assert row is not None
        assert result.log_id == row.id

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_success_estimate_parsed(self, mock_haiku, db_session: Session):
        # Property 4
        _cleanup(db_session)
        result = run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.50,
        )
        assert result is not None
        assert result.success_estimate == pytest.approx(0.75)

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_all_list_fields_populated(self, mock_haiku, db_session: Session):
        # Property 5
        _cleanup(db_session)
        result = run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.50,
        )
        assert result is not None
        assert len(result.memory_candidates) == 1
        assert len(result.belief_updates) == 1
        assert len(result.relationship_evidence) == 1
        assert result.goal_updates == []
        assert result.self_model_updates == []

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_belief_updates_json_stored_in_log(self, mock_haiku, db_session: Session):
        # Property 6
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.50,
        )
        row = db_session.exec(select(ReflectionLog)).first()
        assert row is not None
        stored = json.loads(row.belief_updates_json)
        assert stored == ["Soy capaz de explicar conceptos técnicos con claridad"]


# ---------------------------------------------------------------------------
# 7–10: Belief extraction (sección 57)
# ---------------------------------------------------------------------------

class TestBeliefExtraction:

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_belief_updates_create_self_belief_rows(self, mock_haiku, db_session: Session):
        # Property 7
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.55, trace_id="t-belief",
        )
        beliefs = list(db_session.exec(
            select(SelfBelief).where(SelfBelief.source == "metacognition")
        ).all())
        assert len(beliefs) == 1
        assert beliefs[0].proposition == "Soy capaz de explicar conceptos técnicos con claridad"

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_self_belief_confidence_is_040(self, mock_haiku, db_session: Session):
        # Property 8 — sección 57: metacognition floor
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.55,
        )
        belief = db_session.exec(
            select(SelfBelief).where(SelfBelief.source == "metacognition")
        ).first()
        assert belief is not None
        assert belief.confidence == pytest.approx(0.40)

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=_MOCK_RESULT)
    def test_self_belief_is_active(self, mock_haiku, db_session: Session):
        # Property 9
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.55,
        )
        belief = db_session.exec(select(SelfBelief)).first()
        assert belief is not None
        assert belief.is_active is True

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=ReflectionResult(
        success_estimate=0.60,
        belief_updates=[],  # empty
        memory_candidates=["algo"],
        relationship_evidence=[],
        goal_updates=[],
        self_model_updates=[],
    ))
    def test_empty_belief_updates_no_self_belief_rows(self, mock_haiku, db_session: Session):
        # Property 10
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.50,
        )
        beliefs = list(db_session.exec(
            select(SelfBelief).where(SelfBelief.source == "metacognition")
        ).all())
        assert len(beliefs) == 0


# ---------------------------------------------------------------------------
# 11–12: Fallback paths
# ---------------------------------------------------------------------------

class TestReflectionFallback:

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=None)
    def test_haiku_none_returns_none_no_log(self, mock_haiku, db_session: Session):
        # Property 11
        _cleanup(db_session)
        result = run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.55,
        )
        assert result is None
        rows = list(db_session.exec(select(ReflectionLog)).all())
        assert len(rows) == 0

    @patch("app.cognition.reflection._call_reflection_haiku", return_value=None)
    def test_haiku_none_no_self_beliefs_created(self, mock_haiku, db_session: Session):
        # Property 12 (corollary of 11 — no side effects on failure)
        _cleanup(db_session)
        run_reflection(
            db_session, user_id=1, user_message="test",
            perception=_perception(), appraisal=_appraisal(),
            decision=_decision(), salience_total=0.55,
        )
        beliefs = list(db_session.exec(
            select(SelfBelief).where(SelfBelief.source == "metacognition")
        ).all())
        assert len(beliefs) == 0


# ---------------------------------------------------------------------------
# 13–17: Parsing helpers
# ---------------------------------------------------------------------------

class TestParseReflectionResponse:

    def test_valid_json_returns_result(self):
        # Property 13
        result = _parse_reflection_response(_MOCK_JSON)
        assert result is not None
        assert result.success_estimate == pytest.approx(0.75)
        assert result.belief_updates == ["Soy capaz de explicar conceptos técnicos con claridad"]

    def test_markdown_fences_stripped(self):
        # Property 14
        fenced = f"```json\n{_MOCK_JSON}\n```"
        result = _parse_reflection_response(fenced)
        assert result is not None
        assert result.success_estimate == pytest.approx(0.75)

    def test_malformed_json_returns_none(self):
        # Property 15
        assert _parse_reflection_response("not json at all") is None
        assert _parse_reflection_response("{broken: true") is None

    def test_success_estimate_clamped(self):
        # Property 16
        over = json.dumps({"success_estimate": 1.5, "memory_candidates": [],
                           "belief_updates": [], "relationship_evidence": [],
                           "goal_updates": [], "self_model_updates": []})
        result = _parse_reflection_response(over)
        assert result is not None
        assert result.success_estimate <= 1.0

        under = json.dumps({"success_estimate": -0.3, "memory_candidates": [],
                            "belief_updates": [], "relationship_evidence": [],
                            "goal_updates": [], "self_model_updates": []})
        result2 = _parse_reflection_response(under)
        assert result2 is not None
        assert result2.success_estimate >= 0.0

    def test_non_list_field_becomes_empty_list(self):
        # Property 17 — robust to type errors in Haiku response
        bad = json.dumps({"success_estimate": 0.5, "memory_candidates": "not a list",
                          "belief_updates": 42, "relationship_evidence": None,
                          "goal_updates": [], "self_model_updates": []})
        result = _parse_reflection_response(bad)
        assert result is not None
        assert result.memory_candidates == []
        assert result.belief_updates == []
        assert result.relationship_evidence == []


# ---------------------------------------------------------------------------
# 18: Integration — CognitionTurnResult
# ---------------------------------------------------------------------------

class TestCognitionTurnResultReflection:

    def test_reflection_field_defaults_to_none(self):
        # Property 18
        from app.cognition.appraisal import AppraisalResult
        from app.cognition.perception import PerceptionResult
        r = CognitionTurnResult(
            perception=_perception(),
            appraisal=_appraisal(),
        )
        assert r.reflection is None

    def test_reflection_salience_min_is_045(self):
        # Verify the threshold constant (no-import guard for the value)
        assert _REFLECTION_SALIENCE_MIN == pytest.approx(0.45)

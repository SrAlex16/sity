"""Tests for Operación Remake Fase 9 Paso 3 — SemanticFact read-only integration in Reflection.

Properties verified:

Context building (_build_reflection_context):
1.  No facts (None) → context does not contain KNOWN USER FACTS section.
2.  Empty list → context does not contain KNOWN USER FACTS section.
3.  Non-empty facts → KNOWN USER FACTS section appears in context.
4.  Top 5 facts by confidence are selected when more than 5 facts provided.
5.  Facts are sorted by confidence descending within the section.
6.  Proposition text appears verbatim in context.

run_reflection backward compatibility:
7.  semantic_facts=None → no regression (existing Fase 6 behavior preserved).
8.  semantic_facts=[] → no regression (treated same as None).
9.  semantic_facts=[fact] → fact proposition appears in Haiku context.

Integration — run_reflection with semantic_facts:
10. ReflectionResult returned correctly regardless of semantic_facts presence.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.cognition.reflection import (
    _build_reflection_context,
    run_reflection,
    ReflectionResult,
)
from app.cognition.perception import PerceptionResult
from app.cognition.appraisal import AppraisalResult
from app.memory.models import SemanticFact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_perception(**kwargs) -> PerceptionResult:
    defaults = dict(
        user_intent="question", tone="neutral",
        challenge=0.10, social_signal=0.30, novelty=0.20,
        context_type="explanation",
    )
    defaults.update(kwargs)
    return PerceptionResult(**defaults)


def _make_appraisal(**kwargs) -> AppraisalResult:
    defaults = dict(interest_delta=0.05, frustration_delta=0.0, trust_evidence=0.0)
    defaults.update(kwargs)
    return AppraisalResult(**defaults)


def _make_fact(user_id: int, proposition: str, confidence: float) -> SemanticFact:
    return SemanticFact(user_id=user_id, proposition=proposition, confidence=confidence)


def _base_context_kwargs():
    return dict(
        user_message="¿Puedes explicarme esto?",
        perception=_make_perception(),
        appraisal=_make_appraisal(),
        action="answer",
        salience_total=0.55,
    )


# ---------------------------------------------------------------------------
# 1–6: Context building
# ---------------------------------------------------------------------------

class TestBuildReflectionContext:

    def test_none_facts_no_section(self):
        # Property 1
        ctx = _build_reflection_context(**_base_context_kwargs(), semantic_facts=None)
        assert "KNOWN USER FACTS" not in ctx

    def test_empty_list_no_section(self):
        # Property 2
        ctx = _build_reflection_context(**_base_context_kwargs(), semantic_facts=[])
        assert "KNOWN USER FACTS" not in ctx

    def test_facts_section_appears(self):
        # Property 3
        facts = [_make_fact(1, "User prefers Python", 0.60)]
        ctx = _build_reflection_context(**_base_context_kwargs(), semantic_facts=facts)
        assert "KNOWN USER FACTS" in ctx
        assert "User prefers Python" in ctx

    def test_top_5_selected_from_more(self):
        # Property 4 — 7 facts provided → only top 5 by confidence appear
        facts = [
            _make_fact(1, f"Fact-{i}", confidence=round(0.10 * i, 2))
            for i in range(1, 8)
        ]
        ctx = _build_reflection_context(**_base_context_kwargs(), semantic_facts=facts)
        # Top 5 by confidence: Fact-7 (0.70), Fact-6 (0.60), Fact-5 (0.50), Fact-4 (0.40), Fact-3 (0.30)
        # Bottom 2: Fact-2 (0.20), Fact-1 (0.10) should NOT appear
        assert "Fact-7" in ctx
        assert "Fact-6" in ctx
        assert "Fact-5" in ctx
        assert "Fact-4" in ctx
        assert "Fact-3" in ctx
        assert "Fact-2" not in ctx
        assert "Fact-1" not in ctx

    def test_facts_sorted_by_confidence_desc(self):
        # Property 5 — higher confidence appears before lower in context string
        facts = [
            _make_fact(1, "Low confidence fact", 0.30),
            _make_fact(1, "High confidence fact", 0.75),
        ]
        ctx = _build_reflection_context(**_base_context_kwargs(), semantic_facts=facts)
        idx_high = ctx.index("High confidence fact")
        idx_low = ctx.index("Low confidence fact")
        assert idx_high < idx_low

    def test_proposition_text_verbatim(self):
        # Property 6
        prop = "User primarily uses async Python frameworks for web projects"
        facts = [_make_fact(1, prop, 0.65)]
        ctx = _build_reflection_context(**_base_context_kwargs(), semantic_facts=facts)
        assert prop in ctx


# ---------------------------------------------------------------------------
# 7–10: run_reflection integration
# ---------------------------------------------------------------------------

class TestRunReflectionWithSemanticFacts:

    def _mock_reflection_result(self) -> ReflectionResult:
        return ReflectionResult(
            success_estimate=0.80,
            memory_candidates=[],
            belief_updates=[],
            relationship_evidence=[],
            goal_updates=[],
            self_model_updates=[],
            user_belief_updates=[],
        )

    def test_none_facts_backward_compat(self, db_session):
        # Property 7 — semantic_facts=None works same as Fase 6
        perception = _make_perception()
        appraisal = _make_appraisal()

        with patch("app.cognition.reflection._call_reflection_haiku",
                   return_value=self._mock_reflection_result()):
            result = run_reflection(
                db_session,
                user_id=9901,
                user_message="test",
                perception=perception,
                appraisal=appraisal,
                decision=None,
                salience_total=0.55,
                trace_id="t-none",
                semantic_facts=None,
            )
        assert result is not None
        assert result.success_estimate == pytest.approx(0.80)

    def test_empty_list_backward_compat(self, db_session):
        # Property 8
        perception = _make_perception()
        appraisal = _make_appraisal()

        with patch("app.cognition.reflection._call_reflection_haiku",
                   return_value=self._mock_reflection_result()):
            result = run_reflection(
                db_session,
                user_id=9902,
                user_message="test",
                perception=perception,
                appraisal=appraisal,
                decision=None,
                salience_total=0.55,
                trace_id="t-empty",
                semantic_facts=[],
            )
        assert result is not None

    def test_fact_appears_in_haiku_context(self, db_session):
        # Property 9 — the proposition appears in the context string passed to Haiku
        perception = _make_perception()
        appraisal = _make_appraisal()
        fact = _make_fact(9903, "User always tests before shipping", 0.70)

        captured_context: list[str] = []

        def mock_haiku(context, *, trace_id):
            captured_context.append(context)
            return self._mock_reflection_result()

        with patch("app.cognition.reflection._call_reflection_haiku", side_effect=mock_haiku):
            run_reflection(
                db_session,
                user_id=9903,
                user_message="test",
                perception=perception,
                appraisal=appraisal,
                decision=None,
                salience_total=0.55,
                trace_id="t-fact",
                semantic_facts=[fact],
            )

        assert len(captured_context) == 1
        assert "User always tests before shipping" in captured_context[0]
        assert "KNOWN USER FACTS" in captured_context[0]

    def test_result_returned_with_facts(self, db_session):
        # Property 10
        perception = _make_perception()
        appraisal = _make_appraisal()
        facts = [_make_fact(9904, "User likes minimal code", 0.60)]

        with patch("app.cognition.reflection._call_reflection_haiku",
                   return_value=self._mock_reflection_result()):
            result = run_reflection(
                db_session,
                user_id=9904,
                user_message="test",
                perception=perception,
                appraisal=appraisal,
                decision=None,
                salience_total=0.55,
                trace_id="t-result",
                semantic_facts=facts,
            )
        assert result is not None
        assert result.log_id is not None

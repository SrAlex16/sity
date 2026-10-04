"""Tests for MINI-REMAKE v3.0 — Memory Worthiness pipeline.

Properties verified:

evaluate_memory_worthiness (pure):
1.  "Odio el café" props → MW >= gate → persisted=True (CONSOLIDATE/REINFORCE)
2.  "Hoy estoy cansado" props → MW < gate → IGNORED → persisted=False
3.  "Mi perro se llama Toby" props → MW >= gate → CONSOLIDATE → persisted=True
4.  "No me gusta el café de este sitio" → high context_dependency → MW penalizada < gate

process_mw_pipeline (DB integration):
5.  "Ya sabes que odio el café" + existing fact dislikes_coffee → MATCH → REINFORCE
6.  "Prefiero el té" + existing fact dislikes_coffee, resolver=RELATED, conf>=0.60 → CONSOLIDATE+link
7.  "Últimamente le estoy pillando el gusto al café" + existing fact → CONTRADICT → REVISE
8.  Multi-prop: coffee+tired+dog → three independent MemoryResult, two persisted

build_memory_expression_block (pure):
9.  memory_any_persisted=False → block says no promises
10. memory_any_persisted=True, CONSOLIDATE → block instructs Expression it can confirm
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.cognition.memory_worthiness import (
    MW_GATE,
    build_memory_expression_block,
    evaluate_memory_worthiness,
    process_mw_pipeline,
)
from app.cognition.semantic_proposition import (
    MemoryOperation,
    MemoryResult,
    SemanticProperties,
    SemanticProposition,
)
from app.cognition.semantic_resolver import SemanticResolution
from app.memory.models import SemanticFact


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _props(
    personal_relevance: float = 0.90,
    temporal_scope: str = "habitual",
    context_dependency: float = 0.05,
    assertion_strength: float = 0.90,
    expected_duration: float = 0.85,
    behavioral_relevance: float = 0.75,
) -> SemanticProperties:
    return SemanticProperties(
        personal_relevance=personal_relevance,
        temporal_scope=temporal_scope,
        context_dependency=context_dependency,
        assertion_strength=assertion_strength,
        expected_duration=expected_duration,
        behavioral_relevance=behavioral_relevance,
    )


def _prop(pid: str, content: str, **kw) -> SemanticProposition:
    return SemanticProposition(id=pid, content=content, properties=_props(**kw))


def _new_resolution() -> SemanticResolution:
    return SemanticResolution(relation="new", target_id=None, confidence=0.90, reason="no existing")


def _resolution(relation: str, target_id=None, confidence: float = 0.85) -> SemanticResolution:
    return SemanticResolution(relation=relation, target_id=target_id, confidence=confidence, reason="test")


def _create_fact(session: Session, user_id: int, proposition: str) -> SemanticFact:
    fact = SemanticFact(
        user_id=user_id,
        proposition=proposition,
        confidence=0.50,
        is_active=True,
        candidate=False,
        inference_type="explicit",
        source="test",
        reinforcement_count=1,
        contradiction_count=0,
        evidence_trail_json=json.dumps([]),
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


# ---------------------------------------------------------------------------
# 1-4: evaluate_memory_worthiness — pure
# ---------------------------------------------------------------------------

class TestEvaluateMemoryWorthiness:

    def test_coffee_dislike_above_gate(self):
        # High-quality proposition: personal, habitual, low context dependency
        p = _prop("p1", "User dislikes coffee")
        mw_base, mw_effective = evaluate_memory_worthiness(p)
        assert mw_effective >= MW_GATE, f"mw_effective={mw_effective:.3f} should be >= {MW_GATE}"

    def test_tired_today_below_gate(self):
        # Transient state — low expected_duration + behavioral_relevance
        p = SemanticProposition(
            id="p1",
            content="User is tired today",
            properties=SemanticProperties(
                personal_relevance=0.80,
                temporal_scope="transient",
                context_dependency=0.20,
                assertion_strength=0.70,
                expected_duration=0.05,
                behavioral_relevance=0.10,
            ),
        )
        mw_base, mw_effective = evaluate_memory_worthiness(p)
        assert mw_effective < MW_GATE, f"mw_effective={mw_effective:.3f} should be < {MW_GATE}"

    def test_dog_name_above_gate(self):
        # Persistent personal fact
        p = SemanticProposition(
            id="p1",
            content="User's dog is named Toby",
            properties=SemanticProperties(
                personal_relevance=0.85,
                temporal_scope="persistent",
                context_dependency=0.05,
                assertion_strength=0.95,
                expected_duration=0.90,
                behavioral_relevance=0.60,
            ),
        )
        mw_base, mw_effective = evaluate_memory_worthiness(p)
        assert mw_effective >= MW_GATE

    def test_context_dependent_coffee_penalized(self):
        # "No me gusta el café de este sitio" — high context_dependency penalizes MW
        p = SemanticProposition(
            id="p1",
            content="User dislikes coffee at this place",
            properties=SemanticProperties(
                personal_relevance=0.80,
                temporal_scope="situational",
                context_dependency=0.85,  # highly context-specific
                assertion_strength=0.80,
                expected_duration=0.40,
                behavioral_relevance=0.50,
            ),
        )
        mw_base, mw_effective = evaluate_memory_worthiness(p)
        # High context_dependency applies CONTEXT_PENALTY (0.50), cutting effective MW
        assert mw_effective < mw_base, "context_dependency should reduce MW_effective below MW_base"
        assert mw_effective < MW_GATE, f"penalized mw_effective={mw_effective:.3f} should be < gate"


# ---------------------------------------------------------------------------
# 5-8: process_mw_pipeline — DB integration
# ---------------------------------------------------------------------------

class TestProcessMwPipeline:

    def test_match_gives_reinforce(self, db_session: Session):
        existing = _create_fact(db_session, user_id=1, proposition="User dislikes coffee")
        prop = _prop("p1", "Ya sabes que odio el café")
        with patch(
            "app.cognition.memory_worthiness.resolve_candidate",
            return_value=_resolution("match", target_id=existing.id),
        ):
            results = process_mw_pipeline(db_session, user_id=1, propositions=[prop])
        assert len(results) == 1
        r = results[0]
        assert r.operation == MemoryOperation.REINFORCE
        assert r.persisted is True
        assert r.fact_id == str(existing.id)

    def test_related_high_confidence_consolidates_with_link(self, db_session: Session):
        existing = _create_fact(db_session, user_id=1, proposition="User dislikes coffee")
        prop = _prop("p1", "User prefers tea")
        with patch(
            "app.cognition.memory_worthiness.resolve_candidate",
            return_value=_resolution("related", target_id=existing.id, confidence=0.75),
        ):
            results = process_mw_pipeline(db_session, user_id=1, propositions=[prop])
        assert len(results) == 1
        r = results[0]
        assert r.operation == MemoryOperation.CONSOLIDATE
        assert r.persisted is True
        assert str(existing.id) in r.related_fact_ids

    def test_contradict_gives_revise(self, db_session: Session):
        existing = _create_fact(db_session, user_id=1, proposition="User dislikes coffee")
        prop = _prop("p1", "Últimamente le estoy pillando el gusto al café")
        with patch(
            "app.cognition.memory_worthiness.resolve_candidate",
            return_value=_resolution("contradict", target_id=existing.id),
        ):
            results = process_mw_pipeline(db_session, user_id=1, propositions=[prop])
        assert len(results) == 1
        r = results[0]
        assert r.operation == MemoryOperation.REVISE
        assert r.persisted is True

    def test_multi_proposition_independent_results(self, db_session: Session):
        coffee = _prop("p1", "User dislikes coffee")  # MW >= gate → persist
        tired = SemanticProposition(                    # MW < gate → ignore
            id="p2",
            content="User is tired today",
            properties=SemanticProperties(
                personal_relevance=0.70, temporal_scope="transient",
                context_dependency=0.20, assertion_strength=0.70,
                expected_duration=0.05, behavioral_relevance=0.10,
            ),
        )
        dog = SemanticProposition(                      # MW >= gate → persist
            id="p3",
            content="User's dog is named Toby",
            properties=SemanticProperties(
                personal_relevance=0.85, temporal_scope="persistent",
                context_dependency=0.05, assertion_strength=0.95,
                expected_duration=0.90, behavioral_relevance=0.60,
            ),
        )
        with patch(
            "app.cognition.memory_worthiness.resolve_candidate",
            return_value=_new_resolution(),
        ):
            results = process_mw_pipeline(
                db_session, user_id=1, propositions=[coffee, tired, dog],
            )
        assert len(results) == 3
        assert results[0].operation == MemoryOperation.CONSOLIDATE
        assert results[0].persisted is True
        assert results[1].operation == MemoryOperation.IGNORED
        assert results[1].persisted is False
        assert results[2].operation == MemoryOperation.CONSOLIDATE
        assert results[2].persisted is True


# ---------------------------------------------------------------------------
# 9-10: build_memory_expression_block — pure
# ---------------------------------------------------------------------------

class TestBuildMemoryExpressionBlock:

    def test_no_persisted_says_no_promise(self):
        results = [
            MemoryResult(proposition_id="p1", operation=MemoryOperation.IGNORED,
                         persisted=False, fact_id=None),
        ]
        block = build_memory_expression_block(results)
        assert block, "Should return a non-empty block"
        assert "No" in block or "no" in block
        assert "prometas" in block or "prometer" in block or "guardar" in block

    def test_consolidate_persisted_allows_confirmation(self):
        results = [
            MemoryResult(proposition_id="p1", operation=MemoryOperation.CONSOLIDATE,
                         persisted=True, fact_id="42"),
        ]
        block = build_memory_expression_block(results)
        assert "[MEMORIA ESTE TURNO]" in block
        assert "cuenta" in block or "Puedes" in block

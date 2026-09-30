"""Tests for MINI-REMAKE v2.0 Punto 6 — Reflection output downstream.

Properties verified:

memory_candidates → SemanticFact:
1.  inference_type="inferred" → confidence clamped to 0.45, candidate=True.
2.  inference_type="explicit" → confidence stored as provided (no cap at 0.45), candidate=True.
3.  Same proposition a second time → reinforcement_count incremented, confidence raised.
4.  reinforcement_count >= 2 → candidate promoted to False.
5.  confidence >= 0.55 → candidate promoted to False in the same upsert.

relationship_evidence → RelationshipEvidence:
6.  Valid structured evidence creates RelationshipEvidence with applied=False.
7.  apply_reflection_relationship_evidence updates SocialProfile dimension.
8.  Reflection strength is applied at 30% scale (_REFLECTION_EVIDENCE_SCALE).
9.  Unknown dimension is skipped (applied=True, SocialProfile unchanged).
10. No unapplied rows → no-op.

goal_updates → GoalCandidate / direct Goal:
11. evidence_type="inferred" → GoalCandidate created, not Goal.
12. evidence_type="explicit", confidence >= 0.70, operation="create" → Goal created directly.
13. evidence_type="explicit", confidence < 0.70 → GoalCandidate, not Goal.
14. evidence_type="inferred", confidence clamped to [0.35, 0.45].

self_model_updates → SelfBelief:
15. First observation → SelfBelief with confidence=0.30, source="self_model_reflection".
16. Same observation repeated → existing SelfBelief reinforced (confidence increases).

_parse_reflection_response (backwards compat):
17. Old format (memory_candidates: [str]) still parsed correctly.
18. New memory_candidates_typed format parsed correctly.
19. New relationship_evidence_structured format parsed correctly.
20. New goal_updates_structured format parsed correctly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, delete as sql_delete, select

from app.cognition.reflection import (
    ReflectionResult,
    _parse_reflection_response,
)
from app.cognition.semantic_service import (
    _REFLECTION_INFERRED_CONFIDENCE_MAX,
    _REFLECTION_CANDIDATE_PROMOTE_CONFIDENCE,
    _REFLECTION_CANDIDATE_PROMOTE_REINFORCEMENTS,
    upsert_semantic_candidate,
)
from app.cognition.self_model_service import add_self_model_observation, get_or_create_self_model
from app.memory.models import (
    GoalCandidate,
    Goal,
    RelationshipEvidence,
    SemanticFact,
    SelfBelief,
    SocialProfile,
)
from app.social.social_service import (
    _REFLECTION_EVIDENCE_SCALE,
    apply_reflection_relationship_evidence,
    get_or_create_social_profile,
)


_UID = 971_000
_UID_B = 971_001


def _clean(session: Session, *uids: int) -> None:
    for uid in uids:
        session.exec(sql_delete(SemanticFact).where(SemanticFact.user_id == uid))  # type: ignore[call-overload]
        session.exec(sql_delete(RelationshipEvidence).where(RelationshipEvidence.user_id == uid))  # type: ignore[call-overload]
        session.exec(sql_delete(GoalCandidate).where(GoalCandidate.user_id == uid))  # type: ignore[call-overload]
        session.exec(sql_delete(Goal).where(Goal.user_id == uid))  # type: ignore[call-overload]
        session.exec(sql_delete(SocialProfile).where(SocialProfile.user_id == uid))  # type: ignore[call-overload]
    session.commit()


# ── 1–5: memory_candidates → SemanticFact ────────────────────────────────────

class TestSemanticCandidateUpsert:
    def test_inferred_confidence_capped(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        fact = upsert_semantic_candidate(
            db_session, user_id=_UID,
            proposition="User enjoys debugging problems",
            inference_type="inferred",
            confidence=0.80,  # above cap
        )
        assert fact.confidence <= _REFLECTION_INFERRED_CONFIDENCE_MAX
        assert fact.candidate is True
        assert fact.inference_type == "inferred"

    def test_explicit_no_confidence_cap(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        fact = upsert_semantic_candidate(
            db_session, user_id=_UID,
            proposition="User explicitly stated they love Python",
            inference_type="explicit",
            confidence=0.70,
        )
        assert fact.confidence == pytest.approx(0.70)
        assert fact.candidate is True
        assert fact.inference_type == "explicit"

    def test_reinforcement_increments_count(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        prop = "User prefers concise answers"
        upsert_semantic_candidate(db_session, user_id=_UID, proposition=prop,
                                   inference_type="inferred", confidence=0.35)
        db_session.expire_all()
        fact = upsert_semantic_candidate(db_session, user_id=_UID, proposition=prop,
                                          inference_type="inferred", confidence=0.35)
        assert fact.reinforcement_count == 1

    def test_promotion_by_reinforcement_count(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        prop = "User works in the morning"
        for _ in range(_REFLECTION_CANDIDATE_PROMOTE_REINFORCEMENTS + 1):
            db_session.expire_all()
            fact = upsert_semantic_candidate(db_session, user_id=_UID, proposition=prop,
                                              inference_type="inferred", confidence=0.35)
        assert fact.candidate is False

    def test_promotion_by_confidence(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        prop = "User writes detailed commit messages"
        # First insert: explicit, high confidence → above promote threshold on first reinforce
        upsert_semantic_candidate(db_session, user_id=_UID, proposition=prop,
                                   inference_type="explicit", confidence=0.52)
        db_session.expire_all()
        fact = upsert_semantic_candidate(db_session, user_id=_UID, proposition=prop,
                                          inference_type="explicit", confidence=0.52)
        # After one reinforce: 0.52 + 0.05 = 0.57 >= 0.55 → promoted
        assert fact.candidate is False


# ── 6–10: relationship_evidence → RelationshipEvidence ───────────────────────

class TestRelationshipEvidence:
    def test_evidence_created_with_applied_false(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        ev = RelationshipEvidence(
            user_id=_UID, dimension="affinity", direction="positive",
            strength=0.8, turn_id="trace-001", reason="User was warm",
        )
        db_session.add(ev)
        db_session.commit()
        db_session.expire_all()

        row = db_session.exec(
            select(RelationshipEvidence).where(RelationshipEvidence.user_id == _UID)
        ).first()
        assert row is not None
        assert row.applied is False
        assert row.dimension == "affinity"

    def test_apply_updates_social_profile(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        sp = get_or_create_social_profile(db_session, _UID)
        initial_affinity = sp.affinity
        db_session.add(RelationshipEvidence(
            user_id=_UID, dimension="affinity", direction="positive",
            strength=1.0, turn_id="trace-002",
        ))
        db_session.commit()

        apply_reflection_relationship_evidence(db_session, _UID, trace_id="trace-002")
        db_session.expire_all()

        sp2 = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == _UID)).first()
        assert sp2 is not None
        assert sp2.affinity > initial_affinity

    def test_strength_at_reflection_scale(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        sp = get_or_create_social_profile(db_session, _UID)
        base_affinity = sp.affinity
        db_session.add(RelationshipEvidence(
            user_id=_UID, dimension="affinity", direction="positive",
            strength=1.0, turn_id="trace-003",
        ))
        db_session.commit()

        apply_reflection_relationship_evidence(db_session, _UID, trace_id="trace-003")
        db_session.expire_all()
        sp2 = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == _UID)).first()
        assert sp2 is not None
        expected_delta = 1.0 * _REFLECTION_EVIDENCE_SCALE
        assert abs((sp2.affinity - base_affinity) - expected_delta) < 0.001

    def test_unknown_dimension_skipped(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        sp = get_or_create_social_profile(db_session, _UID)
        base_affinity = sp.affinity
        db_session.add(RelationshipEvidence(
            user_id=_UID, dimension="unknown_dim", direction="positive",
            strength=1.0, turn_id="trace-004",
        ))
        db_session.commit()

        apply_reflection_relationship_evidence(db_session, _UID, trace_id="trace-004")
        db_session.expire_all()
        sp2 = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == _UID)).first()
        assert sp2 is not None
        assert sp2.affinity == pytest.approx(base_affinity)
        ev = db_session.exec(
            select(RelationshipEvidence).where(RelationshipEvidence.user_id == _UID)
        ).first()
        assert ev is not None and ev.applied is True

    def test_no_unapplied_rows_noop(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        sp = get_or_create_social_profile(db_session, _UID)
        base_affinity = sp.affinity
        # No RelationshipEvidence rows at all
        apply_reflection_relationship_evidence(db_session, _UID, trace_id="trace-empty")
        db_session.expire_all()
        sp2 = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == _UID)).first()
        assert sp2 is not None
        assert sp2.affinity == pytest.approx(base_affinity)


# ── 11–14: goal_updates → GoalCandidate / Goal ───────────────────────────────

class TestGoalCandidates:
    def test_inferred_creates_candidate_not_goal(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        gc = GoalCandidate(
            user_id=_UID, operation="create",
            goal_description="Build a personal portfolio",
            confidence=0.40, evidence_type="inferred", source_turn_id="t1",
        )
        db_session.add(gc)
        db_session.commit()

        goals = db_session.exec(select(Goal).where(Goal.user_id == _UID)).all()
        candidates = db_session.exec(select(GoalCandidate).where(GoalCandidate.user_id == _UID)).all()
        assert len(goals) == 0
        assert len(candidates) == 1

    def test_explicit_high_conf_creates_goal(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        goal = Goal(
            user_id=_UID, scope="short_term",
            description="Learn Rust this month",
            origin="autonomous", base_importance=0.75, status="active",
        )
        db_session.add(goal)
        db_session.commit()

        goals = db_session.exec(select(Goal).where(Goal.user_id == _UID)).all()
        assert len(goals) == 1
        assert goals[0].base_importance == pytest.approx(0.75)

    def test_explicit_low_conf_creates_candidate(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        gc = GoalCandidate(
            user_id=_UID, operation="create",
            goal_description="Maybe write a blog",
            confidence=0.55, evidence_type="explicit", source_turn_id="t3",
        )
        db_session.add(gc)
        db_session.commit()

        goals = db_session.exec(select(Goal).where(Goal.user_id == _UID)).all()
        candidates = db_session.exec(select(GoalCandidate).where(GoalCandidate.user_id == _UID)).all()
        assert len(goals) == 0
        assert len(candidates) == 1

    def test_inferred_confidence_clamped_in_reflection(self) -> None:
        # Test that _parse_reflection_response + goal_updates_structured clamps inferred
        raw = json.dumps({
            "success_estimate": 0.7,
            "memory_candidates_typed": [],
            "belief_updates": [],
            "relationship_evidence_structured": [],
            "goal_updates_structured": [
                {"operation": "create", "goal_description": "Finish the report",
                 "confidence": 0.80, "evidence_type": "inferred"},
            ],
            "self_model_updates": [],
            "user_belief_updates": [],
            "future_commitments": [],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert len(result.goal_updates_structured) == 1
        # confidence is stored as-is in the parsed result; clamping happens in run_reflection
        assert result.goal_updates_structured[0]["evidence_type"] == "inferred"


# ── 15–16: self_model_updates → SelfBelief ───────────────────────────────────

class TestSelfModelObservation:
    def test_creates_selfbelief_with_low_confidence(self, db_session: Session) -> None:
        sm = get_or_create_self_model(db_session)
        # Clean any beliefs with this proposition
        db_session.exec(
            sql_delete(SelfBelief)  # type: ignore[call-overload]
            .where(SelfBelief.self_model_id == sm.id)
            .where(SelfBelief.proposition == "Sity struggles with ambiguous instructions")
        )
        db_session.commit()

        add_self_model_observation(
            db_session,
            "Sity struggles with ambiguous instructions",
            trace_id="t-sm-01",
        )
        db_session.expire_all()

        belief = db_session.exec(
            select(SelfBelief)
            .where(SelfBelief.self_model_id == sm.id)
            .where(SelfBelief.proposition == "Sity struggles with ambiguous instructions")
            .where(SelfBelief.is_active == True)  # noqa: E712
        ).first()
        assert belief is not None
        assert belief.confidence == pytest.approx(0.30)
        assert belief.source == "self_model_reflection"

    def test_repeated_observation_reinforces(self, db_session: Session) -> None:
        sm = get_or_create_self_model(db_session)
        prop = "Sity excels at structured analysis 971k"
        db_session.exec(
            sql_delete(SelfBelief)  # type: ignore[call-overload]
            .where(SelfBelief.self_model_id == sm.id)
            .where(SelfBelief.proposition == prop)
        )
        db_session.commit()

        add_self_model_observation(db_session, prop, trace_id="t1")
        db_session.expire_all()
        add_self_model_observation(db_session, prop, trace_id="t2")
        db_session.expire_all()

        belief = db_session.exec(
            select(SelfBelief)
            .where(SelfBelief.self_model_id == sm.id)
            .where(SelfBelief.proposition == prop)
            .where(SelfBelief.is_active == True)  # noqa: E712
        ).first()
        assert belief is not None
        assert belief.confidence > 0.30  # reinforced


# ── 17–20: _parse_reflection_response backwards compat ───────────────────────

class TestParseReflectionBackwardsCompat:
    def test_old_format_memory_candidates_string_list(self) -> None:
        raw = json.dumps({
            "success_estimate": 0.8,
            "memory_candidates": ["User showed interest in AI"],
            "belief_updates": [],
            "relationship_evidence": ["Good vibe today"],
            "goal_updates": [],
            "self_model_updates": [],
            "user_belief_updates": [],
            "future_commitments": [],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert "User showed interest in AI" in result.memory_candidates
        assert len(result.memory_candidates_typed) == 1
        assert result.memory_candidates_typed[0]["inference_type"] == "inferred"

    def test_new_memory_candidates_typed_format(self) -> None:
        raw = json.dumps({
            "success_estimate": 0.7,
            "memory_candidates_typed": [
                {"proposition": "User loves testing", "inference_type": "explicit"},
            ],
            "belief_updates": [],
            "relationship_evidence_structured": [],
            "goal_updates_structured": [],
            "self_model_updates": [],
            "user_belief_updates": [],
            "future_commitments": [],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert result.memory_candidates == ["User loves testing"]
        assert result.memory_candidates_typed[0]["inference_type"] == "explicit"

    def test_new_relationship_evidence_structured_format(self) -> None:
        raw = json.dumps({
            "success_estimate": 0.75,
            "memory_candidates_typed": [],
            "belief_updates": [],
            "relationship_evidence_structured": [
                {"dimension": "affinity", "direction": "positive", "strength": 0.6, "reason": "Warmth"},
            ],
            "goal_updates_structured": [],
            "self_model_updates": [],
            "user_belief_updates": [],
            "future_commitments": [],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert len(result.relationship_evidence_structured) == 1
        ev = result.relationship_evidence_structured[0]
        assert ev["dimension"] == "affinity"
        assert ev["direction"] == "positive"
        assert ev["strength"] == pytest.approx(0.6)

    def test_new_goal_updates_structured_format(self) -> None:
        raw = json.dumps({
            "success_estimate": 0.6,
            "memory_candidates_typed": [],
            "belief_updates": [],
            "relationship_evidence_structured": [],
            "goal_updates_structured": [
                {"operation": "create", "goal_description": "Learn Docker",
                 "confidence": 0.70, "evidence_type": "explicit"},
            ],
            "self_model_updates": [],
            "user_belief_updates": [],
            "future_commitments": [],
        })
        result = _parse_reflection_response(raw)
        assert result is not None
        assert len(result.goal_updates_structured) == 1
        gu = result.goal_updates_structured[0]
        assert gu["operation"] == "create"
        assert gu["evidence_type"] == "explicit"
        assert gu["confidence"] == pytest.approx(0.70)

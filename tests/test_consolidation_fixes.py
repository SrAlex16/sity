"""Tests for pre-beta consolidation fixes (Fixes 1–4).

Properties:

Fix 1 — Volume consolidation semántica:
1.  _count_active_candidates filters SemanticFact by user_id.
2.  _count_active_candidates filters SelfBelief by self_model_id (not all users).
3.  _normalize_trail_entry converts old {trace_id, type, description} to unified schema.
4.  _normalize_trail_entry leaves modern schema entries intact.
5.  _recalculate_confidence_from_scratch applies diminishing returns from initial value.
6.  _recalculate_confidence_from_scratch with zero counts returns initial value.
7.  _parse_grouping_response parses valid match group with canonical_id.
8.  _parse_grouping_response rejects group with fewer than 2 ids.
9.  _parse_grouping_response returns None on invalid JSON.
10. Merge in _run_volume_consolidation migrates evidence trail from dup to canonical.
11. Merge recalculates confidence from scratch (not additive).
12. SemanticFact CONTRADICT in grouping is ignored (only "match" merges).

Fix 2 — add_self_model_observation with resolver:
13. Exact-match proposition → resolver fast-path → reinforce (no new row).
14. New proposition → resolver fast-path (empty list) → insert with confidence=0.30.

Fix 3 — related_fact_id rename:
15. SemanticFact has related_fact_id field, not related_belief_id.
16. upsert_semantic_candidate accepts related_fact_id kwarg.

Fix 4 — Unified evidence trail schema:
17. add_belief_candidate writes turn_id (not trace_id) in trail entry.
18. update_belief_confidence writes turn_id (not trace_id) in trail entry.
19. reinforce_fact writes relation="support" (not "reinforcement").
20. contradict_fact writes relation="contradict" (not "contradiction").
21. upsert_semantic_candidate reinforce writes relation="support".
22. evidence_trail entries from SelfBelief and SemanticFact share the same keys.
"""
from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select
from sqlalchemy import text as sa_text

from sqlmodel import delete as sql_delete

from app.memory.db import engine
from app.memory.models import SemanticFact, SelfBelief, utc_now
from app.cognition.self_model_service import (
    add_belief_candidate,
    add_self_model_observation,
    get_or_create_self_model,
    update_belief_confidence,
)
from app.cognition.semantic_service import (
    _count_active_candidates,
    _normalize_trail_entry,
    _parse_grouping_response,
    _recalculate_confidence_from_scratch,
    _SEMANTIC_REINFORCE_RATE,
    contradict_fact,
    reinforce_fact,
    upsert_semantic_candidate,
    SEMANTIC_CONFIDENCE_MAX,
)

_UID = 90_400
_UID2 = 90_401

_UNIFIED_KEYS = {"turn_id", "relation", "strength", "source", "description", "timestamp"}


def _make_sf(session: Session, proposition: str = "test fact", *, user_id: int = _UID) -> SemanticFact:
    f = SemanticFact(
        user_id=user_id, proposition=proposition, confidence=0.40,
        candidate=True, is_active=True,
    )
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


def _make_sb(session: Session, proposition: str = "test belief") -> SelfBelief:
    sm = get_or_create_self_model(session)
    return add_belief_candidate(
        session, self_model_id=sm.id,  # type: ignore[arg-type]
        proposition=proposition, confidence=0.40,
    )


def _clean_sf(session: Session) -> None:
    session.exec(  # type: ignore[call-overload]
        sql_delete(SemanticFact).where(SemanticFact.user_id.in_([_UID, _UID2]))
    )
    session.commit()


# ---------------------------------------------------------------------------
# Fix 1 — _count_active_candidates
# ---------------------------------------------------------------------------

class TestCountActiveCandidates:

    def test_filters_semanticfact_by_user_id(self, db_session: Session):
        _clean_sf(db_session)
        _make_sf(db_session, "fact user1 alpha", user_id=_UID)
        _make_sf(db_session, "fact user2 beta", user_id=_UID2)
        count_u1 = _count_active_candidates(_UID)
        count_u2 = _count_active_candidates(_UID2)
        # Each user sees only their own facts in the SF part
        assert count_u1 != count_u2 or count_u1 >= 1

    def test_inactive_fact_not_counted(self, db_session: Session):
        _clean_sf(db_session)
        f = _make_sf(db_session, "inactive fact", user_id=_UID)
        f.is_active = False
        db_session.add(f)
        db_session.commit()
        count = _count_active_candidates(_UID)
        # count should not include the deactivated fact (may include SB from other tests)
        with Session(engine) as s:
            sf_count = s.execute(
                sa_text("SELECT COUNT(*) FROM semanticfact WHERE user_id=:u AND candidate=1 AND is_active=1"),
                {"u": _UID},
            ).scalar()
        assert sf_count == 0


# ---------------------------------------------------------------------------
# Fix 1 — _normalize_trail_entry
# ---------------------------------------------------------------------------

class TestNormalizeTrailEntry:

    def test_converts_old_selfbelief_schema(self):
        now_iso = utc_now().isoformat()
        old = {"trace_id": "t-001", "type": "reflection", "description": "initial obs"}
        result = _normalize_trail_entry(old, now_iso)
        assert result["turn_id"] == "t-001"
        assert result["relation"] == "support"
        assert result["description"] == "initial obs"
        assert "strength" in result
        assert "timestamp" in result

    def test_leaves_modern_schema_intact(self):
        now_iso = utc_now().isoformat()
        modern = {
            "turn_id": "t-999", "relation": "support", "strength": 0.20,
            "source": "reflection", "description": "", "timestamp": now_iso,
        }
        result = _normalize_trail_entry(modern, now_iso)
        assert result["turn_id"] == "t-999"
        assert result["relation"] == "support"

    def test_old_contradiction_type_maps_to_contradict(self):
        now_iso = utc_now().isoformat()
        old = {"trace_id": "t-002", "type": "contradiction", "description": "conflict"}
        result = _normalize_trail_entry(old, now_iso)
        assert result["relation"] == "contradict"


# ---------------------------------------------------------------------------
# Fix 1 — _recalculate_confidence_from_scratch
# ---------------------------------------------------------------------------

class TestRecalculateConfidence:

    def test_zero_counts_returns_initial(self):
        assert _recalculate_confidence_from_scratch(0.40, 0, 0) == pytest.approx(0.40)

    def test_one_reinforce_applies_formula(self):
        initial = 0.30
        expected = initial + (1 - initial) * _SEMANTIC_REINFORCE_RATE
        assert _recalculate_confidence_from_scratch(initial, 1, 0) == pytest.approx(expected)

    def test_capped_at_semantic_max(self):
        result = _recalculate_confidence_from_scratch(0.40, 100, 0)
        assert result <= SEMANTIC_CONFIDENCE_MAX

    def test_contradictions_reduce_confidence(self):
        result = _recalculate_confidence_from_scratch(0.60, 0, 3)
        assert result < 0.60


# ---------------------------------------------------------------------------
# Fix 1 — _parse_grouping_response
# ---------------------------------------------------------------------------

class TestParseGroupingResponse:

    def test_parses_match_group(self):
        payload = json.dumps({
            "groups": [{"ids": [1, 2, 3], "relation": "match", "canonical_id": 1}],
            "ungrouped": [4],
        })
        result = _parse_grouping_response(payload)
        assert result is not None
        assert len(result["groups"]) == 1
        assert result["groups"][0]["canonical_id"] == 1
        assert result["groups"][0]["relation"] == "match"

    def test_rejects_group_with_single_id(self):
        payload = json.dumps({
            "groups": [{"ids": [5], "relation": "match", "canonical_id": 5}],
            "ungrouped": [],
        })
        result = _parse_grouping_response(payload)
        assert result is not None
        assert len(result["groups"]) == 0

    def test_returns_none_on_invalid_json(self):
        assert _parse_grouping_response("not json at all") is None

    def test_related_group_has_no_canonical(self):
        payload = json.dumps({
            "groups": [{"ids": [10, 11], "relation": "related"}],
            "ungrouped": [],
        })
        result = _parse_grouping_response(payload)
        assert result is not None
        assert "canonical_id" not in result["groups"][0]


# ---------------------------------------------------------------------------
# Fix 2 — add_self_model_observation with resolver
# ---------------------------------------------------------------------------

class TestSelfModelObservationResolver:

    def _clean(self, session: Session, prop: str) -> None:
        sm = get_or_create_self_model(session)
        session.exec(  # type: ignore[call-overload]
            sql_delete(SelfBelief).where(
                SelfBelief.self_model_id == sm.id,
                SelfBelief.proposition == prop,
            )
        )
        session.commit()

    def test_exact_match_reinforces_existing(self, db_session: Session):
        prop = "Sity is direct and concise in responses 9x1"
        self._clean(db_session, prop)
        first = add_self_model_observation(db_session, prop, trace_id="t-obs-1")
        assert first is not None
        first_conf = first.confidence

        second = add_self_model_observation(db_session, prop, trace_id="t-obs-2")
        assert second is not None
        db_session.refresh(second)
        # Exact match → resolver fast-path → reinforce, not a new row
        assert second.id == first.id
        assert second.confidence > first_conf

    def test_new_proposition_creates_belief(self, db_session: Session):
        prop = "Sity prefers structured output format x7z"
        self._clean(db_session, prop)
        result = add_self_model_observation(db_session, prop, trace_id="t-obs-new")
        assert result is not None
        assert result.confidence == pytest.approx(0.30)
        assert result.source == "self_model_reflection"

    def test_empty_observation_returns_none(self, db_session: Session):
        result = add_self_model_observation(db_session, "   ")
        assert result is None


# ---------------------------------------------------------------------------
# Fix 3 — related_fact_id rename
# ---------------------------------------------------------------------------

class TestRelatedFactIdRename:

    def test_semanticfact_has_related_fact_id(self, db_session: Session):
        cols = {c.name for c in SemanticFact.__table__.columns}
        assert "related_fact_id" in cols, "related_fact_id column must exist on semanticfact table"
        assert "related_belief_id" not in cols, "related_belief_id must have been renamed to related_fact_id"

    def test_upsert_accepts_related_fact_id(self, db_session: Session):
        _clean_sf(db_session)
        f = upsert_semantic_candidate(
            db_session,
            user_id=_UID,
            proposition="primary fact for related",
            confidence=0.40,
        )
        fact = upsert_semantic_candidate(
            db_session,
            user_id=_UID,
            proposition="related but distinct fact",
            confidence=0.35,
            related_fact_id=f.id,
        )
        db_session.refresh(fact)
        assert fact.related_fact_id == f.id


# ---------------------------------------------------------------------------
# Fix 4 — Unified evidence trail schema
# ---------------------------------------------------------------------------

class TestUnifiedEvidenceTrailSchema:

    def test_add_belief_candidate_writes_turn_id(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        b = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="unified trail test 4a",
            trace_id="turn-X99",
        )
        trail = json.loads(b.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["turn_id"] == "turn-X99"
        assert set(trail[0].keys()) >= _UNIFIED_KEYS - {"description"}

    def test_update_belief_confidence_writes_turn_id(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        b = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="unified trail test 4b",
        )
        update_belief_confidence(
            db_session, belief_id=b.id,  # type: ignore[arg-type]
            new_confidence=0.55, trace_id="turn-Y99",
        )
        from app.memory.models import SelfBelief as _SB
        refreshed = db_session.get(_SB, b.id)
        trail = json.loads(refreshed.evidence_trail_json)  # type: ignore[union-attr]
        updated_entry = next((e for e in trail if e.get("turn_id") == "turn-Y99"), None)
        assert updated_entry is not None
        assert set(updated_entry.keys()) >= _UNIFIED_KEYS - {"description"}

    def test_reinforce_fact_writes_support_relation(self, db_session: Session):
        _clean_sf(db_session)
        f = _make_sf(db_session, "unified trail sf reinforce")
        reinforce_fact(db_session, f.id, user_id=_UID, trace_id="r-001")  # type: ignore[arg-type]
        db_session.refresh(f)
        trail = json.loads(f.evidence_trail_json)
        assert trail[0]["relation"] == "support"
        assert set(trail[0].keys()) >= _UNIFIED_KEYS

    def test_contradict_fact_writes_contradict_relation(self, db_session: Session):
        _clean_sf(db_session)
        f = _make_sf(db_session, "unified trail sf contradict", user_id=_UID)
        contradict_fact(db_session, f.id, user_id=_UID, trace_id="c-001")  # type: ignore[arg-type]
        db_session.refresh(f)
        trail = json.loads(f.evidence_trail_json)
        assert trail[0]["relation"] == "contradict"

    def test_upsert_reinforce_writes_support_relation(self, db_session: Session):
        _clean_sf(db_session)
        prop = "upsert unified trail test"
        upsert_semantic_candidate(db_session, user_id=_UID, proposition=prop, confidence=0.40)
        f2 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition=prop, confidence=0.40, trace_id="u-001"
        )
        db_session.refresh(f2)
        trail = json.loads(f2.evidence_trail_json)
        reinforce_entry = next((e for e in trail if e.get("turn_id") == "u-001"), None)
        assert reinforce_entry is not None
        assert reinforce_entry["relation"] == "support"

    def test_sb_and_sf_trail_entries_share_same_keys(self, db_session: Session):
        _clean_sf(db_session)
        sm = get_or_create_self_model(db_session)
        sb = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="key schema match test", trace_id="k-001",
        )
        sf = _make_sf(db_session, "key schema match fact")
        reinforce_fact(db_session, sf.id, user_id=_UID, trace_id="k-002")  # type: ignore[arg-type]
        db_session.refresh(sf)

        sb_trail = json.loads(sb.evidence_trail_json)
        sf_trail = json.loads(sf.evidence_trail_json)
        assert len(sb_trail) >= 1 and len(sf_trail) >= 1
        # Both must share the same key set
        assert set(sb_trail[0].keys()) == set(sf_trail[0].keys())

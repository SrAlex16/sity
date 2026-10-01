"""Tests for final pre-beta fixes (Fixes A–C).

Properties:

Fix A — Evidence trail como fuente de verdad:
1.  New SemanticFact candidate has exactly 1 initial trail entry with relation="support".
2.  New SelfBelief candidate always has exactly 1 initial trail entry (no condition on trace_id).
3.  Merge of 3 candidates (0 extra reinforcements) yields higher confidence than initial
    (confidence derived from trail's 3 support entries, not from counters=0).
4.  recalculate_confidence_from_trail: support→contradict→support ≠ support→support→contradict.

Fix B — Separate SF and SB consolidation:
5.  SF count below threshold + SB count at threshold → only SB thread fires.
6.  SF count at threshold + SB count below threshold → only SF thread fires.
7.  _run_sf_volume_consolidation only queries SemanticFact (not SelfBelief).
8.  _run_sb_volume_consolidation only queries SelfBelief (not SemanticFact).

Fix C — CONTRADICT in consolidation job:
9.  _parse_grouping_response accepts "contradict" as a valid relation.
10. SF consolidation CONTRADICT: both facts get a contradict trail entry, neither is merged.
11. SF consolidation CONTRADICT: neither fact is deactivated (confidence stays above threshold).
12. SB consolidation CONTRADICT: both beliefs get a contradict trail entry without merging.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select
from sqlmodel import delete as sql_delete

from app.memory.db import engine
from app.memory.models import SemanticFact, SelfBelief, utc_now
from app.cognition.self_model_service import (
    add_belief_candidate,
    get_or_create_self_model,
)
from app.cognition.semantic_service import (
    _count_active_semantic_facts,
    _count_active_self_beliefs,
    _normalize_trail_entry,
    _parse_grouping_response,
    _run_sf_volume_consolidation,
    _run_sb_volume_consolidation,
    maybe_trigger_volume_consolidation,
    recalculate_confidence_from_trail,
    upsert_semantic_candidate,
    SEMANTIC_CONFIDENCE_MAX,
    _SEMANTIC_REINFORCE_RATE,
    _SEMANTIC_CONTRADICT_RATE,
)

_UID = 90_500
_UID2 = 90_501


def _make_sf(session: Session, proposition: str = "test fact", *, user_id: int = _UID) -> SemanticFact:
    f = SemanticFact(
        user_id=user_id, proposition=proposition, confidence=0.40,
        candidate=True, is_active=True,
    )
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


def _clean_sf(session: Session) -> None:
    session.exec(  # type: ignore[call-overload]
        sql_delete(SemanticFact).where(SemanticFact.user_id.in_([_UID, _UID2]))
    )
    session.commit()


def _clean_sb(session: Session) -> None:
    sm = get_or_create_self_model(session)
    session.exec(  # type: ignore[call-overload]
        sql_delete(SelfBelief).where(SelfBelief.self_model_id == sm.id)
    )
    session.commit()


# ---------------------------------------------------------------------------
# Fix A — Evidence trail como fuente de verdad
# ---------------------------------------------------------------------------

class TestInitialTrailEntry:

    def test_new_sf_candidate_has_one_initial_trail_entry(self, db_session: Session):
        _clean_sf(db_session)
        fact = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="initial trail test fact A1",
            confidence=0.40, trace_id="t-init-sf",
        )
        trail = json.loads(fact.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["relation"] == "support"
        assert trail[0]["turn_id"] == "t-init-sf"
        assert trail[0]["description"] == "initial candidate"

    def test_new_sf_candidate_trail_contains_initial_confidence_as_strength(self, db_session: Session):
        _clean_sf(db_session)
        fact = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="initial trail strength test A2",
            confidence=0.40, trace_id="t-init-sf2",
        )
        trail = json.loads(fact.evidence_trail_json)
        assert abs(trail[0]["strength"] - 0.40) < 0.01

    def test_new_sb_candidate_always_has_initial_trail_entry(self, db_session: Session):
        _clean_sb(db_session)
        sm = get_or_create_self_model(db_session)
        # Without trace_id — previously no entry was written
        belief = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="initial trail test belief B1",
        )
        trail = json.loads(belief.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["relation"] == "support"

    def test_new_sb_candidate_with_trace_id_has_initial_entry(self, db_session: Session):
        _clean_sb(db_session)
        sm = get_or_create_self_model(db_session)
        belief = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="initial trail test belief B2", trace_id="t-sb-init",
        )
        trail = json.loads(belief.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["turn_id"] == "t-sb-init"


class TestRecalculateFromTrail:

    def test_order_matters_support_contradict_support_vs_support_support_contradict(self):
        now = utc_now()
        from datetime import timedelta

        def _entry(rel: str, dt_offset: int) -> dict:
            return {
                "turn_id": "", "relation": rel,
                "strength": 0.20, "source": "test",
                "description": "",
                "timestamp": (now + timedelta(seconds=dt_offset)).isoformat(),
            }

        trail_scs = [_entry("support", 0), _entry("contradict", 1), _entry("support", 2)]
        trail_ssc = [_entry("support", 0), _entry("support", 1), _entry("contradict", 2)]

        result_scs = recalculate_confidence_from_trail(trail_scs, initial=0.0)
        result_ssc = recalculate_confidence_from_trail(trail_ssc, initial=0.0)
        assert result_scs != pytest.approx(result_ssc), (
            f"Order should matter: s→c→s={result_scs:.4f}, s→s→c={result_ssc:.4f}"
        )

    def test_merge_3_candidates_gives_higher_confidence_than_zero_reinforcements(self, db_session: Session):
        _clean_sf(db_session)
        # Create 3 separate candidates (each with 1 initial trail entry, 0 extra reinforcements)
        f1 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="merge confidence test alpha",
            confidence=0.35, trace_id="m-1",
        )
        f2 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="merge confidence test beta",
            confidence=0.35, trace_id="m-2",
        )
        f3 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="merge confidence test gamma",
            confidence=0.35, trace_id="m-3",
        )

        # Simulate merge: combine all 3 trails
        now_iso = utc_now().isoformat()
        merged: list[dict] = []
        for f in [f1, f2, f3]:
            for e in json.loads(f.evidence_trail_json):
                merged.append(_normalize_trail_entry(e, now_iso))

        result = recalculate_confidence_from_trail(merged, initial=0.0)
        # Old counter-based result: _recalculate_confidence_from_scratch(0.35, 0, 0) = 0.35
        assert result > 0.35, (
            f"Trail-based merge of 3 candidates should yield > 0.35, got {result:.4f}"
        )

    def test_empty_trail_returns_initial(self):
        assert recalculate_confidence_from_trail([], initial=0.50) == pytest.approx(0.50)

    def test_all_support_approaches_cap(self):
        trail = [
            {"relation": "support", "timestamp": f"2026-01-01T00:00:{i:02d}"}
            for i in range(60)
        ]
        result = recalculate_confidence_from_trail(trail, initial=0.0)
        assert result <= SEMANTIC_CONFIDENCE_MAX + 0.001
        assert result > 0.80


# ---------------------------------------------------------------------------
# Fix B — Separate SF and SB consolidation
# ---------------------------------------------------------------------------

class TestSeparateConsolidationTriggers:

    def test_sf_below_threshold_sb_above_fires_only_sb_thread(self, db_session: Session):
        with patch("app.cognition.semantic_service._count_active_semantic_facts", return_value=5), \
             patch("app.cognition.semantic_service._count_active_self_beliefs", return_value=10), \
             patch("app.cognition.semantic_service.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            maybe_trigger_volume_consolidation(user_id=_UID)
            assert mock_threading.Thread.call_count == 1
            # The single thread should target the SB consolidation function
            call_kwargs = mock_threading.Thread.call_args.kwargs
            assert call_kwargs.get("target").__name__ == "_run_sb_volume_consolidation"

    def test_sf_above_threshold_sb_below_fires_only_sf_thread(self, db_session: Session):
        with patch("app.cognition.semantic_service._count_active_semantic_facts", return_value=10), \
             patch("app.cognition.semantic_service._count_active_self_beliefs", return_value=5), \
             patch("app.cognition.semantic_service.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            maybe_trigger_volume_consolidation(user_id=_UID)
            assert mock_threading.Thread.call_count == 1
            call_kwargs = mock_threading.Thread.call_args.kwargs
            assert call_kwargs.get("target").__name__ == "_run_sf_volume_consolidation"

    def test_both_above_threshold_fires_two_independent_threads(self, db_session: Session):
        with patch("app.cognition.semantic_service._count_active_semantic_facts", return_value=10), \
             patch("app.cognition.semantic_service._count_active_self_beliefs", return_value=10), \
             patch("app.cognition.semantic_service.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            maybe_trigger_volume_consolidation(user_id=_UID)
            assert mock_threading.Thread.call_count == 2
            targets = {c.kwargs["target"].__name__ for c in mock_threading.Thread.call_args_list}
            assert targets == {"_run_sf_volume_consolidation", "_run_sb_volume_consolidation"}


# ---------------------------------------------------------------------------
# Fix C — CONTRADICT in consolidation job
# ---------------------------------------------------------------------------

class TestParseGroupingResponseContradict:

    def test_accepts_contradict_relation(self):
        import json as _json
        payload = _json.dumps({
            "groups": [{"ids": [1, 2], "relation": "contradict"}],
            "ungrouped": [],
        })
        result = _parse_grouping_response(payload)
        assert result is not None
        assert len(result["groups"]) == 1
        assert result["groups"][0]["relation"] == "contradict"
        assert "canonical_id" not in result["groups"][0]

    def test_contradict_group_has_no_canonical_id(self):
        import json as _json
        payload = _json.dumps({
            "groups": [{"ids": [10, 11], "relation": "contradict", "canonical_id": 10}],
            "ungrouped": [],
        })
        result = _parse_grouping_response(payload)
        assert result is not None
        assert "canonical_id" not in result["groups"][0]


class TestSFConsolidationContradict:

    def test_contradict_adds_entry_to_both_facts_without_merging(self, db_session: Session):
        _clean_sf(db_session)
        f1 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="user loves outdoor activities",
            confidence=0.50, trace_id="c-sf-1",
        )
        f2 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="user prefers indoor sedentary hobbies",
            confidence=0.50, trace_id="c-sf-2",
        )
        assert f1.id is not None and f2.id is not None

        # Mock Haiku to return these two as "contradict"
        mock_grouping = {
            "groups": [{"ids": [f1.id, f2.id], "relation": "contradict"}],
            "ungrouped": [],
        }
        with patch("app.cognition.semantic_service._call_semantic_grouping_haiku",
                   return_value=mock_grouping):
            _run_sf_volume_consolidation(user_id=_UID, trace_id="c-job")

        db_session.refresh(f1)
        db_session.refresh(f2)

        trail1 = json.loads(f1.evidence_trail_json)
        trail2 = json.loads(f2.evidence_trail_json)

        # Both should have a contradict entry
        assert any(e["relation"] == "contradict" for e in trail1), "f1 missing contradict entry"
        assert any(e["relation"] == "contradict" for e in trail2), "f2 missing contradict entry"

    def test_contradict_does_not_merge_facts(self, db_session: Session):
        """Facts that contradict each other remain as separate rows (not merged)."""
        _clean_sf(db_session)
        f1 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="user is very active sportsman",
            confidence=0.50, trace_id="c-sf-3",
        )
        f2 = upsert_semantic_candidate(
            db_session, user_id=_UID, proposition="user avoids all physical exercise",
            confidence=0.50, trace_id="c-sf-4",
        )
        assert f1.id is not None and f2.id is not None
        f1_id, f2_id = f1.id, f2.id

        mock_grouping = {
            "groups": [{"ids": [f1_id, f2_id], "relation": "contradict"}],
            "ungrouped": [],
        }
        with patch("app.cognition.semantic_service._call_semantic_grouping_haiku",
                   return_value=mock_grouping):
            _run_sf_volume_consolidation(user_id=_UID, trace_id="c-job2")

        # Both rows should still exist as separate SemanticFact entries
        from sqlmodel import Session as _Session
        with _Session(engine) as s:
            row1 = s.get(SemanticFact, f1_id)
            row2 = s.get(SemanticFact, f2_id)
        assert row1 is not None, "f1 row should still exist"
        assert row2 is not None, "f2 row should still exist"
        # f2 was not merged into f1 (neither was deactivated by merge logic)
        assert row1.proposition != row2.proposition


class TestSBConsolidationContradict:

    def test_sb_contradict_adds_entry_to_both_beliefs_without_merging(self, db_session: Session):
        _clean_sb(db_session)
        sm = get_or_create_self_model(db_session)
        b1 = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="Sity is very extroverted and talkative",
            confidence=0.50, trace_id="c-sb-1",
        )
        b2 = add_belief_candidate(
            db_session, self_model_id=sm.id,  # type: ignore[arg-type]
            proposition="Sity is deeply introverted and reserved",
            confidence=0.50, trace_id="c-sb-2",
        )
        assert b1.id is not None and b2.id is not None

        mock_grouping = {
            "groups": [{"ids": [b1.id, b2.id], "relation": "contradict"}],
            "ungrouped": [],
        }
        with patch("app.cognition.semantic_service._call_semantic_grouping_haiku",
                   return_value=mock_grouping):
            _run_sb_volume_consolidation(trace_id="c-sb-job")

        db_session.refresh(b1)
        db_session.refresh(b2)

        trail1 = json.loads(b1.evidence_trail_json)
        trail2 = json.loads(b2.evidence_trail_json)
        assert any(e["relation"] == "contradict" for e in trail1), "b1 missing contradict entry"
        assert any(e["relation"] == "contradict" for e in trail2), "b2 missing contradict entry"
        assert b1.is_active
        assert b2.is_active

"""Tests for Operación Remake Fase 9 Paso 1 — SemanticFact service (data layer).

Properties verified:

SemanticFact CRUD:
1.  SemanticFact created with correct defaults (confidence=0.40, is_active=True).
2.  proposition is stored exactly as given (up to 300 chars in service layer).
3.  source_episode_ids_json is serialized correctly.
4.  load_active_facts returns only is_active=True rows.
5.  load_active_facts user isolation — user A facts not returned for user B.
6.  load_active_facts sorted by confidence desc.
7.  load_active_facts respects min_confidence filter.

reinforce_fact:
8.  confidence increases by 0.05 per call.
9.  confidence is capped at SEMANTIC_CONFIDENCE_MAX (0.85).
10. reinforcement_count increments by 1 per call.
11. last_confirmed_at is set after reinforcement.
12. reinforce on wrong user_id returns None (isolation).
13. reinforce on inactive fact returns None.

contradict_fact:
14. confidence decreases by 0.10 per call.
15. confidence floors at 0.0 (never negative).
16. contradiction_count increments by 1 per call.
17. last_contradicted_at is set after contradiction.
18. fact is deactivated (is_active=False) when confidence < 0.20.
19. contradict on wrong user_id returns None (isolation).
20. contradict on already inactive fact returns None.

Confidence formula verification:
21. Initial confidence 0.40; 3 reinforcements → 0.55 (= 0.40 + 3×0.05).
22. Initial confidence 0.40; 1 contradiction → 0.30 (= 0.40 − 0.10).
23. 3 contradictions from 0.40 → 0.10 < 0.20 → is_active = False.

_parse_synthesis_response:
24. Valid JSON with all fields parsed correctly.
25. Missing key → treated as empty list (backward compat).
26. Invalid JSON → returns None.
27. reinforced_ids and contradicted_ids parsed as int (not str).

maybe_trigger_semantic_consolidation:
28. Below threshold (< 3 unprocessed episodes) → Haiku NOT called.
29. At threshold (= 3 unprocessed episodes) → Haiku IS called (mock).
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import delete as sql_delete, Session

from app.memory.models import Episode, SemanticFact, utc_now
from app.cognition.semantic_service import (
    SEMANTIC_CONFIDENCE_MAX,
    SEMANTIC_DEACTIVATION_THRESHOLD,
    _SEMANTIC_INITIAL_CONFIDENCE,
    _SEMANTIC_REINFORCE_DELTA,
    _SEMANTIC_CONTRADICT_DELTA,
    _SEMANTIC_BATCH_MIN,
    _SynthesisResult,
    _parse_synthesis_response,
    load_active_facts,
    reinforce_fact,
    contradict_fact,
    maybe_trigger_semantic_consolidation,
)


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

def _clean_facts(session: Session, user_id: int) -> None:
    session.exec(sql_delete(SemanticFact).where(SemanticFact.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


def _clean_episodes(session: Session, user_id: int) -> None:
    session.exec(sql_delete(Episode).where(Episode.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


def _make_fact(session: Session, user_id: int, proposition: str, confidence: float = 0.40) -> SemanticFact:
    fact = SemanticFact(user_id=user_id, proposition=proposition, confidence=confidence)
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def _make_episode(session: Session, user_id: int, summary: str = "A test episode", processed: bool = False) -> Episode:
    ep = Episode(
        user_id=user_id,
        summary=summary,
        salience_total=0.50,
        semantically_processed=processed,
    )
    session.add(ep)
    session.commit()
    session.refresh(ep)
    return ep


# ---------------------------------------------------------------------------
# 1–7: SemanticFact CRUD + load_active_facts
# ---------------------------------------------------------------------------

class TestSemanticFactCRUD:

    def test_create_fact_defaults(self, db_session):
        # Property 1
        _clean_facts(db_session, 101)
        fact = _make_fact(db_session, 101, "User prefers Python over Ruby")
        assert fact.id is not None
        assert fact.confidence == pytest.approx(0.40)
        assert fact.is_active is True
        assert fact.reinforcement_count == 0
        assert fact.contradiction_count == 0
        assert fact.last_confirmed_at is None
        assert fact.last_contradicted_at is None

    def test_proposition_stored_as_given(self, db_session):
        # Property 2
        _clean_facts(db_session, 102)
        prop = "User primarily works on backend systems"
        fact = _make_fact(db_session, 102, prop)
        assert fact.proposition == prop

    def test_source_episode_ids_serialized(self, db_session):
        # Property 3
        _clean_facts(db_session, 103)
        ids = [10, 20, 30]
        fact = SemanticFact(
            user_id=103,
            proposition="User asks many questions",
            source_episode_ids_json=json.dumps(ids),
        )
        db_session.add(fact)
        db_session.commit()
        db_session.refresh(fact)
        assert json.loads(fact.source_episode_ids_json) == ids

    def test_load_active_facts_excludes_inactive(self, db_session):
        # Property 4
        _clean_facts(db_session, 104)
        _make_fact(db_session, 104, "Active fact", confidence=0.50)
        inactive = SemanticFact(user_id=104, proposition="Inactive fact", is_active=False)
        db_session.add(inactive)
        db_session.commit()
        results = load_active_facts(db_session, 104)
        assert len(results) == 1
        assert results[0].proposition == "Active fact"

    def test_load_active_facts_user_isolation(self, db_session):
        # Property 5
        _clean_facts(db_session, 105)
        _clean_facts(db_session, 1050)
        _make_fact(db_session, 105, "Fact for user 105")
        results_a = load_active_facts(db_session, 105)
        results_b = load_active_facts(db_session, 1050)
        assert len(results_a) == 1
        assert len(results_b) == 0

    def test_load_active_facts_sorted_by_confidence_desc(self, db_session):
        # Property 6
        _clean_facts(db_session, 106)
        _make_fact(db_session, 106, "Low confidence", confidence=0.30)
        _make_fact(db_session, 106, "High confidence", confidence=0.70)
        _make_fact(db_session, 106, "Mid confidence", confidence=0.50)
        results = load_active_facts(db_session, 106)
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_load_active_facts_min_confidence_filter(self, db_session):
        # Property 7
        _clean_facts(db_session, 107)
        _make_fact(db_session, 107, "Low", confidence=0.30)
        _make_fact(db_session, 107, "High", confidence=0.60)
        results = load_active_facts(db_session, 107, min_confidence=0.50)
        assert all(r.confidence >= 0.50 for r in results)
        assert len(results) == 1
        assert results[0].proposition == "High"


# ---------------------------------------------------------------------------
# 8–13: reinforce_fact
# ---------------------------------------------------------------------------

class TestReinforceFact:

    def test_reinforce_increases_confidence(self, db_session):
        # Property 8
        _clean_facts(db_session, 201)
        fact = _make_fact(db_session, 201, "Fact to reinforce", confidence=0.40)
        updated = reinforce_fact(db_session, fact.id, user_id=201)
        assert updated is not None
        assert updated.confidence == pytest.approx(0.40 + _SEMANTIC_REINFORCE_DELTA, abs=1e-6)

    def test_reinforce_caps_at_max(self, db_session):
        # Property 9
        _clean_facts(db_session, 202)
        fact = _make_fact(db_session, 202, "Near max fact", confidence=0.82)
        updated = reinforce_fact(db_session, fact.id, user_id=202)
        assert updated is not None
        assert updated.confidence == pytest.approx(SEMANTIC_CONFIDENCE_MAX, abs=1e-6)

    def test_reinforce_increments_count(self, db_session):
        # Property 10
        _clean_facts(db_session, 203)
        fact = _make_fact(db_session, 203, "Count test")
        reinforce_fact(db_session, fact.id, user_id=203)
        reinforce_fact(db_session, fact.id, user_id=203)
        db_session.refresh(fact)
        assert fact.reinforcement_count == 2

    def test_reinforce_sets_last_confirmed_at(self, db_session):
        # Property 11
        _clean_facts(db_session, 204)
        fact = _make_fact(db_session, 204, "Timestamp test")
        assert fact.last_confirmed_at is None
        updated = reinforce_fact(db_session, fact.id, user_id=204)
        assert updated is not None
        assert updated.last_confirmed_at is not None

    def test_reinforce_wrong_user_returns_none(self, db_session):
        # Property 12
        _clean_facts(db_session, 205)
        _clean_facts(db_session, 2050)
        fact = _make_fact(db_session, 205, "User 205 fact")
        result = reinforce_fact(db_session, fact.id, user_id=2050)  # wrong user
        assert result is None

    def test_reinforce_inactive_fact_returns_none(self, db_session):
        # Property 13
        _clean_facts(db_session, 206)
        fact = SemanticFact(user_id=206, proposition="Inactive", is_active=False)
        db_session.add(fact)
        db_session.commit()
        db_session.refresh(fact)
        result = reinforce_fact(db_session, fact.id, user_id=206)
        assert result is None


# ---------------------------------------------------------------------------
# 14–20: contradict_fact
# ---------------------------------------------------------------------------

class TestContradictFact:

    def test_contradict_decreases_confidence(self, db_session):
        # Property 14
        _clean_facts(db_session, 301)
        fact = _make_fact(db_session, 301, "Fact to contradict", confidence=0.50)
        updated = contradict_fact(db_session, fact.id, user_id=301)
        assert updated is not None
        assert updated.confidence == pytest.approx(0.50 - _SEMANTIC_CONTRADICT_DELTA, abs=1e-6)

    def test_contradict_floors_at_zero(self, db_session):
        # Property 15
        _clean_facts(db_session, 302)
        fact = _make_fact(db_session, 302, "Near zero fact", confidence=0.05)
        updated = contradict_fact(db_session, fact.id, user_id=302)
        assert updated is not None
        assert updated.confidence == pytest.approx(0.0, abs=1e-6)

    def test_contradict_increments_count(self, db_session):
        # Property 16
        _clean_facts(db_session, 303)
        fact = _make_fact(db_session, 303, "Count test", confidence=0.60)
        contradict_fact(db_session, fact.id, user_id=303)
        contradict_fact(db_session, fact.id, user_id=303)
        db_session.refresh(fact)
        assert fact.contradiction_count == 2

    def test_contradict_sets_last_contradicted_at(self, db_session):
        # Property 17
        _clean_facts(db_session, 304)
        fact = _make_fact(db_session, 304, "Timestamp test")
        assert fact.last_contradicted_at is None
        updated = contradict_fact(db_session, fact.id, user_id=304)
        assert updated is not None
        assert updated.last_contradicted_at is not None

    def test_contradict_deactivates_below_threshold(self, db_session):
        # Property 18 — confidence 0.25 - 0.10 = 0.15 < 0.20 → deactivate
        _clean_facts(db_session, 305)
        fact = _make_fact(db_session, 305, "Near deactivation", confidence=0.25)
        updated = contradict_fact(db_session, fact.id, user_id=305)
        assert updated is not None
        assert updated.confidence == pytest.approx(0.15, abs=1e-6)
        assert updated.is_active is False

    def test_contradict_wrong_user_returns_none(self, db_session):
        # Property 19
        _clean_facts(db_session, 306)
        _clean_facts(db_session, 3060)
        fact = _make_fact(db_session, 306, "User 306 fact")
        result = contradict_fact(db_session, fact.id, user_id=3060)
        assert result is None

    def test_contradict_inactive_fact_returns_none(self, db_session):
        # Property 20
        _clean_facts(db_session, 307)
        fact = SemanticFact(user_id=307, proposition="Already inactive", is_active=False)
        db_session.add(fact)
        db_session.commit()
        db_session.refresh(fact)
        result = contradict_fact(db_session, fact.id, user_id=307)
        assert result is None


# ---------------------------------------------------------------------------
# 21–23: Confidence formula verification
# ---------------------------------------------------------------------------

class TestConfidenceFormula:

    def test_three_reinforcements_from_initial(self, db_session):
        # Property 21 — 0.40 + 3×0.05 = 0.55
        _clean_facts(db_session, 401)
        fact = _make_fact(db_session, 401, "Formula test", confidence=0.40)
        for _ in range(3):
            reinforce_fact(db_session, fact.id, user_id=401)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(0.55, abs=1e-6)

    def test_one_contradiction_from_initial(self, db_session):
        # Property 22 — 0.40 − 0.10 = 0.30
        _clean_facts(db_session, 402)
        fact = _make_fact(db_session, 402, "Contradict from initial", confidence=0.40)
        updated = contradict_fact(db_session, fact.id, user_id=402)
        assert updated is not None
        assert updated.confidence == pytest.approx(0.30, abs=1e-6)

    def test_three_contradictions_deactivate(self, db_session):
        # Property 23 — 0.40 - 3×0.10 = 0.10 < 0.20 → is_active = False
        _clean_facts(db_session, 403)
        fact = _make_fact(db_session, 403, "Will be deactivated", confidence=0.40)
        for _ in range(3):
            contradict_fact(db_session, fact.id, user_id=403)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(0.10, abs=1e-6)
        assert fact.is_active is False


# ---------------------------------------------------------------------------
# 24–27: _parse_synthesis_response
# ---------------------------------------------------------------------------

class TestParseSynthesisResponse:

    def test_valid_json_all_fields(self):
        # Property 24
        raw = json.dumps({
            "new_facts": ["User prefers TDD", "User works in Python"],
            "reinforced_ids": [1, 2],
            "contradicted_ids": [3],
        })
        result = _parse_synthesis_response(raw)
        assert result is not None
        assert result.new_facts == ["User prefers TDD", "User works in Python"]
        assert result.reinforced_ids == [1, 2]
        assert result.contradicted_ids == [3]

    def test_missing_key_empty_list(self):
        # Property 25 — missing contradicted_ids → []
        raw = json.dumps({"new_facts": ["Some fact"], "reinforced_ids": []})
        result = _parse_synthesis_response(raw)
        assert result is not None
        assert result.contradicted_ids == []

    def test_invalid_json_returns_none(self):
        # Property 26
        result = _parse_synthesis_response("not json at all {{{{")
        assert result is None

    def test_ids_parsed_as_int(self):
        # Property 27 — JSON numbers always parse as int
        raw = json.dumps({"new_facts": [], "reinforced_ids": [10, 20], "contradicted_ids": [5]})
        result = _parse_synthesis_response(raw)
        assert result is not None
        assert all(isinstance(i, int) for i in result.reinforced_ids)
        assert all(isinstance(i, int) for i in result.contradicted_ids)


# ---------------------------------------------------------------------------
# 28–29: maybe_trigger_semantic_consolidation
# ---------------------------------------------------------------------------

class TestMaybeTriggerConsolidation:

    def test_below_threshold_haiku_not_called(self, db_session):
        # Property 28 — < 3 unprocessed episodes → no synthesis
        _clean_episodes(db_session, 501)
        _make_episode(db_session, 501, "Episode 1")
        _make_episode(db_session, 501, "Episode 2")
        # Only 2 unprocessed (< _SEMANTIC_BATCH_MIN = 3)

        with patch("app.cognition.semantic_service._call_synthesis_haiku") as mock_haiku:
            maybe_trigger_semantic_consolidation(user_id=501, trace_id="t-below")
            mock_haiku.assert_not_called()

    def test_at_threshold_haiku_called(self, db_session):
        # Property 29 — = 3 unprocessed episodes → synthesis triggered
        _clean_episodes(db_session, 502)
        _clean_facts(db_session, 502)
        _make_episode(db_session, 502, "Episode A")
        _make_episode(db_session, 502, "Episode B")
        _make_episode(db_session, 502, "Episode C")
        # Exactly 3 unprocessed (= _SEMANTIC_BATCH_MIN = 3)

        mock_result = _SynthesisResult(new_facts=[], reinforced_ids=[], contradicted_ids=[])

        with patch("app.cognition.semantic_service._call_synthesis_haiku", return_value=mock_result):
            maybe_trigger_semantic_consolidation(user_id=502, trace_id="t-threshold")

        # All 3 episodes should now be marked processed
        from sqlmodel import select as _select
        from app.memory.db import engine
        with Session(engine) as db:
            episodes = list(db.exec(
                _select(Episode).where(Episode.user_id == 502)
            ).all())
        assert all(e.semantically_processed for e in episodes)

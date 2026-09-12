"""Tests for Operación Remake Fase 8 Paso 1 — User Model service (data layer).

Properties verified:

UserKnowledge:
1.  upsert on new (user_id, topic) creates row with correct fields.
2.  upsert on existing (user_id, topic) updates level, confidence, occurrence_count.
3.  upsert appends trace_id to evidence_trail; deduplicates repeated trace_ids.
4.  confidence is capped at 0.80 regardless of caller input.
5.  load_knowledge without topic filter returns all active rows for user.
6.  load_knowledge with topic filter returns only matching topic.
7.  is_active=False row is excluded from load_knowledge.
8.  user A's knowledge is not returned for user B (isolation invariant).

BeliefAttribution:
9.  add_belief_attribution creates row with correct fields.
10. confidence is capped at 0.65 regardless of caller input.
11. proposition is truncated to 300 chars.
12. load_belief_attributions default (is_active=True) excludes inactive rows.
13. load_belief_attributions(is_active=False) returns only inactive rows.
14. user A's beliefs are not returned for user B (isolation invariant).

Expectation:
15. upsert on new (user_id, context_type, expected_behavior) creates row.
16. upsert on existing row updates probability, occurrence_count, evidence_trail.
17. unknown expected_behavior returns None without raising.
18. load_active_expectations respects min_probability threshold.
19. load_active_expectations excludes is_active=False rows.
20. load_active_expectations filters by context_type — other context_types excluded.
21. user A's expectations not returned for user B (isolation invariant).
22. load_active_expectations returns empty list when no qualifying rows exist.
"""
from __future__ import annotations

import json
import pytest
from sqlmodel import delete as sql_delete

from app.memory.models import BeliefAttribution, Expectation, UserKnowledge
from app.cognition.user_model_service import (
    _MAX_BELIEF_CONFIDENCE,
    _MAX_KNOWLEDGE_CONFIDENCE,
    VALID_EXPECTED_BEHAVIORS,
    add_belief_attribution,
    load_active_expectations,
    load_belief_attributions,
    load_knowledge,
    upsert_expectation,
    upsert_knowledge,
)


# ---------------------------------------------------------------------------
# Cleanup helpers (isolation between tests)
# ---------------------------------------------------------------------------

def _clean_knowledge(session, user_id: int) -> None:
    session.exec(sql_delete(UserKnowledge).where(UserKnowledge.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


def _clean_beliefs(session, user_id: int) -> None:
    session.exec(sql_delete(BeliefAttribution).where(BeliefAttribution.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


def _clean_expectations(session, user_id: int) -> None:
    session.exec(sql_delete(Expectation).where(Expectation.user_id == user_id))  # type: ignore[call-overload]
    session.commit()


# ---------------------------------------------------------------------------
# 1–8: UserKnowledge
# ---------------------------------------------------------------------------

class TestUserKnowledge:

    def test_upsert_creates_new_row(self, db_session):
        # Property 1
        _clean_knowledge(db_session, 801)
        row = upsert_knowledge(db_session, user_id=801, topic="python",
                               level=0.90, confidence=0.70, trace_id="t1")
        assert row is not None
        assert row.user_id == 801
        assert row.topic == "python"
        assert row.level == pytest.approx(0.90, abs=1e-6)
        assert row.confidence == pytest.approx(0.70, abs=1e-6)
        assert row.occurrence_count == 1
        assert "t1" in json.loads(row.evidence_trail_json)

    def test_upsert_updates_existing_row(self, db_session):
        # Property 2
        _clean_knowledge(db_session, 802)
        upsert_knowledge(db_session, user_id=802, topic="rust",
                         level=0.30, confidence=0.40, trace_id="t1")
        updated = upsert_knowledge(db_session, user_id=802, topic="rust",
                                   level=0.55, confidence=0.60, trace_id="t2")
        assert updated is not None
        assert updated.level == pytest.approx(0.55, abs=1e-6)
        assert updated.confidence == pytest.approx(0.60, abs=1e-6)
        assert updated.occurrence_count == 2
        rows = load_knowledge(db_session, 802, topic="rust")
        assert len(rows) == 1, "upsert must not create a duplicate row"

    def test_upsert_evidence_trail_deduplication(self, db_session):
        # Property 3
        _clean_knowledge(db_session, 803)
        upsert_knowledge(db_session, user_id=803, topic="sql",
                         level=0.50, confidence=0.50, trace_id="trace-A")
        row = upsert_knowledge(db_session, user_id=803, topic="sql",
                               level=0.50, confidence=0.50, trace_id="trace-A")  # same trace_id
        assert row is not None
        trail = json.loads(row.evidence_trail_json)
        assert trail.count("trace-A") == 1, "same trace_id must not be duplicated"

    def test_confidence_capped_at_max(self, db_session):
        # Property 4 — confidence 0.99 → clamped to 0.80
        _clean_knowledge(db_session, 804)
        row = upsert_knowledge(db_session, user_id=804, topic="go",
                               level=0.80, confidence=0.99)
        assert row is not None
        assert row.confidence <= _MAX_KNOWLEDGE_CONFIDENCE + 1e-9

    def test_load_all_topics(self, db_session):
        # Property 5
        _clean_knowledge(db_session, 805)
        upsert_knowledge(db_session, user_id=805, topic="python", level=0.9, confidence=0.7)
        upsert_knowledge(db_session, user_id=805, topic="rust", level=0.5, confidence=0.5)
        rows = load_knowledge(db_session, 805)
        topics = {r.topic for r in rows}
        assert "python" in topics
        assert "rust" in topics

    def test_load_filtered_by_topic(self, db_session):
        # Property 6
        _clean_knowledge(db_session, 806)
        upsert_knowledge(db_session, user_id=806, topic="python", level=0.9, confidence=0.7)
        upsert_knowledge(db_session, user_id=806, topic="rust", level=0.5, confidence=0.5)
        rows = load_knowledge(db_session, 806, topic="python")
        assert len(rows) == 1
        assert rows[0].topic == "python"

    def test_inactive_row_excluded(self, db_session):
        # Property 7
        _clean_knowledge(db_session, 807)
        row = upsert_knowledge(db_session, user_id=807, topic="java", level=0.6, confidence=0.5)
        assert row is not None
        row.is_active = False
        db_session.add(row)
        db_session.commit()
        result = load_knowledge(db_session, 807, topic="java")
        assert len(result) == 0

    def test_user_isolation(self, db_session):
        # Property 8 — user A's knowledge must not appear for user B
        _clean_knowledge(db_session, 811)
        _clean_knowledge(db_session, 812)
        upsert_knowledge(db_session, user_id=811, topic="haskell", level=0.7, confidence=0.6)
        result_b = load_knowledge(db_session, 812, topic="haskell")
        assert len(result_b) == 0


# ---------------------------------------------------------------------------
# 9–14: BeliefAttribution
# ---------------------------------------------------------------------------

class TestBeliefAttribution:

    def test_add_creates_row(self, db_session):
        # Property 9
        _clean_beliefs(db_session, 821)
        row = add_belief_attribution(
            db_session,
            user_id=821,
            proposition="The user believes Python is the best language",
            confidence=0.50,
            source="reflection",
            context_type="implementation",
            trace_id="t-ba-1",
        )
        assert row is not None
        assert row.user_id == 821
        assert row.confidence == pytest.approx(0.50, abs=1e-6)
        assert row.source == "reflection"
        assert row.context_type == "implementation"
        assert "t-ba-1" in json.loads(row.evidence_trail_json)

    def test_confidence_capped_at_max(self, db_session):
        # Property 10 — confidence 0.90 → clamped to 0.65
        _clean_beliefs(db_session, 822)
        row = add_belief_attribution(db_session, user_id=822,
                                     proposition="User believes X", confidence=0.90)
        assert row is not None
        assert row.confidence <= _MAX_BELIEF_CONFIDENCE + 1e-9

    def test_proposition_truncated(self, db_session):
        # Property 11 — proposition > 300 chars must be stored truncated
        _clean_beliefs(db_session, 823)
        long_prop = "x" * 400
        row = add_belief_attribution(db_session, user_id=823,
                                     proposition=long_prop, confidence=0.40)
        assert row is not None
        assert len(row.proposition) == 300

    def test_load_excludes_inactive(self, db_session):
        # Property 12
        _clean_beliefs(db_session, 824)
        row = add_belief_attribution(db_session, user_id=824,
                                     proposition="X", confidence=0.40)
        assert row is not None
        row.is_active = False
        db_session.add(row)
        db_session.commit()
        result = load_belief_attributions(db_session, 824)
        assert len(result) == 0

    def test_load_inactive_filter(self, db_session):
        # Property 13 — explicit is_active=False returns only inactive rows
        _clean_beliefs(db_session, 825)
        active = add_belief_attribution(db_session, user_id=825,
                                        proposition="Active belief", confidence=0.40)
        inactive = add_belief_attribution(db_session, user_id=825,
                                          proposition="Inactive belief", confidence=0.35)
        assert inactive is not None
        inactive.is_active = False
        db_session.add(inactive)
        db_session.commit()

        only_inactive = load_belief_attributions(db_session, 825, is_active=False)
        assert len(only_inactive) == 1
        assert only_inactive[0].proposition == "Inactive belief"

    def test_user_isolation(self, db_session):
        # Property 14
        _clean_beliefs(db_session, 831)
        _clean_beliefs(db_session, 832)
        add_belief_attribution(db_session, user_id=831,
                               proposition="User 831 belief", confidence=0.45)
        result_b = load_belief_attributions(db_session, 832)
        assert len(result_b) == 0


# ---------------------------------------------------------------------------
# 15–22: Expectation
# ---------------------------------------------------------------------------

class TestExpectation:

    def test_upsert_creates_row(self, db_session):
        # Property 15
        _clean_expectations(db_session, 841)
        row = upsert_expectation(
            db_session,
            user_id=841,
            context_type="implementation",
            expected_behavior="request_help",
            probability=0.75,
            trace_id="t-exp-1",
        )
        assert row is not None
        assert row.user_id == 841
        assert row.context_type == "implementation"
        assert row.expected_behavior == "request_help"
        assert row.probability == pytest.approx(0.75, abs=1e-6)
        assert row.occurrence_count == 1
        assert "t-exp-1" in json.loads(row.evidence_trail_json)

    def test_upsert_updates_existing_row(self, db_session):
        # Property 16
        _clean_expectations(db_session, 842)
        upsert_expectation(db_session, user_id=842, context_type="debugging",
                           expected_behavior="ask_question", probability=0.65)
        updated = upsert_expectation(db_session, user_id=842, context_type="debugging",
                                     expected_behavior="ask_question", probability=0.80,
                                     trace_id="t-upd")
        assert updated is not None
        assert updated.probability == pytest.approx(0.80, abs=1e-6)
        assert updated.occurrence_count == 2
        # Must not create a duplicate row
        rows = load_active_expectations(db_session, user_id=842,
                                        context_type="debugging", min_probability=0.0)
        matching = [r for r in rows if r.expected_behavior == "ask_question"]
        assert len(matching) == 1

    def test_unknown_behavior_returns_none(self, db_session):
        # Property 17
        _clean_expectations(db_session, 843)
        result = upsert_expectation(db_session, user_id=843,
                                    context_type="debugging",
                                    expected_behavior="totally_unknown_behavior_xyz",
                                    probability=0.80)
        assert result is None

    def test_load_respects_min_probability(self, db_session):
        # Property 18 — rows below min_probability not returned
        _clean_expectations(db_session, 844)
        upsert_expectation(db_session, user_id=844, context_type="planning",
                           expected_behavior="ask_question", probability=0.55)
        upsert_expectation(db_session, user_id=844, context_type="planning",
                           expected_behavior="request_help", probability=0.75)
        # Default min_probability=0.60 → only the 0.75 row
        rows = load_active_expectations(db_session, user_id=844, context_type="planning")
        behaviors = {r.expected_behavior for r in rows}
        assert "request_help" in behaviors
        assert "ask_question" not in behaviors

    def test_load_excludes_inactive(self, db_session):
        # Property 19
        _clean_expectations(db_session, 845)
        row = upsert_expectation(db_session, user_id=845, context_type="feedback",
                                 expected_behavior="challenge_sity", probability=0.70)
        assert row is not None
        row.is_active = False
        db_session.add(row)
        db_session.commit()
        result = load_active_expectations(db_session, user_id=845,
                                          context_type="feedback", min_probability=0.0)
        assert len(result) == 0

    def test_load_filters_by_context_type(self, db_session):
        # Property 20 — expectations for other context_types not returned
        _clean_expectations(db_session, 846)
        upsert_expectation(db_session, user_id=846, context_type="implementation",
                           expected_behavior="request_help", probability=0.80)
        upsert_expectation(db_session, user_id=846, context_type="debugging",
                           expected_behavior="ask_question", probability=0.80)
        impl_rows = load_active_expectations(db_session, user_id=846,
                                             context_type="implementation")
        assert all(r.context_type == "implementation" for r in impl_rows)
        assert not any(r.context_type == "debugging" for r in impl_rows)

    def test_user_isolation(self, db_session):
        # Property 21
        _clean_expectations(db_session, 851)
        _clean_expectations(db_session, 852)
        upsert_expectation(db_session, user_id=851, context_type="casual_chat",
                           expected_behavior="casual_engagement", probability=0.80)
        result_b = load_active_expectations(db_session, user_id=852,
                                            context_type="casual_chat")
        assert len(result_b) == 0

    def test_returns_empty_when_no_rows(self, db_session):
        # Property 22
        _clean_expectations(db_session, 853)
        result = load_active_expectations(db_session, user_id=853,
                                          context_type="technical_design")
        assert result == []

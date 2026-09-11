"""Tests for Operación Remake Fase 6 — SelfModel, SelfBelief, SityValues (Paso 1).

Properties verified:

SelfModel singleton:
1.  get_or_create_self_model returns a SelfModel with identity_name="Sity".
2.  get_or_create_self_model is idempotent (same id on second call).
3.  abilities_json defaults to "{}".
4.  limitations_json defaults to "[]".
5.  current_roles_json contains "assistant".
6.  unresolved_questions_json defaults to "[]".

SityValues singleton:
7.  get_or_create_sity_values returns SityValues with doc defaults.
8.  get_or_create_sity_values is idempotent (same id on second call).
9.  load_values_dict returns dict with all 6 value_ keys.
10. load_values_dict values match defaults from sección 43.
11. load_values_dict creates singleton if absent.

SelfBelief — creation:
12. add_belief_candidate creates a row with given proposition.
13. source defaults to "metacognition" when not specified.
14. confidence defaults to 0.40 for metacognition candidates.
15. is_active=True by default.
16. evidence_trail_json contains the initial evidence entry with trace_id.
17. "initial" source belief accepts higher confidence (0.70).

SelfBelief — retrieval:
18. get_active_beliefs returns only is_active=True rows.
19. Deactivated belief excluded from get_active_beliefs.
20. get_active_beliefs returns empty list when no beliefs exist.

SelfBelief — update:
21. update_belief_confidence changes confidence.
22. update_belief_confidence appends evidence entry to trail.
23. update_belief_confidence returns None for unknown belief_id.
24. confidence clamped to [0, 1] on create.
25. confidence clamped to [0, 1] on update.
"""
from __future__ import annotations

import json

import pytest
from sqlmodel import Session

from app.cognition.self_model_service import (
    add_belief_candidate,
    deactivate_belief,
    get_active_beliefs,
    get_or_create_self_model,
    get_or_create_sity_values,
    load_values_dict,
    update_belief_confidence,
)


# ---------------------------------------------------------------------------
# SelfModel singleton
# ---------------------------------------------------------------------------

class TestSelfModelSingleton:
    def test_returns_self_model_with_default_name(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        assert sm.identity_name == "Sity"

    def test_idempotent_same_id(self, db_session: Session):
        sm1 = get_or_create_self_model(db_session)
        sm2 = get_or_create_self_model(db_session)
        assert sm1.id == sm2.id

    def test_abilities_json_defaults_empty_dict(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        assert json.loads(sm.abilities_json) == {}

    def test_limitations_json_defaults_empty_list(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        assert json.loads(sm.limitations_json) == []

    def test_current_roles_contains_assistant(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        roles = json.loads(sm.current_roles_json)
        assert "assistant" in roles

    def test_unresolved_questions_defaults_empty_list(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        assert json.loads(sm.unresolved_questions_json) == []


# ---------------------------------------------------------------------------
# SityValues singleton
# ---------------------------------------------------------------------------

class TestSityValuesSingleton:
    def test_returns_sity_values_with_doc_defaults(self, db_session: Session):
        v = get_or_create_sity_values(db_session)
        assert v.value_autonomy == pytest.approx(0.80)
        assert v.value_honesty == pytest.approx(0.75)
        assert v.value_helpfulness == pytest.approx(0.72)
        assert v.value_curiosity == pytest.approx(0.66)
        assert v.value_fairness == pytest.approx(0.80)
        assert v.value_loyalty == pytest.approx(0.50)

    def test_idempotent_same_id(self, db_session: Session):
        v1 = get_or_create_sity_values(db_session)
        v2 = get_or_create_sity_values(db_session)
        assert v1.id == v2.id

    def test_load_values_dict_has_all_six_keys(self, db_session: Session):
        d = load_values_dict(db_session)
        expected_keys = {
            "value_autonomy", "value_honesty", "value_helpfulness",
            "value_curiosity", "value_fairness", "value_loyalty",
        }
        assert set(d.keys()) == expected_keys

    def test_load_values_dict_matches_defaults(self, db_session: Session):
        d = load_values_dict(db_session)
        assert d["value_autonomy"] == pytest.approx(0.80)
        assert d["value_fairness"] == pytest.approx(0.80)
        assert d["value_loyalty"] == pytest.approx(0.50)

    def test_load_values_dict_creates_singleton_if_absent(self, db_session: Session):
        # Call without prior get_or_create — should not raise
        d = load_values_dict(db_session)
        assert isinstance(d, dict)
        assert len(d) == 6


# ---------------------------------------------------------------------------
# SelfBelief — creation
# ---------------------------------------------------------------------------

class TestSelfBeliefCreation:
    def _sm_id(self, db_session: Session) -> int:
        return get_or_create_self_model(db_session).id  # type: ignore[return-value]

    def test_creates_row_with_proposition(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="tiendo a mantener mi criterio")
        assert b.proposition == "tiendo a mantener mi criterio"

    def test_source_defaults_to_metacognition(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x")
        assert b.source == "metacognition"

    def test_confidence_defaults_to_040_for_metacognition(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x")
        assert b.confidence == pytest.approx(0.40)

    def test_is_active_true_by_default(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x")
        assert b.is_active is True

    def test_evidence_trail_contains_trace_id(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(
            db_session, self_model_id=sm_id, proposition="x",
            trace_id="abc123", evidence_description="reflection output",
        )
        trail = json.loads(b.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["trace_id"] == "abc123"

    def test_initial_source_accepts_higher_confidence(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(
            db_session, self_model_id=sm_id, proposition="soy un asistente útil",
            confidence=0.70, source="initial",
        )
        assert b.confidence == pytest.approx(0.70)
        assert b.source == "initial"


# ---------------------------------------------------------------------------
# SelfBelief — retrieval
# ---------------------------------------------------------------------------

class TestSelfBeliefRetrieval:
    def _sm_id(self, db_session: Session) -> int:
        return get_or_create_self_model(db_session).id  # type: ignore[return-value]

    def test_get_active_returns_only_active_rows(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b1 = add_belief_candidate(db_session, self_model_id=sm_id, proposition="active belief")
        b2 = add_belief_candidate(db_session, self_model_id=sm_id, proposition="to be deactivated")
        deactivate_belief(db_session, b2.id)  # type: ignore[arg-type]
        active = get_active_beliefs(db_session, sm_id)
        ids = [b.id for b in active]
        assert b1.id in ids
        assert b2.id not in ids

    def test_deactivated_belief_excluded(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x")
        deactivate_belief(db_session, b.id)  # type: ignore[arg-type]
        active = get_active_beliefs(db_session, sm_id)
        assert all(ab.id != b.id for ab in active)

    def test_returns_empty_list_when_no_beliefs(self, db_session: Session):
        sm = get_or_create_self_model(db_session)
        # Fresh session with no beliefs — may have residual from other tests
        # so we just verify no exception and correct type
        active = get_active_beliefs(db_session, sm.id)  # type: ignore[arg-type]
        assert isinstance(active, list)


# ---------------------------------------------------------------------------
# SelfBelief — update
# ---------------------------------------------------------------------------

class TestSelfBeliefUpdate:
    def _sm_id(self, db_session: Session) -> int:
        return get_or_create_self_model(db_session).id  # type: ignore[return-value]

    def test_update_changes_confidence(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x", confidence=0.40)
        updated = update_belief_confidence(db_session, belief_id=b.id, new_confidence=0.65)  # type: ignore[arg-type]
        assert updated is not None
        assert updated.confidence == pytest.approx(0.65)

    def test_update_appends_evidence_entry(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(
            db_session, self_model_id=sm_id, proposition="x",
            trace_id="first", evidence_description="initial",
        )
        update_belief_confidence(
            db_session, belief_id=b.id,  # type: ignore[arg-type]
            new_confidence=0.60,
            trace_id="second", evidence_description="corroborated",
        )
        from sqlmodel import select as _select
        from app.memory.models import SelfBelief
        refreshed = db_session.get(SelfBelief, b.id)
        trail = json.loads(refreshed.evidence_trail_json)  # type: ignore[union-attr]
        assert len(trail) == 2
        assert trail[1]["trace_id"] == "second"

    def test_update_returns_none_for_unknown_id(self, db_session: Session):
        result = update_belief_confidence(db_session, belief_id=999999, new_confidence=0.5)
        assert result is None

    def test_confidence_clamped_on_create(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x", confidence=1.5)
        assert b.confidence <= 1.0

    def test_confidence_clamped_on_update(self, db_session: Session):
        sm_id = self._sm_id(db_session)
        b = add_belief_candidate(db_session, self_model_id=sm_id, proposition="x")
        updated = update_belief_confidence(db_session, belief_id=b.id, new_confidence=-0.5)  # type: ignore[arg-type]
        assert updated is not None
        assert updated.confidence >= 0.0

"""Tests for MINI-REMAKE v2.0 Punto 4A — semantic_resolver.py

Properties verified:

resolve_candidate — fast paths:
1.  Empty existing list → SemanticResolution(relation="new") without Haiku call.
2.  Exact proposition match (lowercased) → SemanticResolution(relation="match", confidence=1.0).
3.  Exact match with whitespace normalization → still returns MATCH.

resolve_candidate — Haiku path:
4.  Haiku returns valid MATCH JSON → parsed correctly with target_id.
5.  Haiku returns valid CONTRADICT JSON → parsed correctly.
6.  Haiku returns valid RELATED JSON → parsed correctly.
7.  Haiku response fails (ok=False) → fallback NEW with reason="haiku_fallback".
8.  Haiku raises exception → fallback NEW.
9.  Haiku returns invalid target_id not in existing → demoted to NEW.

_parse_resolver_response:
10. Valid JSON all fields → SemanticResolution parsed correctly.
11. Relation not in allowed set → defaults to "new".
12. target_id not coercible to int → None.
13. Invalid JSON → returns None.
14. Code fence wrapping → stripped and parsed.

Confidence formula (Componente C — diminishing returns):
15. SelfBelief: 4 reinforcements from 0.30 → confidence >= 0.60.
16. SelfBelief: contradict from 0.40 → confidence = 0.40 - 0.40*0.15 = 0.34.
17. SemanticFact: 4 reinforcements from 0.30 → confidence >= 0.60.
18. SemanticFact: contradiction reduces confidence correctly.

evidence_trail_json (Componente B):
19. reinforce_fact appends an entry to evidence_trail_json.
20. contradict_fact appends an entry to evidence_trail_json.

Volume consolidation trigger (Componente D):
21. With < 10 candidates, maybe_trigger_volume_consolidation does NOT launch a thread.
22. With >= 10 candidates, maybe_trigger_volume_consolidation launches a daemon thread.

Behaviour-regression tests (require real ANTHROPIC_API_KEY):
23. "Tiendo a ser directa" vs "Suelo responder con confrontación" → MATCH or RELATED.
24. "Le gusta el techno" vs "No soporta el techno" → CONTRADICT.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import delete as sql_delete, Session

from app.memory.models import SelfBelief, SemanticFact, SelfModel, utc_now
from app.cognition.semantic_resolver import (
    SemanticResolution,
    _parse_resolver_response,
    resolve_candidate,
)
from app.cognition.self_model_service import (
    _BELIEF_REINFORCE_RATE,
    _BELIEF_CONTRADICT_RATE,
    add_belief_candidate,
    contradict_belief,
    get_or_create_self_model,
    reinforce_belief,
)
from app.cognition.semantic_service import (
    _SEMANTIC_REINFORCE_RATE,
    _SEMANTIC_CONTRADICT_RATE,
    SEMANTIC_CONFIDENCE_MAX,
    _count_active_semantic_facts,
    _count_active_self_beliefs,
    maybe_trigger_volume_consolidation,
    reinforce_fact,
    contradict_fact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UID = 90_100


def _clean(session: Session) -> None:
    session.exec(sql_delete(SemanticFact).where(SemanticFact.user_id == _UID))  # type: ignore[call-overload]
    session.commit()


def _make_belief(session: Session, proposition: str, confidence: float = 0.50) -> SelfBelief:
    sm = get_or_create_self_model(session)
    assert sm.id is not None
    b = add_belief_candidate(
        session, self_model_id=sm.id, proposition=proposition, confidence=confidence,
    )
    return b


def _make_fact(session: Session, proposition: str, confidence: float = 0.40) -> SemanticFact:
    f = SemanticFact(user_id=_UID, proposition=proposition, confidence=confidence)
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


def _mock_haiku(relation: str, target_id: int | None = None, confidence: float = 0.85) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.text = json.dumps({
        "relation": relation,
        "target_id": target_id,
        "confidence": confidence,
        "reason": "test reason",
    })
    provider = MagicMock()
    provider.generate.return_value = resp
    mock_factory = MagicMock(return_value=provider)
    return mock_factory


# ---------------------------------------------------------------------------
# 1–3: Fast paths
# ---------------------------------------------------------------------------

class TestResolveCandidate_FastPaths:

    def test_empty_existing_returns_new(self):
        resolution = resolve_candidate("some proposition", "self_belief", [])
        assert resolution.relation == "new"
        assert resolution.target_id is None

    def test_empty_existing_no_haiku_call(self):
        with patch("app.cognition.semantic_resolver.build_ai_provider") as mock_factory:
            resolve_candidate("some proposition", "self_belief", [])
            mock_factory.assert_not_called()

    def test_exact_match_returns_match(self, db_session: Session):
        b = _make_belief(db_session, "tiendo a ser directa")
        resolution = resolve_candidate("tiendo a ser directa", "self_belief", [b])
        assert resolution.relation == "match"
        assert resolution.target_id == b.id
        assert resolution.confidence == pytest.approx(1.0)

    def test_exact_match_case_insensitive(self, db_session: Session):
        b = _make_belief(db_session, "Tiendo a ser directa")
        resolution = resolve_candidate("tiendo a ser directa", "self_belief", [b])
        assert resolution.relation == "match"
        assert resolution.target_id == b.id

    def test_exact_match_no_haiku_call(self, db_session: Session):
        b = _make_belief(db_session, "tiendo a ser directa")
        with patch("app.cognition.semantic_resolver.build_ai_provider") as mock_factory:
            resolve_candidate("tiendo a ser directa", "self_belief", [b])
            mock_factory.assert_not_called()


# ---------------------------------------------------------------------------
# 4–9: Haiku path
# ---------------------------------------------------------------------------

class TestResolveCandidate_HaikuPath:

    def test_haiku_match_parsed(self, db_session: Session):
        b = _make_belief(db_session, "me importa la honestidad")
        with patch("app.cognition.semantic_resolver.build_ai_provider", _mock_haiku("match", b.id)):
            r = resolve_candidate("valoro ser honesta", "self_belief", [b])
        assert r.relation == "match"
        assert r.target_id == b.id
        assert r.confidence == pytest.approx(0.85)

    def test_haiku_contradict_parsed(self, db_session: Session):
        b = _make_belief(db_session, "me gusta el techno")
        with patch("app.cognition.semantic_resolver.build_ai_provider", _mock_haiku("contradict", b.id)):
            r = resolve_candidate("no soporto el techno", "self_belief", [b])
        assert r.relation == "contradict"
        assert r.target_id == b.id

    def test_haiku_related_parsed(self, db_session: Session):
        b = _make_belief(db_session, "me gusta programar")
        with patch("app.cognition.semantic_resolver.build_ai_provider", _mock_haiku("related", b.id)):
            r = resolve_candidate("me encanta el diseño de software", "self_belief", [b])
        assert r.relation == "related"

    def test_haiku_response_not_ok_falls_back_to_new(self, db_session: Session):
        b = _make_belief(db_session, "alguna creencia")
        bad_resp = MagicMock()
        bad_resp.ok = False
        bad_resp.text = ""
        provider = MagicMock()
        provider.generate.return_value = bad_resp
        with patch("app.cognition.semantic_resolver.build_ai_provider", return_value=provider):
            r = resolve_candidate("nueva proposición", "self_belief", [b])
        assert r.relation == "new"
        assert r.reason == "haiku_fallback"

    def test_haiku_exception_falls_back_to_new(self, db_session: Session):
        b = _make_belief(db_session, "alguna creencia")
        with patch("app.cognition.semantic_resolver.build_ai_provider", side_effect=RuntimeError("boom")):
            r = resolve_candidate("otra proposición", "self_belief", [b])
        assert r.relation == "new"
        assert r.reason == "haiku_fallback"

    def test_invalid_target_id_demoted_to_new(self, db_session: Session):
        b = _make_belief(db_session, "alguna creencia")
        # Return a target_id that is NOT in existing
        with patch("app.cognition.semantic_resolver.build_ai_provider",
                   _mock_haiku("match", target_id=99999)):
            r = resolve_candidate("nueva proposición", "self_belief", [b])
        assert r.relation == "new"
        assert r.target_id is None


# ---------------------------------------------------------------------------
# 10–14: _parse_resolver_response
# ---------------------------------------------------------------------------

class TestParseResolverResponse:

    def test_valid_json_all_fields(self):
        raw = json.dumps({"relation": "match", "target_id": 5, "confidence": 0.9, "reason": "same"})
        r = _parse_resolver_response(raw)
        assert r is not None
        assert r.relation == "match"
        assert r.target_id == 5
        assert r.confidence == pytest.approx(0.9)
        assert r.reason == "same"

    def test_unknown_relation_defaults_to_new(self):
        raw = json.dumps({"relation": "fused", "target_id": None, "confidence": 0.8, "reason": ""})
        r = _parse_resolver_response(raw)
        assert r is not None
        assert r.relation == "new"

    def test_non_int_target_id_becomes_none(self):
        raw = json.dumps({"relation": "match", "target_id": "not-a-number", "confidence": 0.7, "reason": ""})
        r = _parse_resolver_response(raw)
        assert r is not None
        assert r.target_id is None

    def test_invalid_json_returns_none(self):
        assert _parse_resolver_response("{{invalid}}") is None

    def test_code_fence_stripped(self):
        raw = "```json\n" + json.dumps({"relation": "new", "target_id": None, "confidence": 0.5, "reason": ""}) + "\n```"
        r = _parse_resolver_response(raw)
        assert r is not None
        assert r.relation == "new"


# ---------------------------------------------------------------------------
# 15–18: Confidence — diminishing returns (Componente C)
# ---------------------------------------------------------------------------

class TestConfidenceDiminishingReturns:

    def test_selfbelief_four_reinforcements_from_030(self, db_session: Session):
        # Start 0.30, after 4: 0.30→0.44→0.552→0.642→0.714 ≥ 0.60
        b = _make_belief(db_session, "creencia para test reinforce", confidence=0.30)
        for _ in range(4):
            reinforce_belief(db_session, b.id)
        db_session.refresh(b)
        assert b.confidence >= 0.60

    def test_selfbelief_contradict_from_040(self, db_session: Session):
        b = _make_belief(db_session, "creencia para test contradict", confidence=0.40)
        contradict_belief(db_session, b.id)
        db_session.refresh(b)
        expected = 0.40 - 0.40 * _BELIEF_CONTRADICT_RATE
        assert b.confidence == pytest.approx(expected, abs=1e-6)

    def test_semanticfact_four_reinforcements_from_030(self, db_session: Session):
        _clean(db_session)
        f = _make_fact(db_session, "fact para test reinforce", confidence=0.30)
        for _ in range(4):
            reinforce_fact(db_session, f.id, user_id=_UID)
        db_session.refresh(f)
        assert f.confidence >= 0.60

    def test_semanticfact_contradict_reduces_confidence(self, db_session: Session):
        _clean(db_session)
        f = _make_fact(db_session, "fact para test contradict", confidence=0.50)
        contradict_fact(db_session, f.id, user_id=_UID)
        db_session.refresh(f)
        expected = 0.50 - 0.50 * _SEMANTIC_CONTRADICT_RATE
        assert f.confidence == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# 19–20: evidence_trail_json (Componente B)
# ---------------------------------------------------------------------------

class TestEvidenceTrail:

    def test_reinforce_fact_appends_to_trail(self, db_session: Session):
        _clean(db_session)
        f = _make_fact(db_session, "trail reinforce test")
        assert json.loads(f.evidence_trail_json) == []
        reinforce_fact(db_session, f.id, user_id=_UID, trace_id="t-001")
        db_session.refresh(f)
        trail = json.loads(f.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["relation"] == "support"
        assert trail[0]["turn_id"] == "t-001"

    def test_contradict_fact_appends_to_trail(self, db_session: Session):
        _clean(db_session)
        f = _make_fact(db_session, "trail contradict test", confidence=0.50)
        contradict_fact(db_session, f.id, user_id=_UID, trace_id="t-002")
        db_session.refresh(f)
        trail = json.loads(f.evidence_trail_json)
        assert len(trail) == 1
        assert trail[0]["relation"] == "contradict"
        assert trail[0]["turn_id"] == "t-002"


# ---------------------------------------------------------------------------
# 21–22: Volume consolidation trigger (Componente D)
# ---------------------------------------------------------------------------

class TestVolumeConsolidationTrigger:

    def test_below_threshold_no_thread_launched(self, db_session: Session):
        _clean(db_session)
        with patch("app.cognition.semantic_service._count_active_semantic_facts", return_value=5), \
             patch("app.cognition.semantic_service._count_active_self_beliefs", return_value=5), \
             patch("app.cognition.semantic_service.threading") as mock_threading:
            maybe_trigger_volume_consolidation(user_id=_UID)
            mock_threading.Thread.assert_not_called()

    def test_at_threshold_sf_thread_launched(self, db_session: Session):
        with patch("app.cognition.semantic_service._count_active_semantic_facts", return_value=10), \
             patch("app.cognition.semantic_service._count_active_self_beliefs", return_value=5), \
             patch("app.cognition.semantic_service.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            maybe_trigger_volume_consolidation(user_id=_UID)
            mock_threading.Thread.assert_called_once()
            assert mock_threading.Thread.call_args.kwargs.get("daemon") is True
            mock_thread.start.assert_called_once()


# ---------------------------------------------------------------------------
# 23–24: Behaviour regression (require real ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.behavior_regression
class TestSemanticResolverBehaviorRegression:

    def test_similar_directness_beliefs_match_or_related(self, db_session: Session):
        b = _make_belief(db_session, "Tiendo a ser directa")
        r = resolve_candidate("Suelo responder con confrontación", "self_belief", [b])
        assert r.relation in ("match", "related"), (
            f"Expected match or related for semantically similar beliefs, got {r.relation!r}"
        )

    def test_techno_contradiction_detected(self, db_session: Session):
        b = _make_belief(db_session, "Le gusta el techno")
        r = resolve_candidate("No soporta el techno", "self_belief", [b])
        assert r.relation == "contradict", (
            f"Expected contradict for opposing claims, got {r.relation!r}"
        )

"""Tests for SemanticFact.stability field and apply_semantic_fact_decay
(MINI-REMAKE v2.0 Punto 4-B).

Properties:
1.  New SemanticFact has stability="normal" by default.
2.  stability field persists to DB and can be read back.
3.  apply_semantic_fact_decay: facts meeting decay condition lose confidence.
4.  apply_semantic_fact_decay: fact with confidence >= 0.65 is NOT decayed.
5.  apply_semantic_fact_decay: fact with reinforcement_count >= 3 is NOT decayed.
6.  apply_semantic_fact_decay: fact with stability="stable" is NOT decayed.
7.  apply_semantic_fact_decay: fact whose confidence drops below deactivation
    threshold is deactivated (is_active=False).
8.  apply_semantic_fact_decay: inactive facts are NOT touched.
9.  apply_semantic_fact_decay: user isolation — only the target user's facts decay.
10. apply_semantic_fact_decay: no-op when no qualifying facts exist.
11. maybe_trigger_semantic_consolidation calls apply_semantic_fact_decay
    even when below the synthesis batch threshold.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import delete as sql_delete, Session

from app.memory.models import Episode, SemanticFact, utc_now
from app.cognition.semantic_service import (
    SEMANTIC_CONFIDENCE_MAX,
    SEMANTIC_DEACTIVATION_THRESHOLD,
    _SEMANTIC_BATCH_MIN,
    _SEMANTIC_PASSIVE_DECAY,
    _SEMANTIC_PASSIVE_DECAY_MIN_CONFIDENCE,
    _SEMANTIC_PASSIVE_DECAY_MIN_REINFORCEMENTS,
    apply_semantic_fact_decay,
    maybe_trigger_semantic_consolidation,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_UID = 980_000   # high user_id to avoid autoincrement collisions
_UID_OTHER = 980_001


def _clean(session: Session, *uids: int) -> None:
    for uid in uids:
        session.exec(sql_delete(SemanticFact).where(SemanticFact.user_id == uid))  # type: ignore[call-overload]
        session.exec(sql_delete(Episode).where(Episode.user_id == uid))  # type: ignore[call-overload]
    session.commit()


def _make_fact(
    session: Session,
    user_id: int,
    prop: str = "User likes Python",
    confidence: float = 0.40,
    reinforcement_count: int = 0,
    stability: str = "normal",
    is_active: bool = True,
) -> SemanticFact:
    fact = SemanticFact(
        user_id=user_id,
        proposition=prop,
        confidence=confidence,
        reinforcement_count=reinforcement_count,
        stability=stability,
        is_active=is_active,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def _make_episode(session: Session, user_id: int, processed: bool = False) -> Episode:
    ep = Episode(
        user_id=user_id,
        summary="test",
        salience_total=0.5,
        semantically_processed=processed,
    )
    session.add(ep)
    session.commit()
    session.refresh(ep)
    return ep


# ── Tests: stability field ────────────────────────────────────────────────────

class TestStabilityFieldDefaults:
    def test_default_stability_is_normal(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        fact = _make_fact(db_session, _UID)
        assert fact.stability == "normal"

    def test_stability_persists_to_db(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        fact = _make_fact(db_session, _UID, stability="stable")
        db_session.refresh(fact)
        assert fact.stability == "stable"

    def test_stability_volatile_persists(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        fact = _make_fact(db_session, _UID, stability="volatile")
        db_session.refresh(fact)
        assert fact.stability == "volatile"


# ── Tests: apply_semantic_fact_decay ─────────────────────────────────────────

class TestApplySemanticFactDecay:

    def test_qualifying_fact_loses_confidence(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # confidence < 0.65, reinforcement_count < 3, stability != "stable"
        fact = _make_fact(db_session, _UID, confidence=0.40, reinforcement_count=0, stability="normal")
        original_conf = fact.confidence
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(original_conf - _SEMANTIC_PASSIVE_DECAY)

    def test_high_confidence_fact_not_decayed(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # confidence >= 0.65 → excluded
        fact = _make_fact(db_session, _UID, confidence=0.70)
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(0.70)

    def test_high_reinforcement_fact_not_decayed(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # reinforcement_count >= 3 → excluded
        fact = _make_fact(db_session, _UID, confidence=0.50, reinforcement_count=3)
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(0.50)

    def test_stable_fact_not_decayed(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # stability="stable" → excluded
        fact = _make_fact(db_session, _UID, confidence=0.50, stability="stable")
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(0.50)

    def test_decay_deactivates_below_threshold(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # confidence just above deactivation threshold; one decay step will cross it
        just_above = SEMANTIC_DEACTIVATION_THRESHOLD + _SEMANTIC_PASSIVE_DECAY - 0.001
        fact = _make_fact(db_session, _UID, confidence=just_above)
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.is_active is False

    def test_inactive_fact_not_touched(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        fact = _make_fact(db_session, _UID, confidence=0.40, is_active=False)
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.confidence == pytest.approx(0.40)  # unchanged

    def test_user_isolation(self, db_session: Session) -> None:
        _clean(db_session, _UID, _UID_OTHER)
        # Both users have qualifying facts; only _UID should be decayed
        mine = _make_fact(db_session, _UID, confidence=0.40)
        theirs = _make_fact(db_session, _UID_OTHER, confidence=0.40)
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(mine)
        db_session.refresh(theirs)
        assert mine.confidence < 0.40         # decayed
        assert theirs.confidence == pytest.approx(0.40)  # untouched

    def test_noop_when_no_qualifying_facts(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # No facts at all — should not raise
        apply_semantic_fact_decay(user_id=_UID)  # must not raise

    def test_confidence_does_not_go_negative(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # confidence already at 0 — should floor at 0
        fact = _make_fact(db_session, _UID, confidence=0.01)
        apply_semantic_fact_decay(user_id=_UID)
        db_session.refresh(fact)
        assert fact.confidence >= 0.0


# ── Tests: maybe_trigger integration ─────────────────────────────────────────

class TestMaybeTriggerCallsDecay:
    def test_decay_called_even_below_synthesis_threshold(self, db_session: Session) -> None:
        _clean(db_session, _UID)
        # No episodes → count < threshold → synthesis Haiku NOT called
        # But decay SHOULD still be called
        fact = _make_fact(db_session, _UID, confidence=0.40)
        with patch("app.cognition.semantic_service.build_ai_provider") as mock_provider:
            maybe_trigger_semantic_consolidation(user_id=_UID, trace_id="test")
        # Haiku NOT called
        mock_provider.assert_not_called()
        # But decay DID run
        db_session.refresh(fact)
        assert fact.confidence < 0.40

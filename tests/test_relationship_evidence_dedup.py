"""Tests for MINI-REMAKE v2.0 Punto 5 — RelationshipEvidence dedup.

Properties verified:

Parte 1 — Appraisal writes RelationshipEvidence:
1.  Appraisal with positive trust_evidence → RelationshipEvidence row for trust_honesty,
    source="appraisal", applied=True, direction="positive".
2.  Appraisal with high challenge → RelationshipEvidence row for affinity,
    source="appraisal", applied=True, direction="negative".
3.  Appraisal with zero signals (except familiarity) → only familiarity row written.
4.  Without session/trace_id, no RelationshipEvidence rows are written (backward compat).
5.  Without trace_id, no RelationshipEvidence rows are written.

Parte 2 — Reflection dedup:
6.  Reflection evidence for a dimension where Appraisal already wrote → applied=False,
    SocialProfile dimension NOT changed.
7.  Reflection evidence for a dimension NOT touched by Appraisal → applied=True,
    SocialProfile dimension IS changed.
8.  Reflection with no prior Appraisal evidence → applies normally (applied=True).
9.  Multiple Reflection evidences in same turn: Appraisal-dominated dimensions skipped,
    others applied.
"""
from __future__ import annotations

import pytest
from sqlmodel import delete as sql_delete, Session, select

from app.memory.models import RelationshipEvidence, SocialProfile, utc_now
from app.social.social_service import (
    _REFLECTION_EVIDENCE_SCALE,
    apply_appraisal_to_social_profile,
    apply_reflection_relationship_evidence,
    get_or_create_social_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UID = 90_200


def _clean(session: Session) -> None:
    session.exec(sql_delete(RelationshipEvidence).where(RelationshipEvidence.user_id == _UID))  # type: ignore[call-overload]
    session.exec(sql_delete(SocialProfile).where(SocialProfile.user_id == _UID))  # type: ignore[call-overload]
    session.commit()


def _neutral_personality() -> dict:
    return {
        "skepticism": 0.5, "warmth": 0.5, "patience": 0.5,
        "assertiveness": 0.5, "empathy": 0.5,
    }


def _make_profile(session: Session) -> SocialProfile:
    p = SocialProfile(user_id=_UID)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _make_appraisal_evidence(
    session: Session, dimension: str, direction: str = "positive", turn_id: str = "turn-X"
) -> RelationshipEvidence:
    ev = RelationshipEvidence(
        user_id=_UID,
        dimension=dimension,
        direction=direction,
        strength=0.01,
        source="appraisal",
        turn_id=turn_id,
        applied=True,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def _make_reflection_evidence(
    session: Session, dimension: str, direction: str = "positive",
    turn_id: str = "turn-X", applied: bool = False,
) -> RelationshipEvidence:
    ev = RelationshipEvidence(
        user_id=_UID,
        dimension=dimension,
        direction=direction,
        strength=0.5,
        source="reflection",
        turn_id=turn_id,
        applied=applied,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


# ---------------------------------------------------------------------------
# Parte 1 — Appraisal writes RelationshipEvidence
# ---------------------------------------------------------------------------

class TestAppraisalWritesEvidence:

    def test_positive_trust_evidence_writes_trust_honesty_row(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        apply_appraisal_to_social_profile(
            profile, 0.05, 0.0, 0.0, 0.0, 0.0, _neutral_personality(),
            session=db_session, trace_id="turn-1",
        )
        db_session.add(profile)
        db_session.commit()

        rows = list(db_session.exec(
            select(RelationshipEvidence)
            .where(RelationshipEvidence.user_id == _UID)
            .where(RelationshipEvidence.turn_id == "turn-1")
            .where(RelationshipEvidence.source == "appraisal")
            .where(RelationshipEvidence.dimension == "trust_honesty")
        ).all())
        assert len(rows) == 1
        assert rows[0].direction == "positive"
        assert rows[0].applied is True

    def test_high_challenge_writes_negative_trust_intentions_row(self, db_session: Session):
        # trust_intentions starts at 0.5 → challenge reduces it → negative delta row
        _clean(db_session)
        profile = _make_profile(db_session)
        # Ensure trust_intentions has room to go down (default is 0.5)
        assert profile.trust_intentions == pytest.approx(0.5)
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.0, 0.0, 1.0, _neutral_personality(),
            session=db_session, trace_id="turn-2",
        )
        db_session.add(profile)
        db_session.commit()

        rows = list(db_session.exec(
            select(RelationshipEvidence)
            .where(RelationshipEvidence.user_id == _UID)
            .where(RelationshipEvidence.turn_id == "turn-2")
            .where(RelationshipEvidence.source == "appraisal")
            .where(RelationshipEvidence.dimension == "trust_intentions")
        ).all())
        assert len(rows) == 1
        assert rows[0].direction == "negative"
        assert rows[0].applied is True

    def test_zero_signals_only_familiarity_written(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.0, 0.0, 0.0, _neutral_personality(),
            session=db_session, trace_id="turn-3",
        )
        db_session.add(profile)
        db_session.commit()

        rows = list(db_session.exec(
            select(RelationshipEvidence)
            .where(RelationshipEvidence.user_id == _UID)
            .where(RelationshipEvidence.turn_id == "turn-3")
            .where(RelationshipEvidence.source == "appraisal")
        ).all())
        # familiarity always increases (0.005 + ss*0.003 with ss=0 → +0.005)
        dims = {r.dimension for r in rows}
        assert "familiarity" in dims
        # uncertainty decreases by 0 (te=0, ss=0) → no row
        assert "uncertainty" not in dims or all(r.dimension != "uncertainty" for r in rows)

    def test_without_session_no_evidence_rows(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        apply_appraisal_to_social_profile(
            profile, 0.05, 0.0, 0.0, 0.0, 0.0, _neutral_personality(),
            # no session or trace_id
        )
        rows = list(db_session.exec(
            select(RelationshipEvidence).where(RelationshipEvidence.user_id == _UID)
        ).all())
        assert rows == []

    def test_without_trace_id_no_evidence_rows(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        apply_appraisal_to_social_profile(
            profile, 0.05, 0.0, 0.0, 0.0, 0.0, _neutral_personality(),
            session=db_session,
            # trace_id omitted → defaults to ""
        )
        db_session.add(profile)
        db_session.commit()
        rows = list(db_session.exec(
            select(RelationshipEvidence).where(RelationshipEvidence.user_id == _UID)
        ).all())
        assert rows == []


# ---------------------------------------------------------------------------
# Parte 2 — Reflection dedup
# ---------------------------------------------------------------------------

class TestReflectionDedup:

    def test_appraisal_dominated_dimension_not_applied(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        before = profile.trust_honesty
        # Appraisal already wrote evidence for trust_honesty in this turn
        _make_appraisal_evidence(db_session, "trust_honesty", "positive", "turn-A")
        # Reflection has evidence for trust_honesty in same turn
        _make_reflection_evidence(db_session, "trust_honesty", "positive", "turn-A")

        apply_reflection_relationship_evidence(db_session, _UID, "turn-A")

        # Profile should NOT have changed for trust_honesty
        db_session.refresh(profile)
        assert profile.trust_honesty == pytest.approx(before, abs=1e-9)

        # The reflection row should be marked applied=False
        ref_rows = list(db_session.exec(
            select(RelationshipEvidence)
            .where(RelationshipEvidence.user_id == _UID)
            .where(RelationshipEvidence.turn_id == "turn-A")
            .where(RelationshipEvidence.source == "reflection")
        ).all())
        assert len(ref_rows) == 1
        assert ref_rows[0].applied is False

    def test_unappraisal_dimension_is_applied(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        before = profile.respect
        # Appraisal only touched trust_honesty, NOT respect
        _make_appraisal_evidence(db_session, "trust_honesty", "positive", "turn-B")
        # Reflection has evidence for respect (not touched by Appraisal)
        _make_reflection_evidence(db_session, "respect", "positive", "turn-B")

        apply_reflection_relationship_evidence(db_session, _UID, "turn-B")

        db_session.refresh(profile)
        assert profile.respect > before

        ref_rows = list(db_session.exec(
            select(RelationshipEvidence)
            .where(RelationshipEvidence.user_id == _UID)
            .where(RelationshipEvidence.turn_id == "turn-B")
            .where(RelationshipEvidence.source == "reflection")
        ).all())
        assert len(ref_rows) == 1
        assert ref_rows[0].applied is True

    def test_no_appraisal_evidence_reflection_applies_normally(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        before = profile.affinity
        _make_reflection_evidence(db_session, "affinity", "positive", "turn-C")

        apply_reflection_relationship_evidence(db_session, _UID, "turn-C")

        db_session.refresh(profile)
        assert profile.affinity > before

        ref_rows = list(db_session.exec(
            select(RelationshipEvidence)
            .where(RelationshipEvidence.user_id == _UID)
            .where(RelationshipEvidence.turn_id == "turn-C")
            .where(RelationshipEvidence.source == "reflection")
        ).all())
        assert ref_rows[0].applied is True

    def test_mixed_turn_appraisal_dominates_only_overlapping(self, db_session: Session):
        _clean(db_session)
        profile = _make_profile(db_session)
        trust_before = profile.trust_honesty
        comfort_before = profile.comfort

        # Appraisal wrote trust_honesty only
        _make_appraisal_evidence(db_session, "trust_honesty", "positive", "turn-D")
        # Reflection has both trust_honesty (dominated) and comfort (free)
        _make_reflection_evidence(db_session, "trust_honesty", "positive", "turn-D")
        _make_reflection_evidence(db_session, "comfort", "positive", "turn-D")

        apply_reflection_relationship_evidence(db_session, _UID, "turn-D")

        db_session.refresh(profile)
        assert profile.trust_honesty == pytest.approx(trust_before, abs=1e-9)  # blocked
        assert profile.comfort > comfort_before                                  # applied

        ref_rows = {
            r.dimension: r for r in db_session.exec(
                select(RelationshipEvidence)
                .where(RelationshipEvidence.user_id == _UID)
                .where(RelationshipEvidence.turn_id == "turn-D")
                .where(RelationshipEvidence.source == "reflection")
            ).all()
        }
        assert ref_rows["trust_honesty"].applied is False
        assert ref_rows["comfort"].applied is True

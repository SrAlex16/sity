"""Tests for AutobiographicalNarrative generation (Remake Fase 4 Parte 3).

Properties verified:

1.  No narrative if insufficient muy_alta episodes (< narrative_min_muy_alta_episodes).
2.  Narrative created when >= min muy_alta episodes and no prior narrative.
3.  Narrative NOT created if prior narrative is < 7 days old (age gate).
4.  Narrative created if prior narrative is >= 7 days old AND enough new episodes.
5.  Prior narrative superseded (superseded_at set) when new one is created.
6.  important_episode_ids_json contains episode IDs that triggered generation.
7.  period is the correct quarter string for the current date.
8.  Narrative generation failure does not block the social update job.
9.  _get_current_quarter returns correct strings for all four quarters.
10. _has_narrative_signal: False when count < min, True when count >= min.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import (
    AutobiographicalNarrative,
    Episode,
    SocialProfile,
    utc_now,
)
from app.social.update import (
    _get_current_quarter,
    _get_latest_active_narrative,
    _has_narrative_signal,
    _run_social_update,
    _NARRATIVE_MIN_EPISODES,
    _NARRATIVE_MIN_DAYS,
    _SALIENCE_MUY_ALTA,
)


_FAKE_NARRATIVE = "Este interlocutor se centra en temas técnicos y creativos con curiosidad constante."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_profile(user_id: int, pending_loads: list[int] | None = None) -> int:
    loads = json.dumps(pending_loads if pending_loads is not None else [1])
    with Session(engine) as db:
        existing = db.exec(
            select(SocialProfile).where(SocialProfile.user_id == user_id)
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        profile = SocialProfile(
            user_id=user_id,
            pending_loads_json=loads,
            created_at=utc_now() - timedelta(days=10),
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile.id  # type: ignore[return-value]


def _seed_muy_alta_episodes(user_id: int, n: int, *, offset_days: int = 0) -> list[int]:
    """Insert n muy_alta Episodes for user_id. Returns list of inserted IDs."""
    ids = []
    with Session(engine) as db:
        for i in range(n):
            ep = Episode(
                user_id=user_id,
                occurred_at=utc_now() - timedelta(days=offset_days),
                summary=f"Momento significativo {i}",
                salience_total=0.80,  # muy_alta
                strength=1.0,
            )
            db.add(ep)
            db.flush()
            ids.append(ep.id)
        db.commit()
    return ids


def _delete_narratives(user_id: int) -> None:
    with Session(engine) as db:
        db.execute(
            sa_text("DELETE FROM autobiographicalnarrative WHERE user_id = :uid"),
            {"uid": user_id},
        )
        db.commit()


def _delete_episodes(user_id: int) -> None:
    with Session(engine) as db:
        db.execute(
            sa_text("DELETE FROM episode WHERE user_id = :uid"),
            {"uid": user_id},
        )
        db.commit()


def _count_narratives(user_id: int) -> int:
    with Session(engine) as db:
        return db.execute(
            sa_text("SELECT COUNT(*) FROM autobiographicalnarrative WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar() or 0


def _get_active_narrative(user_id: int) -> AutobiographicalNarrative | None:
    with Session(engine) as db:
        return _get_latest_active_narrative(user_id, db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_narrative_if_insufficient_episodes() -> None:
    uid = 9201
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)
    # Seed fewer than minimum (default 3)
    _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES - 1)

    with patch("app.social.update._generate_narrative_content") as mock_gen:
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_001")

    mock_gen.assert_not_called()
    assert _count_narratives(uid) == 0

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_narrative_created_when_enough_episodes_no_prior() -> None:
    uid = 9202
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)
    ep_ids = _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES)

    with patch(
        "app.social.update._generate_narrative_content",
        return_value=_FAKE_NARRATIVE,
    ):
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_002")

    narrative = _get_active_narrative(uid)
    assert narrative is not None, "AutobiographicalNarrative should have been created"
    assert narrative.narrative == _FAKE_NARRATIVE
    assert narrative.superseded_at is None
    stored_ids = json.loads(narrative.important_episode_ids_json)
    assert isinstance(stored_ids, list)
    assert len(stored_ids) > 0

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_narrative_not_created_if_prior_too_recent() -> None:
    uid = 9203
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)
    _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES + 2)

    # Insert a prior narrative created 3 days ago (< 7 day gate)
    with Session(engine) as db:
        db.add(AutobiographicalNarrative(
            user_id=uid,
            period="2026-Q3",
            narrative="Old narrative.",
            created_at=utc_now() - timedelta(days=3),
        ))
        db.commit()

    with patch("app.social.update._generate_narrative_content") as mock_gen:
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_003")

    mock_gen.assert_not_called()
    assert _count_narratives(uid) == 1  # only the prior one, no new

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_narrative_created_if_prior_old_enough() -> None:
    uid = 9204
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)

    # Insert an old prior narrative (8 days ago)
    with Session(engine) as db:
        db.add(AutobiographicalNarrative(
            user_id=uid,
            period="2026-Q3",
            narrative="Old narrative.",
            created_at=utc_now() - timedelta(days=8),
        ))
        db.commit()

    # Seed new muy_alta episodes (they occur after the prior narrative)
    _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES)

    with patch(
        "app.social.update._generate_narrative_content",
        return_value=_FAKE_NARRATIVE,
    ):
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_004")

    assert _count_narratives(uid) == 2  # old + new

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_prior_narrative_superseded_on_new_generation() -> None:
    uid = 9205
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)

    # Prior narrative, old enough
    with Session(engine) as db:
        db.add(AutobiographicalNarrative(
            user_id=uid,
            period="2026-Q2",
            narrative="Anterior narrative.",
            created_at=utc_now() - timedelta(days=10),
        ))
        db.commit()

    _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES)

    with patch(
        "app.social.update._generate_narrative_content",
        return_value=_FAKE_NARRATIVE,
    ):
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_005")

    # Active (non-superseded) narrative should be exactly 1 and be the new one
    active = _get_active_narrative(uid)
    assert active is not None
    assert active.narrative == _FAKE_NARRATIVE
    assert active.superseded_at is None

    # The old one should now be superseded
    with Session(engine) as db:
        old = db.exec(
            select(AutobiographicalNarrative)
            .where(AutobiographicalNarrative.user_id == uid)
            .where(AutobiographicalNarrative.narrative == "Anterior narrative.")
        ).first()
    assert old is not None
    assert old.superseded_at is not None

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_episode_ids_stored_in_narrative() -> None:
    uid = 9206
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)
    inserted_ids = _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES)

    with patch(
        "app.social.update._generate_narrative_content",
        return_value=_FAKE_NARRATIVE,
    ):
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_006")

    narrative = _get_active_narrative(uid)
    assert narrative is not None
    stored_ids = json.loads(narrative.important_episode_ids_json)
    assert set(stored_ids).issubset(set(inserted_ids))
    assert len(stored_ids) == len(inserted_ids)

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_period_is_correct_quarter() -> None:
    uid = 9207
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)
    _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES)

    with patch(
        "app.social.update._generate_narrative_content",
        return_value=_FAKE_NARRATIVE,
    ):
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_007")

    narrative = _get_active_narrative(uid)
    assert narrative is not None
    # Period should be a string like "YYYY-Qn"
    assert narrative.period.startswith("20")
    assert "-Q" in narrative.period

    _delete_episodes(uid)
    _delete_narratives(uid)


def test_narrative_failure_does_not_block_job() -> None:
    uid = 9208
    _setup_profile(uid, pending_loads=[1])
    _delete_narratives(uid)
    _delete_episodes(uid)
    _seed_muy_alta_episodes(uid, _NARRATIVE_MIN_EPISODES)

    with patch(
        "app.social.update._generate_narrative_content",
        side_effect=RuntimeError("Haiku exploded"),
    ):
        with patch("app.social.update._generate_reflection_content", return_value=None):
            _run_social_update(uid, "trc_narr_008")  # must not raise

    assert _count_narratives(uid) == 0

    _delete_episodes(uid)
    _delete_narratives(uid)


# ---------------------------------------------------------------------------
# Unit tests for helper functions (no DB needed)
# ---------------------------------------------------------------------------

class TestGetCurrentQuarter:
    def test_q1_january(self):
        dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
        assert _get_current_quarter(dt) == "2026-Q1"

    def test_q1_march(self):
        dt = datetime(2026, 3, 31, tzinfo=timezone.utc)
        assert _get_current_quarter(dt) == "2026-Q1"

    def test_q2_april(self):
        dt = datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert _get_current_quarter(dt) == "2026-Q2"

    def test_q3_september(self):
        dt = datetime(2026, 9, 9, tzinfo=timezone.utc)
        assert _get_current_quarter(dt) == "2026-Q3"

    def test_q4_december(self):
        dt = datetime(2026, 12, 31, tzinfo=timezone.utc)
        assert _get_current_quarter(dt) == "2026-Q4"

    def test_default_arg_returns_string(self):
        result = _get_current_quarter()
        assert isinstance(result, str)
        assert "-Q" in result


class TestHasNarrativeSignal:
    _UID = 9290

    def _cleanup(self) -> None:
        with Session(engine) as db:
            db.execute(sa_text("DELETE FROM episode WHERE user_id = :uid"), {"uid": self._UID})
            db.execute(
                sa_text("DELETE FROM autobiographicalnarrative WHERE user_id = :uid"),
                {"uid": self._UID},
            )
            db.commit()

    def test_false_when_no_episodes(self):
        self._cleanup()
        cfg = {"narrative_min_muy_alta_episodes": 3, "narrative_min_days_since_last": 7}
        with Session(engine) as db:
            result = _has_narrative_signal(self._UID, None, cfg, db)
        assert result is False
        self._cleanup()

    def test_true_when_enough_episodes_no_prior(self):
        self._cleanup()
        with Session(engine) as db:
            for _ in range(3):
                db.add(Episode(
                    user_id=self._UID,
                    summary="x",
                    salience_total=0.80,
                    strength=1.0,
                ))
            db.commit()
        cfg = {"narrative_min_muy_alta_episodes": 3, "narrative_min_days_since_last": 7}
        with Session(engine) as db:
            result = _has_narrative_signal(self._UID, None, cfg, db)
        assert result is True
        self._cleanup()

    def test_false_when_prior_too_recent(self):
        self._cleanup()
        with Session(engine) as db:
            for _ in range(5):
                db.add(Episode(
                    user_id=self._UID,
                    summary="x",
                    salience_total=0.80,
                    strength=1.0,
                ))
            recent = AutobiographicalNarrative(
                user_id=self._UID,
                period="2026-Q3",
                narrative="recent",
                created_at=utc_now() - timedelta(days=2),
            )
            db.add(recent)
            db.commit()
            db.refresh(recent)
        cfg = {"narrative_min_muy_alta_episodes": 3, "narrative_min_days_since_last": 7}
        with Session(engine) as db:
            latest = _get_latest_active_narrative(self._UID, db)
            result = _has_narrative_signal(self._UID, latest, cfg, db)
        assert result is False
        self._cleanup()

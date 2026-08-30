"""Tests for Achievements Paso 2 Fase 2b — post-turn and secondary inline triggers.

Coverage:
  - Personality post-turn: who_am_i, chaos_head
  - Social post-turn: remember_me, love_is_war, its_over_9000, redemption, schizophrenia
  - Account-age post-turn: a_long_time_ago
  - Consecutive-refusal counter: get_in_the_robot
  - Catalog entries: the_memory_remains, youre_finally_awake
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.achievements.catalog import VALID_SLUGS
from app.achievements.triggers.post_turn import (
    _check_account_age,
    _check_personality,
    _check_social,
)
from app.achievements.unlock import get_user_achievements, try_unlock_achievement
from app.core.refusal_tracker import (
    get_consecutive_refusals,
    increment_consecutive_refusals,
    reset_consecutive_refusals,
)
from app.memory.db import engine
from app.memory.models import OpinionSnapshot, SocialProfile, User
from app.settings.settings_service import CANONICAL_PERSONALITY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> int:
    return abs(hash(uuid.uuid4())) % 2_000_000 + 5_000_000


def _unlocked(db: Session, user_id: int) -> set[str]:
    return {a["slug"] for a in get_user_achievements(db, user_id) if a["unlocked"]}


def _cfg() -> dict:
    return {
        "who_am_i_distance_threshold": 0.5,
        "chaos_head_threshold": 0.95,
        "remember_me_trust_threshold": 0.30,
        "opinion_negative_threshold": -0.5,
        "opinion_extreme_threshold": -1.5,
        "schizophrenia_min_flips": 3,
        "account_age_days": 30,
    }


def _unlock(db, user_id, slug):
    return try_unlock_achievement(db, user_id, slug)


def _personality(overrides: dict) -> dict:
    return {**CANONICAL_PERSONALITY, **overrides}


def _create_profile(db: Session, user_id: int, opinion: float, trust: float) -> SocialProfile:
    profile = SocialProfile(user_id=user_id, opinion=opinion, trust=trust)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _add_snapshot(db: Session, profile_id: int, opinion_value: float, days_ago: int = 0) -> None:
    ts = datetime.utcnow() - timedelta(days=days_ago)
    db.add(OpinionSnapshot(profile_id=profile_id, opinion_value=opinion_value, trust_value=0.0, computed_at=ts))
    db.commit()


def _create_user(db: Session, days_old: int) -> int:
    created = datetime.utcnow() - timedelta(days=days_old)
    user = User(email=f"pt_{uuid.uuid4().hex}@test.com", password_hash="x", created_at=created)
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.id is not None
    return user.id


# ---------------------------------------------------------------------------
# Catalog: all Fase 2b slugs are registered
# ---------------------------------------------------------------------------

FASE2B_SLUGS = [
    "who_am_i", "chaos_head",
    "remember_me", "love_is_war", "its_over_9000", "redemption", "schizophrenia",
    "a_long_time_ago", "youre_finally_awake", "get_in_the_robot", "the_memory_remains",
]


@pytest.mark.parametrize("slug", FASE2B_SLUGS)
def test_fase2b_slug_in_catalog(slug: str) -> None:
    assert slug in VALID_SLUGS, f"Slug '{slug}' missing from catalog"


# ---------------------------------------------------------------------------
# Personality — who_am_i
# ---------------------------------------------------------------------------

def test_who_am_i_unlocks_when_distance_above_threshold() -> None:
    uid = _uid()
    # Six sliders at 1.0 → normalized euclidean distance ≈ 0.548 > threshold 0.5
    p = _personality({
        "sarcasm_level": 1.0, "rudeness_level": 1.0, "contrarian_level": 1.0,
        "initiative_level": 1.0, "dry_humor_level": 1.0, "melancholy_level": 1.0,
    })
    with Session(engine) as db:
        with patch("app.settings.settings_service.SettingsService.get_personality", return_value=p):
            _check_personality(db, uid, _cfg(), _unlock)
        assert "who_am_i" in _unlocked(db, uid)


def test_who_am_i_no_unlock_at_canonical() -> None:
    uid = _uid()
    with Session(engine) as db:
        with patch("app.settings.settings_service.SettingsService.get_personality", return_value=dict(CANONICAL_PERSONALITY)):
            _check_personality(db, uid, _cfg(), _unlock)
        assert "who_am_i" not in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# Personality — chaos_head
# ---------------------------------------------------------------------------

def test_chaos_head_unlocks_at_max_values() -> None:
    uid = _uid()
    p = _personality({"rudeness_level": 1.0, "sarcasm_level": 1.0, "contrarian_level": 1.0, "dry_humor_level": 1.0})
    with Session(engine) as db:
        with patch("app.settings.settings_service.SettingsService.get_personality", return_value=p):
            _check_personality(db, uid, _cfg(), _unlock)
        assert "chaos_head" in _unlocked(db, uid)


def test_chaos_head_no_unlock_below_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        with patch("app.settings.settings_service.SettingsService.get_personality", return_value=dict(CANONICAL_PERSONALITY)):
            _check_personality(db, uid, _cfg(), _unlock)
        assert "chaos_head" not in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# Social — remember_me
# ---------------------------------------------------------------------------

def test_remember_me_unlocks_at_trust_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=0.0, trust=0.30)
        _check_social(db, uid, _cfg(), _unlock)
        assert "remember_me" in _unlocked(db, uid)


def test_remember_me_no_unlock_below_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=0.0, trust=0.29)
        _check_social(db, uid, _cfg(), _unlock)
        assert "remember_me" not in _unlocked(db, uid)


def test_remember_me_no_profile_no_unlock() -> None:
    uid = _uid()
    with Session(engine) as db:
        _check_social(db, uid, _cfg(), _unlock)
        assert "remember_me" not in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# Social — love_is_war
# ---------------------------------------------------------------------------

def test_love_is_war_unlocks_at_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=-0.5, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        assert "love_is_war" in _unlocked(db, uid)


def test_love_is_war_unlocks_below_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=-1.0, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        assert "love_is_war" in _unlocked(db, uid)


def test_love_is_war_no_unlock_above_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=-0.4, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        assert "love_is_war" not in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# Social — its_over_9000
# ---------------------------------------------------------------------------

def test_its_over_9000_unlocks_at_extreme_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=-1.5, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        assert "its_over_9000" in _unlocked(db, uid)


def test_its_over_9000_no_unlock_above_extreme_threshold() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=-0.5, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        assert "its_over_9000" not in _unlocked(db, uid)


def test_its_over_9000_also_unlocks_love_is_war() -> None:
    """opinion ≤ -1.5 satisfies both love_is_war and its_over_9000."""
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=-2.0, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        slugs = _unlocked(db, uid)
        assert "love_is_war" in slugs
        assert "its_over_9000" in slugs


# ---------------------------------------------------------------------------
# Social — redemption
# ---------------------------------------------------------------------------

def test_redemption_unlocks_when_snapshot_negative_and_current_positive() -> None:
    uid = _uid()
    with Session(engine) as db:
        profile = _create_profile(db, uid, opinion=0.3, trust=0.0)
        _add_snapshot(db, profile.id, opinion_value=-0.5)
        _check_social(db, uid, _cfg(), _unlock)
        assert "redemption" in _unlocked(db, uid)


def test_redemption_no_unlock_when_snapshot_positive() -> None:
    uid = _uid()
    with Session(engine) as db:
        profile = _create_profile(db, uid, opinion=0.3, trust=0.0)
        _add_snapshot(db, profile.id, opinion_value=0.5)
        _check_social(db, uid, _cfg(), _unlock)
        assert "redemption" not in _unlocked(db, uid)


def test_redemption_no_unlock_with_no_snapshots() -> None:
    uid = _uid()
    with Session(engine) as db:
        _create_profile(db, uid, opinion=0.3, trust=0.0)
        _check_social(db, uid, _cfg(), _unlock)
        assert "redemption" not in _unlocked(db, uid)


def test_redemption_no_unlock_when_current_still_negative() -> None:
    uid = _uid()
    with Session(engine) as db:
        profile = _create_profile(db, uid, opinion=-0.1, trust=0.0)
        _add_snapshot(db, profile.id, opinion_value=-0.5)
        _check_social(db, uid, _cfg(), _unlock)
        assert "redemption" not in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# Social — schizophrenia
# ---------------------------------------------------------------------------

def test_schizophrenia_unlocks_with_three_sign_flips() -> None:
    uid = _uid()
    # DESC order (newest first): [+0.5, -0.5, +0.5, -0.5] → 3 flips
    with Session(engine) as db:
        profile = _create_profile(db, uid, opinion=0.0, trust=0.0)
        for days_ago, val in enumerate([0.5, -0.5, 0.5, -0.5]):
            _add_snapshot(db, profile.id, opinion_value=val, days_ago=days_ago)
        _check_social(db, uid, _cfg(), _unlock)
        assert "schizophrenia" in _unlocked(db, uid)


def test_schizophrenia_no_unlock_with_two_flips() -> None:
    uid = _uid()
    # DESC order: [+0.5, -0.5, +0.5] → 2 flips — below threshold
    with Session(engine) as db:
        profile = _create_profile(db, uid, opinion=0.0, trust=0.0)
        for days_ago, val in enumerate([0.5, -0.5, 0.5]):
            _add_snapshot(db, profile.id, opinion_value=val, days_ago=days_ago)
        _check_social(db, uid, _cfg(), _unlock)
        assert "schizophrenia" not in _unlocked(db, uid)


def test_schizophrenia_no_unlock_with_single_snapshot() -> None:
    uid = _uid()
    with Session(engine) as db:
        profile = _create_profile(db, uid, opinion=0.0, trust=0.0)
        _add_snapshot(db, profile.id, opinion_value=0.5)
        _check_social(db, uid, _cfg(), _unlock)
        assert "schizophrenia" not in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# Account age — a_long_time_ago
# ---------------------------------------------------------------------------

def test_a_long_time_ago_unlocks_after_30_days() -> None:
    with Session(engine) as db:
        uid = _create_user(db, days_old=31)
        _check_account_age(db, uid, _cfg(), _unlock)
        assert "a_long_time_ago" in _unlocked(db, uid)


def test_a_long_time_ago_no_unlock_before_30_days() -> None:
    with Session(engine) as db:
        uid = _create_user(db, days_old=29)
        _check_account_age(db, uid, _cfg(), _unlock)
        assert "a_long_time_ago" not in _unlocked(db, uid)


def test_a_long_time_ago_no_unlock_user_not_found() -> None:
    uid = 9_888_777
    with Session(engine) as db:
        _check_account_age(db, uid, _cfg(), _unlock)
        assert "a_long_time_ago" not in _unlocked(db, uid)


def test_a_long_time_ago_idempotent() -> None:
    with Session(engine) as db:
        uid = _create_user(db, days_old=31)
        _check_account_age(db, uid, _cfg(), _unlock)
        _check_account_age(db, uid, _cfg(), _unlock)  # second call — no duplicate
        assert "a_long_time_ago" in _unlocked(db, uid)


# ---------------------------------------------------------------------------
# get_in_the_robot — consecutive refusal counter
# ---------------------------------------------------------------------------

def test_refusal_counter_increments() -> None:
    sid = f"user:{_uid()}"
    try:
        assert increment_consecutive_refusals(sid) == 1
        assert increment_consecutive_refusals(sid) == 2
        assert increment_consecutive_refusals(sid) == 3
    finally:
        reset_consecutive_refusals(sid)


def test_refusal_counter_resets_to_zero() -> None:
    sid = f"user:{_uid()}"
    increment_consecutive_refusals(sid)
    increment_consecutive_refusals(sid)
    reset_consecutive_refusals(sid)
    assert get_consecutive_refusals(sid) == 0


def test_refusal_counter_new_session_starts_at_zero() -> None:
    sid = f"user:{_uid()}"
    assert get_consecutive_refusals(sid) == 0


def test_refusal_counter_sessions_are_isolated() -> None:
    sid_a = f"user:{_uid()}"
    sid_b = f"user:{_uid()}"
    try:
        increment_consecutive_refusals(sid_a)
        increment_consecutive_refusals(sid_a)
        assert get_consecutive_refusals(sid_b) == 0
    finally:
        reset_consecutive_refusals(sid_a)


def test_get_in_the_robot_fires_on_third_consecutive_refusal() -> None:
    from app.achievements.triggers.inline import fire
    uid = _uid()
    sid = f"user:{uid}"
    try:
        increment_consecutive_refusals(sid)
        increment_consecutive_refusals(sid)
        count = increment_consecutive_refusals(sid)
        assert count >= 3
        with Session(engine) as db:
            assert fire(db, sid, "get_in_the_robot") is True
    finally:
        reset_consecutive_refusals(sid)


def test_get_in_the_robot_idempotent_after_unlock() -> None:
    from app.achievements.triggers.inline import fire
    uid = _uid()
    sid = f"user:{uid}"
    with Session(engine) as db:
        fire(db, sid, "get_in_the_robot")
        result = fire(db, sid, "get_in_the_robot")
        assert result is False


# ---------------------------------------------------------------------------
# the_memory_remains and youre_finally_awake — catalog + fire smoke tests
# ---------------------------------------------------------------------------

def test_the_memory_remains_fire_returns_true_first_call() -> None:
    from app.achievements.triggers.inline import fire
    uid = _uid()
    with Session(engine) as db:
        assert fire(db, f"user:{uid}", "the_memory_remains") is True


def test_the_memory_remains_fire_idempotent() -> None:
    from app.achievements.triggers.inline import fire
    uid = _uid()
    with Session(engine) as db:
        fire(db, f"user:{uid}", "the_memory_remains")
        assert fire(db, f"user:{uid}", "the_memory_remains") is False


def test_youre_finally_awake_fire_returns_true_first_call() -> None:
    from app.achievements.triggers.inline import fire
    uid = _uid()
    with Session(engine) as db:
        assert fire(db, f"user:{uid}", "youre_finally_awake") is True


def test_youre_finally_awake_fire_idempotent() -> None:
    from app.achievements.triggers.inline import fire
    uid = _uid()
    with Session(engine) as db:
        fire(db, f"user:{uid}", "youre_finally_awake")
        assert fire(db, f"user:{uid}", "youre_finally_awake") is False

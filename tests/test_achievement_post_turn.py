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
from app.memory.models import SocialProfile, User
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


def _create_profile(db: Session, user_id: int) -> SocialProfile:
    """Create a SocialProfile with new multidimensional defaults."""
    profile = SocialProfile(user_id=user_id)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


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
    # Six high-canonical traits at 0.0 → normalized euclidean distance ≈ 0.55 > threshold 0.5
    p = _personality({
        "independence": 0.0, "skepticism": 0.0, "curiosity": 0.0,
        "honesty": 0.0, "directness": 0.0, "helpfulness": 0.0,
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
    # playfulness*0.35 + (1-warmth)*0.30 + assertiveness*0.20 + independence*0.15
    # = 1.0*0.35 + 1.0*0.30 + 1.0*0.20 + 1.0*0.15 = 1.0 >= 0.95
    p = _personality({"playfulness": 1.0, "warmth": 0.0, "assertiveness": 1.0, "independence": 1.0})
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
# Social — Fase 3 Paso 2: fórmulas pendientes de confirmación explícita
#
# _check_social() is currently a no-op (returns early) — formulas for the 5
# social achievements (remember_me, love_is_war, its_over_9000, redemption,
# schizophrenia) will be reimplemented with the new SocialProfile dimensions
# once the user explicitly confirms them in Paso 2.
# ---------------------------------------------------------------------------

def test_check_social_is_noop_unlocks_nothing() -> None:
    """_check_social must be a no-op: it should not unlock any social achievement."""
    uid = _uid()
    social_slugs = {"remember_me", "love_is_war", "its_over_9000", "redemption", "schizophrenia"}
    with Session(engine) as db:
        _create_profile(db, uid)
        _check_social(db, uid, _cfg(), _unlock)
        assert _unlocked(db, uid).isdisjoint(social_slugs), (
            "_check_social must not unlock social achievements until Paso 2 formulas are confirmed"
        )


def test_check_social_does_not_raise() -> None:
    """_check_social must never raise regardless of profile state."""
    uid = _uid()
    with Session(engine) as db:
        _check_social(db, uid, _cfg(), _unlock)  # no profile — must not raise
        _create_profile(db, uid)
        _check_social(db, uid, _cfg(), _unlock)  # with profile — must not raise


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


# ---------------------------------------------------------------------------
# chaos_head — session_id scope regression
# Ensures _check_personality reads session-scoped settings, not global defaults.
# Reproduces the bug where session_id=None was passed instead of f"user:{uid}",
# causing chaos_head to never unlock even when the user had max encabronamiento.
# ---------------------------------------------------------------------------

def test_chaos_head_uses_session_settings_not_global_defaults() -> None:
    """Global settings below threshold, session settings above — chaos_head must fire."""
    from app.settings.settings_service import SettingsService, CANONICAL_PERSONALITY

    uid = _uid()
    session_id = f"user:{uid}"
    # Params used by the Remake Fase 1 chaos formula
    chaos_params = ["playfulness", "warmth", "assertiveness", "independence"]

    with Session(engine) as db:
        svc = SettingsService(db)

        # Snapshot current global values so we can restore them after the test
        orig_globals = {p: CANONICAL_PERSONALITY[p] for p in chaos_params}

        try:
            # Global settings: values that do NOT cross the 0.95 chaos threshold
            # chaos = 0.2*0.35 + (1-0.8)*0.30 + 0.1*0.20 + 0.1*0.15 ≈ 0.165
            for param, val in [
                ("playfulness", 0.2),
                ("warmth", 0.8),
                ("assertiveness", 0.1),
                ("independence", 0.1),
            ]:
                svc.set_setting(f"personality.{param}", val, source="test", session_id=None)
            db.commit()

            # Session settings: values that DO cross the 0.95 chaos threshold
            # chaos = 1.0*0.35 + (1-0.0)*0.30 + 1.0*0.20 + 1.0*0.15 = 1.0
            for param, val in [
                ("playfulness", 1.0),
                ("warmth", 0.0),
                ("assertiveness", 1.0),
                ("independence", 1.0),
            ]:
                svc.set_setting(f"personality.{param}", val, source="test", session_id=session_id)
            db.commit()

            # Call without mocking — must read real DB and use session scope
            _check_personality(db, uid, _cfg(), _unlock)

            assert "chaos_head" in _unlocked(db, uid), (
                "chaos_head must unlock when session-scoped personality exceeds threshold; "
                "if it doesn't, _check_personality is reading the wrong session_id scope."
            )
        finally:
            # Restore global settings to canonical values so other tests are not affected
            for param, val in orig_globals.items():
                svc.set_setting(f"personality.{param}", val, source="test", session_id=None)
            db.commit()

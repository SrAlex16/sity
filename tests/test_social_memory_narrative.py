"""Tests for Social Memory Narrative — SocialReflection (§12 of design doc).

1. test_reflection_not_generated_if_insufficient_signal
2. test_reflection_generated_after_enough_messages
3. test_reflection_generated_on_large_opinion_delta
4. test_old_reflection_superseded_on_new_generation
5. test_expired_reflection_not_injected
6. test_active_reflection_injected_in_prompt
7. test_reflection_generation_failure_does_not_block_job
8. test_guest_never_gets_reflection
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
    ChatMessage,
    SocialProfile,
    SocialReflection,
    utc_now,
)
from app.social.update import _run_social_update


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_CONTENT = "Este usuario hace preguntas técnicas claras y acepta las sugerencias sin resistencia."


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _setup_profile(user_id: int, pending_loads: list[int] | None = None) -> int:
    """Insert (or replace) a SocialProfile, return profile.id."""
    loads = json.dumps(pending_loads or [1])
    with Session(engine) as db:
        existing = db.exec(
            select(SocialProfile).where(SocialProfile.user_id == user_id)
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
        profile = SocialProfile(
            user_id=user_id,
            opinion=0.0,
            trust=0.0,
            pending_loads_json=loads,
            created_at=utc_now() - timedelta(days=10),
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile.id  # type: ignore[return-value]


def _seed_messages(user_id: int, n: int) -> None:
    """Insert n ChatMessage rows for user:{user_id}, purging any existing ones first."""
    session_id = f"user:{user_id}"
    with Session(engine) as db:
        db.execute(
            sa_text("DELETE FROM chatmessage WHERE session_id = :sid"),
            {"sid": session_id},
        )
        db.commit()
        for i in range(n):
            db.add(ChatMessage(
                session_id=session_id,
                role="user" if i % 2 == 0 else "sity",
                text=f"Mensaje {i}",
            ))
        db.commit()


def _delete_reflections(profile_id: int) -> None:
    with Session(engine) as db:
        db.execute(
            sa_text("DELETE FROM socialreflection WHERE profile_id = :pid"),
            {"pid": profile_id},
        )
        db.commit()


def _count_reflections(profile_id: int) -> int:
    with Session(engine) as db:
        return db.execute(
            sa_text("SELECT COUNT(*) FROM socialreflection WHERE profile_id = :pid"),
            {"pid": profile_id},
        ).scalar() or 0


def _get_active_reflection(profile_id: int) -> SocialReflection | None:
    now = utc_now()
    with Session(engine) as db:
        return db.exec(
            select(SocialReflection)
            .where(SocialReflection.profile_id == profile_id)
            .where(SocialReflection.superseded_at == None)  # noqa: E711
            .where(SocialReflection.expires_at > now)
        ).first()


# ---------------------------------------------------------------------------
# 1. Insufficient signal → no reflection generated
# ---------------------------------------------------------------------------

def test_reflection_not_generated_if_insufficient_signal() -> None:
    uid = 8801
    profile_id = _setup_profile(uid, pending_loads=[1])
    _delete_reflections(profile_id)
    # Seed fewer messages than reflection_min_new_messages (default 20)
    _seed_messages(uid, 5)

    with patch("app.social.update._generate_reflection_content") as mock_gen:
        _run_social_update(uid, "trc_narr_test_1")

    mock_gen.assert_not_called()
    assert _count_reflections(profile_id) == 0


# ---------------------------------------------------------------------------
# 2. Enough messages → reflection generated
# ---------------------------------------------------------------------------

def test_reflection_generated_after_enough_messages() -> None:
    uid = 8802
    profile_id = _setup_profile(uid, pending_loads=[1])
    _delete_reflections(profile_id)
    _seed_messages(uid, 20)

    with patch(
        "app.social.update._generate_reflection_content",
        return_value=_FAKE_CONTENT,
    ):
        _run_social_update(uid, "trc_narr_test_2")

    ref = _get_active_reflection(profile_id)
    assert ref is not None, "SocialReflection should have been created"
    assert ref.content == _FAKE_CONTENT
    assert ref.category == "general"
    assert ref.superseded_at is None
    evidence = json.loads(ref.evidence_json)
    assert isinstance(evidence, list) and len(evidence) > 0
    # expires_at ≈ now + 30 days (within 60 s tolerance)
    now = utc_now()
    assert abs((_utc(ref.expires_at) - now).days - 30) <= 1


# ---------------------------------------------------------------------------
# 3. Large opinion delta → reflection generated even with fewer messages
# ---------------------------------------------------------------------------

def test_reflection_generated_on_large_opinion_delta() -> None:
    uid = 8803
    profile_id = _setup_profile(uid, pending_loads=[2, 2, 2, 2, 2])
    _delete_reflections(profile_id)
    # Seed an existing reflection with opinion_at_gen far from what the update will produce
    future = utc_now() + timedelta(days=20)
    with Session(engine) as db:
        db.add(SocialReflection(
            profile_id=profile_id,
            category="general",
            content="Reflexión anterior",
            evidence_json="[]",
            opinion_at_gen=-0.8,   # far from the positive loads we're about to process
            trust_at_gen=0.0,
            expires_at=future,
        ))
        db.commit()
    # Seed fewer than 20 messages (opinion delta alone must trigger)
    _seed_messages(uid, 3)

    with patch(
        "app.social.update._generate_reflection_content",
        return_value=_FAKE_CONTENT,
    ):
        _run_social_update(uid, "trc_narr_test_3")

    # There should now be 2 reflections: old (superseded) + new (active)
    assert _count_reflections(profile_id) == 2
    active = _get_active_reflection(profile_id)
    assert active is not None
    assert active.content == _FAKE_CONTENT


# ---------------------------------------------------------------------------
# 4. Existing active reflection is superseded when new one is generated
# ---------------------------------------------------------------------------

def test_old_reflection_superseded_on_new_generation() -> None:
    uid = 8804
    profile_id = _setup_profile(uid, pending_loads=[1])
    _delete_reflections(profile_id)

    # Seed an existing active reflection with small opinion_at_gen
    future = utc_now() + timedelta(days=20)
    with Session(engine) as db:
        old_ref = SocialReflection(
            profile_id=profile_id,
            category="general",
            content="Reflexión previa",
            evidence_json="[]",
            opinion_at_gen=-0.9,
            trust_at_gen=0.0,
            expires_at=future,
        )
        db.add(old_ref)
        db.commit()
        db.refresh(old_ref)
        old_id = old_ref.id

    _seed_messages(uid, 3)  # delta alone triggers (opinion will move from -0.9)

    with patch(
        "app.social.update._generate_reflection_content",
        return_value="Reflexión nueva",
    ):
        _run_social_update(uid, "trc_narr_test_4")

    # Old reflection must be superseded
    with Session(engine) as db:
        old = db.get(SocialReflection, old_id)
        assert old is not None
        assert old.superseded_at is not None, "Old reflection should be superseded"

    # New active reflection must exist
    active = _get_active_reflection(profile_id)
    assert active is not None
    assert active.content == "Reflexión nueva"
    assert active.id != old_id


# ---------------------------------------------------------------------------
# 5. Expired reflection is NOT injected in the prompt
# ---------------------------------------------------------------------------

def test_expired_reflection_not_injected() -> None:
    uid = 8805
    profile_id = _setup_profile(uid, pending_loads=[])
    _delete_reflections(profile_id)

    # Insert an expired reflection
    past = utc_now() - timedelta(seconds=1)
    with Session(engine) as db:
        db.add(SocialReflection(
            profile_id=profile_id,
            category="general",
            content="Reflexión caducada",
            evidence_json="[]",
            opinion_at_gen=0.0,
            trust_at_gen=0.0,
            expires_at=past,
        ))
        db.commit()
    # Also ensure the profile has correct opinion/trust
    with Session(engine) as db:
        profile = db.exec(
            select(SocialProfile).where(SocialProfile.user_id == uid)
        ).first()
        profile.opinion = 0.3
        profile.trust = 0.5
        db.add(profile)
        db.commit()

    from app.chat.prompt_context import _build_social_context_block
    with Session(engine) as db:
        block = _build_social_context_block(db, f"user:{uid}")

    assert "Patrón observado" not in block
    assert "Reflexión caducada" not in block
    assert "Disposición" in block  # numerical block still present


# ---------------------------------------------------------------------------
# 6. Active reflection IS injected in the prompt
# ---------------------------------------------------------------------------

def test_active_reflection_injected_in_prompt() -> None:
    uid = 8806
    profile_id = _setup_profile(uid, pending_loads=[])
    _delete_reflections(profile_id)

    future = utc_now() + timedelta(days=25)
    with Session(engine) as db:
        db.add(SocialReflection(
            profile_id=profile_id,
            category="general",
            content=_FAKE_CONTENT,
            evidence_json="[]",
            opinion_at_gen=0.3,
            trust_at_gen=0.5,
            expires_at=future,
        ))
        db.commit()
    with Session(engine) as db:
        profile = db.exec(
            select(SocialProfile).where(SocialProfile.user_id == uid)
        ).first()
        profile.opinion = 0.3
        profile.trust = 0.5
        db.add(profile)
        db.commit()

    from app.chat.prompt_context import _build_social_context_block
    with Session(engine) as db:
        block = _build_social_context_block(db, f"user:{uid}")

    assert "Patrón observado" in block
    assert _FAKE_CONTENT in block


# ---------------------------------------------------------------------------
# 7. LLM failure does NOT block the social update (numerical fields still updated)
# ---------------------------------------------------------------------------

def test_reflection_generation_failure_does_not_block_job() -> None:
    uid = 8807
    profile_id = _setup_profile(uid, pending_loads=[2, 2, 2])
    _delete_reflections(profile_id)
    _seed_messages(uid, 20)

    with patch(
        "app.social.update._generate_reflection_content",
        side_effect=RuntimeError("provider_timeout"),
    ):
        _run_social_update(uid, "trc_narr_test_7")

    # Numerical update must have succeeded
    with Session(engine) as db:
        profile = db.exec(
            select(SocialProfile).where(SocialProfile.user_id == uid)
        ).first()
        assert profile is not None
        assert profile.opinion != 0.0, "opinion should have been updated from pending loads"

    # No reflection should exist (generation failed gracefully)
    assert _count_reflections(profile_id) == 0


# ---------------------------------------------------------------------------
# 8. Guest session never triggers a SocialReflection query
# ---------------------------------------------------------------------------

def test_guest_never_gets_reflection() -> None:
    from app.chat.prompt_context import _build_social_context_block

    with Session(engine) as db:
        block = _build_social_context_block(db, "guest:abc123")

    # Guest gets empty block — no DB access at all for SocialReflection
    assert block == ""

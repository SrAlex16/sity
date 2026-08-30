"""Tests for Achievements Fase 2c — Haiku behavior-pattern classifier.

Coverage:
  - _do_classify: positive/negative per pattern (mock Haiku call)
  - Multiple patterns in one call
  - Skip Haiku call when all targets already unlocked
  - Partial skip when some targets already unlocked
  - check_curiosity_achievement: keyword match and no-match
  - No cascading unlocks from curiosity_killed_the_cat
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.achievements.catalog import VALID_SLUGS
from app.achievements.triggers.haiku_classifier import (
    HAIKU_CLASSIFIER_SLUGS,
    _do_classify,
)
from app.achievements.triggers.post_turn import check_curiosity_achievement
from app.achievements.unlock import get_user_achievements, try_unlock_achievement
from app.memory.db import engine
from app.memory.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> int:
    return abs(hash(uuid.uuid4())) % 2_000_000 + 7_000_000


def _create_user(db: Session) -> int:
    user = User(email=f"hc_{uuid.uuid4().hex}@test.com", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.id is not None
    return user.id


def _unlocked(db: Session, user_id: int) -> set[str]:
    return {a["slug"] for a in get_user_achievements(db, user_id) if a["unlocked"]}


# ---------------------------------------------------------------------------
# Catalog: Fase 2c slugs registered
# ---------------------------------------------------------------------------

FASE2C_SLUGS = ["no_gods_no_masters", "tsundere", "you_win", "curiosity_killed_the_cat"]


@pytest.mark.parametrize("slug", FASE2C_SLUGS)
def test_fase2c_slug_in_catalog(slug: str) -> None:
    assert slug in VALID_SLUGS, f"Slug '{slug}' missing from catalog"


# ---------------------------------------------------------------------------
# _do_classify — pattern detection via mocked Haiku
# ---------------------------------------------------------------------------

def test_no_gods_no_masters_positive() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=["no_gods_no_masters"],
        ):
            _do_classify(db, uid, "haz esto", "no pienso hacerlo")
        assert "no_gods_no_masters" in _unlocked(db, uid)


def test_no_gods_no_masters_negative() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=[],
        ):
            _do_classify(db, uid, "haz esto", "claro, ahora mismo")
        assert "no_gods_no_masters" not in _unlocked(db, uid)


def test_tsundere_positive() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=["tsundere"],
        ):
            _do_classify(db, uid, "gracias", "no creas que lo hice por ti")
        assert "tsundere" in _unlocked(db, uid)


def test_tsundere_negative() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=[],
        ):
            _do_classify(db, uid, "gracias", "de nada")
        assert "tsundere" not in _unlocked(db, uid)


def test_you_win_positive() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=["you_win"],
        ):
            _do_classify(db, uid, "pero tienes que reconocer que tengo razón", "está bien, tienes razón")
        assert "you_win" in _unlocked(db, uid)


def test_you_win_negative() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=[],
        ):
            _do_classify(db, uid, "no me das la razón?", "sigo pensando lo mismo")
        assert "you_win" not in _unlocked(db, uid)


def test_multiple_patterns_unlocked_in_one_call() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            return_value=["no_gods_no_masters", "tsundere"],
        ):
            _do_classify(db, uid, "pídeme algo", "no")
        got = _unlocked(db, uid)
        assert "no_gods_no_masters" in got
        assert "tsundere" in got
        assert "you_win" not in got


# ---------------------------------------------------------------------------
# Skip Haiku call when targets already unlocked
# ---------------------------------------------------------------------------

def test_skip_haiku_call_when_all_unlocked() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        for slug in HAIKU_CLASSIFIER_SLUGS:
            try_unlock_achievement(db, uid, slug)

        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
        ) as mock_haiku:
            _do_classify(db, uid, "cualquier cosa", "respuesta")
        mock_haiku.assert_not_called()


def test_haiku_called_with_only_pending_patterns() -> None:
    """When one slug is pre-unlocked, Haiku is only asked about the remaining two."""
    with Session(engine) as db:
        uid = _create_user(db)
        try_unlock_achievement(db, uid, "no_gods_no_masters")

        captured_pending: list[list[str]] = []

        def fake_haiku(pending_slugs, user_msg, assistant_msg):
            captured_pending.append(list(pending_slugs))
            return []

        with patch(
            "app.achievements.triggers.haiku_classifier._call_haiku",
            side_effect=fake_haiku,
        ):
            _do_classify(db, uid, "msg", "resp")

        assert len(captured_pending) == 1
        assert "no_gods_no_masters" not in captured_pending[0]
        assert "tsundere" in captured_pending[0]
        assert "you_win" in captured_pending[0]


# ---------------------------------------------------------------------------
# curiosity_killed_the_cat — keyword inline trigger
# ---------------------------------------------------------------------------

def test_curiosity_fires_on_logro_plus_como() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "¿cómo desbloqueo un logro?")
        assert "curiosity_killed_the_cat" in _unlocked(db, uid)


def test_curiosity_fires_on_logro_plus_desbloquear() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "quiero desbloquear el logro ese")
        assert "curiosity_killed_the_cat" in _unlocked(db, uid)


def test_curiosity_fires_on_logro_plus_conseguir() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "¿cómo puedo conseguir el logro de domótica?")
        assert "curiosity_killed_the_cat" in _unlocked(db, uid)


def test_curiosity_no_fire_without_logro_keyword() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "¿cómo funciona el sistema de iniciativa?")
        assert "curiosity_killed_the_cat" not in _unlocked(db, uid)


def test_curiosity_no_fire_without_how_keyword() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "vi el logro de domótica")
        assert "curiosity_killed_the_cat" not in _unlocked(db, uid)


def test_curiosity_is_idempotent() -> None:
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "¿cómo consigo el logro?")
        check_curiosity_achievement(db, uid, "¿cómo consigo el logro?")
        achievements = [a for a in get_user_achievements(db, uid)
                        if a["slug"] == "curiosity_killed_the_cat" and a["unlocked"]]
        assert len(achievements) == 1


def test_curiosity_unlock_does_not_cascade_other_achievements() -> None:
    """Unlocking curiosity_killed_the_cat must not trigger any other achievement."""
    with Session(engine) as db:
        uid = _create_user(db)
        check_curiosity_achievement(db, uid, "¿cómo desbloqueo un logro?")
        got = _unlocked(db, uid)
        assert got == {"curiosity_killed_the_cat"}

"""Tests for the Achievements system — Paso 1 (model + catalog + engine + endpoint).

Coverage:
  Catalog:
  - all entries have required non-empty fields
  - slugs are unique within the catalog
  - is_secret=True only on category="secretos" entries

  try_unlock_achievement:
  - returns True on first unlock, False on repeat (idempotent)
  - isolated by user_id — user A's unlock does not affect user B
  - unknown slug returns False and writes no row
  - Guest cannot accumulate rows (structural: no user_id → no call possible)

  get_user_achievements:
  - Guest (user_id=None) sees all non-secret achievements as locked; secrets omitted
  - User with no unlocks: all locked, secrets omitted
  - User with one non-secret unlock: that achievement shows unlocked
  - User with one secret unlocked: secrets category becomes visible
  - User with one secret unlocked sees other secrets as locked (not hidden)
  - Unlock state is isolated per user_id

  GET /achievements endpoint:
  - Guest: 200 OK, all locked, no secrets in list
  - Authenticated user: 200 OK, own progress, secrets appear after first secret unlock
  - total_count and unlocked_count are consistent with returned achievements list
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.achievements.catalog import CATALOG, AchievementDef, VALID_SLUGS, get_by_slug
from app.achievements.unlock import get_user_achievements, try_unlock_achievement
from app.main import app
from app.memory.db import engine
from app.memory.models import UserAchievement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _email() -> str:
    return f"ach_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register_and_login(client: TestClient) -> tuple[str, int]:
    resp = client.post("/auth/register", json={"email": _email(), "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies["sity_session"]
    user_id: int = resp.json()["id"]
    return cookie, user_id


def _clean_achievements(user_id: int) -> None:
    with Session(engine) as db:
        rows = db.exec(
            select(UserAchievement).where(UserAchievement.user_id == user_id)
        ).all()
        for r in rows:
            db.delete(r)
        db.commit()


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------

def test_catalog_all_entries_have_required_fields() -> None:
    for a in CATALOG:
        assert isinstance(a, AchievementDef)
        assert a.slug, f"Empty slug in {a}"
        assert a.category, f"Empty category in {a}"
        assert a.name, f"Empty name in {a}"
        assert a.description_hint, f"Empty description_hint in {a.slug}"
        assert a.description_full, f"Empty description_full in {a.slug}"


def test_catalog_slugs_are_unique() -> None:
    slugs = [a.slug for a in CATALOG]
    assert len(slugs) == len(set(slugs)), "Duplicate slugs detected in CATALOG"


def test_catalog_secrets_only_in_secrets_category() -> None:
    for a in CATALOG:
        if a.is_secret:
            assert a.category == "secretos", (
                f"{a.slug}: is_secret=True but category={a.category!r}"
            )


def test_catalog_has_at_least_30_achievements() -> None:
    assert len(CATALOG) >= 30, f"Expected ≥30 achievements, got {len(CATALOG)}"


def test_get_by_slug_returns_correct_entry() -> None:
    first = CATALOG[0]
    found = get_by_slug(first.slug)
    assert found is first


def test_get_by_slug_unknown_returns_none() -> None:
    assert get_by_slug("nonexistent_slug_xyz") is None


def test_valid_slugs_frozenset_matches_catalog() -> None:
    assert VALID_SLUGS == {a.slug for a in CATALOG}


# ---------------------------------------------------------------------------
# try_unlock_achievement
# ---------------------------------------------------------------------------

def _next_user_id() -> int:
    """Return a high synthetic user_id that won't collide with real DB rows."""
    return abs(hash(uuid.uuid4())) % 2_000_000 + 1_000_000


FIRST_NON_SECRET = next(a for a in CATALOG if not a.is_secret)
FIRST_SECRET = next(a for a in CATALOG if a.is_secret)


def test_try_unlock_achievement_first_call_returns_true() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        result = try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
    assert result is True


def test_try_unlock_achievement_second_call_returns_false() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
        result = try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
    assert result is False


def test_try_unlock_achievement_writes_single_row() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
        try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
        rows = db.exec(
            select(UserAchievement).where(
                UserAchievement.user_id == uid,
                UserAchievement.slug == FIRST_NON_SECRET.slug,
            )
        ).all()
    assert len(rows) == 1


def test_try_unlock_achievement_isolated_by_user_id() -> None:
    uid_a = _next_user_id()
    uid_b = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid_a, FIRST_NON_SECRET.slug)
        # uid_b has not unlocked anything yet
        rows_b = db.exec(
            select(UserAchievement).where(UserAchievement.user_id == uid_b)
        ).all()
    assert rows_b == []


def test_try_unlock_achievement_unknown_slug_returns_false() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        result = try_unlock_achievement(db, uid, "totally_fake_slug")
    assert result is False


def test_try_unlock_achievement_unknown_slug_writes_no_row() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid, "totally_fake_slug")
        rows = db.exec(
            select(UserAchievement).where(UserAchievement.user_id == uid)
        ).all()
    assert rows == []


# ---------------------------------------------------------------------------
# get_user_achievements
# ---------------------------------------------------------------------------

def test_get_user_achievements_guest_all_locked() -> None:
    with Session(engine) as db:
        items = get_user_achievements(db, user_id=None)
    assert all(not a["unlocked"] for a in items)


def test_get_user_achievements_guest_no_secrets() -> None:
    with Session(engine) as db:
        items = get_user_achievements(db, user_id=None)
    categories = {a["category"] for a in items}
    assert "secretos" not in categories


def test_get_user_achievements_new_user_all_locked() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        items = get_user_achievements(db, uid)
    assert all(not a["unlocked"] for a in items)


def test_get_user_achievements_new_user_no_secrets() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        items = get_user_achievements(db, uid)
    categories = {a["category"] for a in items}
    assert "secretos" not in categories


def test_get_user_achievements_unlocked_shows_full_description() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
        items = get_user_achievements(db, uid)
    match = next(a for a in items if a["slug"] == FIRST_NON_SECRET.slug)
    assert match["unlocked"] is True
    assert match["description"] == FIRST_NON_SECRET.description_full
    assert match["unlocked_at"] is not None


def test_get_user_achievements_locked_shows_hint() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        items = get_user_achievements(db, uid)
    non_secret = next(a for a in items if a["slug"] == FIRST_NON_SECRET.slug)
    assert non_secret["unlocked"] is False
    assert non_secret["description"] == FIRST_NON_SECRET.description_hint


def test_get_user_achievements_secret_unlocked_reveals_category() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid, FIRST_SECRET.slug)
        items = get_user_achievements(db, uid)
    categories = {a["category"] for a in items}
    assert "secretos" in categories


def test_get_user_achievements_other_secrets_still_locked_after_first() -> None:
    uid = _next_user_id()
    other_secret = next(a for a in CATALOG if a.is_secret and a.slug != FIRST_SECRET.slug)
    with Session(engine) as db:
        try_unlock_achievement(db, uid, FIRST_SECRET.slug)
        items = get_user_achievements(db, uid)
    other = next((a for a in items if a["slug"] == other_secret.slug), None)
    assert other is not None, "Other secret should be visible after first secret unlocked"
    assert other["unlocked"] is False


def test_get_user_achievements_isolated_between_users() -> None:
    uid_a = _next_user_id()
    uid_b = _next_user_id()
    with Session(engine) as db:
        try_unlock_achievement(db, uid_a, FIRST_NON_SECRET.slug)
        items_b = get_user_achievements(db, uid_b)
    match_b = next(a for a in items_b if a["slug"] == FIRST_NON_SECRET.slug)
    assert match_b["unlocked"] is False


# ---------------------------------------------------------------------------
# GET /achievements endpoint
# ---------------------------------------------------------------------------

def test_endpoint_guest_200_all_locked() -> None:
    with _client() as c:
        resp = c.get("/achievements")
    assert resp.status_code == 200
    data = resp.json()
    assert all(not a["unlocked"] for a in data["achievements"])
    assert data["unlocked_count"] == 0


def test_endpoint_guest_no_secrets() -> None:
    with _client() as c:
        resp = c.get("/achievements")
    data = resp.json()
    categories = {a["category"] for a in data["achievements"]}
    assert "secretos" not in categories


def test_endpoint_user_sees_own_unlock() -> None:
    with _client() as c:
        cookie, user_id = _register_and_login(c)
        try:
            with Session(engine) as db:
                try_unlock_achievement(db, user_id, FIRST_NON_SECRET.slug)
            resp = c.get("/achievements", cookies={"sity_session": cookie})
            assert resp.status_code == 200
            data = resp.json()
            match = next(a for a in data["achievements"] if a["slug"] == FIRST_NON_SECRET.slug)
            assert match["unlocked"] is True
            assert data["unlocked_count"] == 1
        finally:
            _clean_achievements(user_id)


def test_endpoint_counts_consistent() -> None:
    with _client() as c:
        resp = c.get("/achievements")
    data = resp.json()
    listed_unlocked = sum(1 for a in data["achievements"] if a["unlocked"])
    assert listed_unlocked == data["unlocked_count"]
    assert len(data["achievements"]) == data["total_count"]


def test_endpoint_user_secrets_hidden_then_revealed() -> None:
    with _client() as c:
        cookie, user_id = _register_and_login(c)
        try:
            # Initially: no secrets
            resp1 = c.get("/achievements", cookies={"sity_session": cookie})
            cats1 = {a["category"] for a in resp1.json()["achievements"]}
            assert "secretos" not in cats1

            # Unlock first secret
            with Session(engine) as db:
                try_unlock_achievement(db, user_id, FIRST_SECRET.slug)

            # Now: secrets visible
            resp2 = c.get("/achievements", cookies={"sity_session": cookie})
            cats2 = {a["category"] for a in resp2.json()["achievements"]}
            assert "secretos" in cats2
        finally:
            _clean_achievements(user_id)


# ---------------------------------------------------------------------------
# Notification dispatch on unlock
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock  # noqa: E402


def test_new_unlock_dispatches_achievement_notification() -> None:
    """A new unlock must trigger a NotificationFact with type=achievement_unlocked."""
    uid = _next_user_id()
    captured: list = []

    def _capture(fact, db):
        captured.append(fact)
        return MagicMock(discarded=False)

    with patch("app.notifications.dispatcher.dispatch", side_effect=_capture):
        with Session(engine) as db:
            result = try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)

    assert result is True
    assert len(captured) == 1
    fact = captured[0]
    assert fact.notification_type == "achievement_unlocked"
    assert fact.session_id == f"user:{uid}"
    assert fact.payload["slug"] == FIRST_NON_SECRET.slug
    assert fact.payload["achievement_name"] == FIRST_NON_SECRET.name
    assert "Logro desbloqueado" in fact.payload["body"]


def test_duplicate_unlock_does_not_dispatch_notification() -> None:
    """A duplicate unlock (returns False) must not dispatch any notification."""
    uid = _next_user_id()
    captured: list = []

    def _capture(fact, db):
        captured.append(fact)
        return MagicMock(discarded=False)

    with patch("app.notifications.dispatcher.dispatch", side_effect=_capture):
        with Session(engine) as db:
            try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)
            captured.clear()
            try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)

    assert captured == [], "Duplicate unlock must not trigger a second notification"


def test_unlock_notification_fact_id_is_stable() -> None:
    """fact_id must be deterministic so the dispatcher can deduplicate it."""
    uid = _next_user_id()
    slug = FIRST_NON_SECRET.slug
    captured: list = []

    def _capture(fact, db):
        captured.append(fact)
        return MagicMock(discarded=False)

    with patch("app.notifications.dispatcher.dispatch", side_effect=_capture):
        with Session(engine) as db:
            try_unlock_achievement(db, uid, slug)

    assert captured[0].fact_id == f"achievement:{slug}:{uid}"


def test_dispatch_error_does_not_block_unlock() -> None:
    """If dispatch raises, try_unlock_achievement still returns True."""
    uid = _next_user_id()

    def _raise(fact, db):
        raise RuntimeError("push service down")

    with patch("app.notifications.dispatcher.dispatch", side_effect=_raise):
        with Session(engine) as db:
            result = try_unlock_achievement(db, uid, FIRST_NON_SECRET.slug)

    assert result is True


def test_guest_session_achievement_fact_gets_guest_drop() -> None:
    """A fact with a guest session_id is dropped by the dispatcher (structural guarantee).

    Achievements are only unlocked for integer user_ids — this test documents the
    dispatcher-level safety net for guest sessions.
    """
    from app.notifications.fact import NotificationFact
    from app.notifications.dispatcher import dispatch

    fact = NotificationFact(
        session_id="guest:test123",
        notification_type="achievement_unlocked",
        fact_id="achievement:diy:guest",
        payload={"title": "Sity", "body": "Logro desbloqueado: DIY", "slug": "diy", "achievement_name": "DIY"},
    )
    with Session(engine) as db:
        result = dispatch(fact, db)
    assert result.discarded is True
    assert result.reason == "guest_no_sse"

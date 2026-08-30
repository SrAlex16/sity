"""Tests for Achievements Paso 2 Fase 2a — inline triggers.

Each trigger slug is tested for:
  - first call returns True (new unlock)
  - repeat call returns False (idempotent)
  - guest session (no "user:" prefix) always returns False

Also tests the _user_id_from_session helper and the fire() wrapper directly.
"""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session

from app.achievements.triggers.inline import _user_id_from_session, fire
from app.achievements.catalog import VALID_SLUGS
from app.memory.db import engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_user_id() -> int:
    return abs(hash(uuid.uuid4())) % 2_000_000 + 3_000_000


def _sid(user_id: int) -> str:
    return f"user:{user_id}"


# ---------------------------------------------------------------------------
# _user_id_from_session
# ---------------------------------------------------------------------------

def test_user_id_from_session_authenticated() -> None:
    assert _user_id_from_session("user:42") == 42


def test_user_id_from_session_guest() -> None:
    assert _user_id_from_session("guest:abc") is None


def test_user_id_from_session_empty() -> None:
    assert _user_id_from_session("") is None


def test_user_id_from_session_invalid_int() -> None:
    assert _user_id_from_session("user:notanint") is None


def test_user_id_from_session_high_id() -> None:
    assert _user_id_from_session("user:9999999") == 9_999_999


# ---------------------------------------------------------------------------
# fire() — generic wrapper
# ---------------------------------------------------------------------------

def test_fire_unknown_slug_returns_false() -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        result = fire(db, _sid(uid), "totally_fake_slug_xyz")
    assert result is False


def test_fire_guest_session_returns_false() -> None:
    with Session(engine) as db:
        result = fire(db, "guest:abc123", "hello_world")
    assert result is False


def test_fire_no_prefix_session_returns_false() -> None:
    with Session(engine) as db:
        result = fire(db, "default", "hello_world")
    assert result is False


# ---------------------------------------------------------------------------
# Parametrized: first / repeat / guest for every Fase 2a slug
# ---------------------------------------------------------------------------

FASE2A_SLUGS = [
    "hello_world",
    "persona",
    "tars",
    "objection",
    "pacto",
    "diy",
    "wired",
    "law_of_cycles",
    "pause_menu",
    "say_cheese",
    "codec",
    "would_you_kindly",
    "glados",
    "here_comes_the_sun",
    "welcome_to_the_family",
    "radio_video",
    "keep_on_rollin",
    "time_is_running_out",
    "youve_got_mail",
    "ill_be_back",
    "voices",
]


@pytest.mark.parametrize("slug", FASE2A_SLUGS)
def test_slug_exists_in_catalog(slug: str) -> None:
    assert slug in VALID_SLUGS, f"Slug '{slug}' missing from catalog"


@pytest.mark.parametrize("slug", FASE2A_SLUGS)
def test_fire_first_call_returns_true(slug: str) -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        result = fire(db, _sid(uid), slug)
    assert result is True, f"Expected True on first fire for {slug}"


@pytest.mark.parametrize("slug", FASE2A_SLUGS)
def test_fire_repeat_call_returns_false(slug: str) -> None:
    uid = _next_user_id()
    with Session(engine) as db:
        fire(db, _sid(uid), slug)
        result = fire(db, _sid(uid), slug)
    assert result is False, f"Expected False on repeat fire for {slug}"


@pytest.mark.parametrize("slug", FASE2A_SLUGS)
def test_fire_guest_returns_false(slug: str) -> None:
    with Session(engine) as db:
        result = fire(db, "guest:session123", slug)
    assert result is False, f"Expected False for guest on {slug}"


@pytest.mark.parametrize("slug", FASE2A_SLUGS)
def test_fire_isolated_between_users(slug: str) -> None:
    uid_a = _next_user_id()
    uid_b = _next_user_id()
    with Session(engine) as db:
        fire(db, _sid(uid_a), slug)
        result_b = fire(db, _sid(uid_b), slug)
    assert result_b is True, f"User B should still unlock {slug} independently of user A"

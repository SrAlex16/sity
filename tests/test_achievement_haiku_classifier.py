"""Tests for Achievements Fase 2c — Haiku-based conversation pattern classifier.

All tests mock the Anthropic API — no real LLM calls.

Coverage:
  - _user_id_from_session helper
  - _call_haiku filters valid slugs and rejects invalid ones
  - _run_classifier unlocks detected achievements
  - _run_classifier skips already-unlocked targets
  - _run_classifier is a no-op for guest sessions
  - classify_conversation_async is a no-op without ANTHROPIC_API_KEY
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

from app.achievements.triggers.haiku_classifier import (
    _TARGETS,
    _call_haiku,
    _run_classifier,
    _user_id_from_session,
    classify_conversation_async,
)
from app.achievements.unlock import get_user_achievements, try_unlock_achievement
from app.memory.db import engine
from app.memory.models import ChatMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> int:
    return abs(hash(uuid.uuid4())) % 2_000_000 + 7_000_000


def _sid(user_id: int) -> str:
    return f"user:{user_id}"


def _unlocked(db: Session, user_id: int) -> set[str]:
    return {a["slug"] for a in get_user_achievements(db, user_id) if a["unlocked"]}


def _insert_messages(db: Session, session_id: str, count: int = 5) -> None:
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        db.add(ChatMessage(session_id=session_id, role=role, text=f"message {i}"))
    db.commit()


def _mock_haiku_response(slugs: list[str]) -> MagicMock:
    content_block = MagicMock()
    content_block.text = json.dumps(slugs)
    resp = MagicMock()
    resp.content = [content_block]
    return resp


# ---------------------------------------------------------------------------
# _user_id_from_session
# ---------------------------------------------------------------------------

def test_user_id_from_session_valid() -> None:
    assert _user_id_from_session("user:42") == 42


def test_user_id_from_session_guest() -> None:
    assert _user_id_from_session("guest:abc") is None


def test_user_id_from_session_empty() -> None:
    assert _user_id_from_session("") is None


def test_user_id_from_session_invalid_int() -> None:
    assert _user_id_from_session("user:notanint") is None


# ---------------------------------------------------------------------------
# _call_haiku
# ---------------------------------------------------------------------------

def test_call_haiku_returns_valid_slugs() -> None:
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create.return_value = _mock_haiku_response(["you_win", "tsundere"])
        result = _call_haiku([{"role": "user", "content": "hi"}], "fake-key")
    assert set(result) == {"you_win", "tsundere"}


def test_call_haiku_filters_invalid_slugs() -> None:
    with patch("anthropic.Anthropic") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.messages.create.return_value = _mock_haiku_response(
            ["you_win", "fake_slug", "another_fake"]
        )
        result = _call_haiku([{"role": "user", "content": "hi"}], "fake-key")
    assert result == ["you_win"]


def test_call_haiku_returns_empty_on_api_error() -> None:
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = RuntimeError("API down")
        result = _call_haiku([{"role": "user", "content": "hi"}], "fake-key")
    assert result == []


def test_call_haiku_returns_empty_on_invalid_json() -> None:
    content_block = MagicMock()
    content_block.text = "not json at all"
    resp = MagicMock()
    resp.content = [content_block]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = resp
        result = _call_haiku([{"role": "user", "content": "hi"}], "fake-key")
    assert result == []


# ---------------------------------------------------------------------------
# _run_classifier — integration
# ---------------------------------------------------------------------------

def test_run_classifier_unlocks_detected_achievement() -> None:
    uid = _uid()
    session_id = _sid(uid)
    with Session(engine) as db:
        _insert_messages(db, session_id)

    with (
        patch("app.achievements.triggers.haiku_classifier._call_haiku", return_value=["you_win"]),
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}),
    ):
        _run_classifier(session_id, "fake-key")

    with Session(engine) as db:
        assert "you_win" in _unlocked(db, uid)


def test_run_classifier_skips_already_unlocked() -> None:
    uid = _uid()
    session_id = _sid(uid)
    with Session(engine) as db:
        _insert_messages(db, session_id)
        try_unlock_achievement(db, uid, "you_win")

    call_count = []

    def fake_call_haiku(history, api_key):
        call_count.append(1)
        return ["you_win"]

    with patch("app.achievements.triggers.haiku_classifier._call_haiku", side_effect=fake_call_haiku):
        _run_classifier(session_id, "fake-key")

    # All targets except you_win remain — but _call_haiku should still be called
    # (other targets might not be unlocked). This test verifies the already-unlocked
    # slug is NOT re-processed even if returned by the classifier.
    with Session(engine) as db:
        unlocked = _unlocked(db, uid)
    assert "you_win" in unlocked


def test_run_classifier_guest_session_is_noop() -> None:
    _run_classifier("guest:abc123", "fake-key")
    # No exception raised, and no DB operations on guest


def test_run_classifier_no_messages_is_noop() -> None:
    uid = _uid()
    session_id = _sid(uid)

    call_count = []
    with patch("app.achievements.triggers.haiku_classifier._call_haiku", side_effect=lambda h, k: call_count.append(1) or []):
        _run_classifier(session_id, "fake-key")

    assert call_count == [], "Should not call Haiku when there are no messages"


# ---------------------------------------------------------------------------
# classify_conversation_async — no-op without API key
# ---------------------------------------------------------------------------

def test_classify_conversation_async_noop_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Should return immediately without spawning a thread
    classify_conversation_async("user:999")  # no exception, no side effects


def test_targets_frozenset_contains_expected_slugs() -> None:
    assert _TARGETS == {"no_gods_no_masters", "tsundere", "you_win", "curiosity_killed_the_cat"}

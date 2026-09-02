"""Tests for UserMessageGuard (per-session daily message-count limits).

Scenarios:
- User within limit → None (proceeds to AI)
- User exceeds limit → guard response, no Claude call
- Guest has independent lower limit from User
- Admin is never blocked
- Counter resets on date change (mocked)
- Disabled limit (0) never blocks
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.memory.models import DailyMessageUsage


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def mem_session(mem_engine):
    with Session(mem_engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_ctx(session, session_id: str, *, is_admin: bool = False,
              user_limit: int = 5, guest_limit: int = 2,
              language_override: str = "auto"):
    from app.chat.user_message_guard import UserMessageGuardContext
    return UserMessageGuardContext(
        session=session,
        trace_id="test-guard",
        session_id=session_id,
        message="hola",
        is_admin=is_admin,
        user_limit=user_limit,
        guest_limit=guest_limit,
        save_message=MagicMock(),
        language_override=language_override,
    )


# ---------------------------------------------------------------------------
# Admin exemption
# ---------------------------------------------------------------------------

def test_admin_never_blocked(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:1", is_admin=True, user_limit=1)
    # Exhaust limit
    for _ in range(5):
        UserMessageGuard().try_handle(ctx)
    # Still no block
    result = UserMessageGuard().try_handle(ctx)
    assert result is None


# ---------------------------------------------------------------------------
# User limits
# ---------------------------------------------------------------------------

def test_user_within_limit_returns_none(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:10", user_limit=5)
    for _ in range(5):
        assert UserMessageGuard().try_handle(ctx) is None


def test_user_exceeds_limit_returns_guard_response(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:11", user_limit=3)
    for _ in range(3):
        UserMessageGuard().try_handle(ctx)
    result = UserMessageGuard().try_handle(ctx)
    assert result is not None
    assert result.ok is True
    assert result.model == "user-message-guard"
    assert "límite" in result.text.lower()


def test_user_exceeds_limit_saves_messages(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:12", user_limit=1)
    UserMessageGuard().try_handle(ctx)
    result = UserMessageGuard().try_handle(ctx)
    assert result is not None
    assert ctx.save_message.call_count == 2  # user msg + sity response


def test_user_blocked_count_does_not_increment(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:13", user_limit=2)
    UserMessageGuard().try_handle(ctx)  # count=1
    UserMessageGuard().try_handle(ctx)  # count=2
    UserMessageGuard().try_handle(ctx)  # blocked, count stays 2
    UserMessageGuard().try_handle(ctx)  # blocked, count stays 2
    row = mem_session.get(DailyMessageUsage, "user:13")
    assert row.count == 2


# ---------------------------------------------------------------------------
# Guest limits
# ---------------------------------------------------------------------------

def test_guest_uses_guest_limit(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "guest:abc123", user_limit=100, guest_limit=2)
    UserMessageGuard().try_handle(ctx)  # count=1
    UserMessageGuard().try_handle(ctx)  # count=2
    result = UserMessageGuard().try_handle(ctx)  # blocked
    assert result is not None
    assert "límite" in result.text.lower()


def test_guest_and_user_have_independent_counters(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    guest_ctx = _make_ctx(mem_session, "guest:xyz", guest_limit=1)
    user_ctx = _make_ctx(mem_session, "user:99", user_limit=5)
    # Exhaust guest
    UserMessageGuard().try_handle(guest_ctx)
    guest_blocked = UserMessageGuard().try_handle(guest_ctx)
    # User is not affected
    user_result = UserMessageGuard().try_handle(user_ctx)
    assert guest_blocked is not None
    assert user_result is None


# ---------------------------------------------------------------------------
# Disabled limits
# ---------------------------------------------------------------------------

def test_zero_user_limit_never_blocks(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:20", user_limit=0)
    for _ in range(200):
        assert UserMessageGuard().try_handle(ctx) is None


def test_zero_guest_limit_never_blocks(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "guest:free", guest_limit=0)
    for _ in range(50):
        assert UserMessageGuard().try_handle(ctx) is None


# ---------------------------------------------------------------------------
# Daily reset
# ---------------------------------------------------------------------------

def test_counter_resets_on_new_day(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:30", user_limit=2)

    yesterday = "2026-08-04"
    today = "2026-08-05"

    with patch("app.chat.user_message_guard.date") as mock_date:
        mock_date.today.return_value = date.fromisoformat(yesterday)
        UserMessageGuard().try_handle(ctx)  # count=1 on yesterday
        UserMessageGuard().try_handle(ctx)  # count=2 on yesterday (at limit)
        blocked_yesterday = UserMessageGuard().try_handle(ctx)

    assert blocked_yesterday is not None  # was blocked

    with patch("app.chat.user_message_guard.date") as mock_date:
        mock_date.today.return_value = date.fromisoformat(today)
        result_today = UserMessageGuard().try_handle(ctx)  # reset → count=1

    assert result_today is None  # new day, not blocked


def test_counter_date_field_is_updated(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:31", user_limit=10)

    with patch("app.chat.user_message_guard.date") as mock_date:
        mock_date.today.return_value = date.fromisoformat("2026-01-01")
        UserMessageGuard().try_handle(ctx)

    row = mem_session.get(DailyMessageUsage, "user:31")
    assert row.count_date == "2026-01-01"

    with patch("app.chat.user_message_guard.date") as mock_date:
        mock_date.today.return_value = date.fromisoformat("2026-01-02")
        UserMessageGuard().try_handle(ctx)

    mem_session.refresh(row)
    assert row.count_date == "2026-01-02"
    assert row.count == 1  # reset + 1


# ---------------------------------------------------------------------------
# No DB write when blocked
# ---------------------------------------------------------------------------

def test_no_db_write_when_blocked(mem_session):
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:40", user_limit=1)
    UserMessageGuard().try_handle(ctx)  # count=1
    count_before = mem_session.get(DailyMessageUsage, "user:40").count
    UserMessageGuard().try_handle(ctx)  # blocked
    count_after = mem_session.get(DailyMessageUsage, "user:40").count
    assert count_before == count_after == 1


# ---------------------------------------------------------------------------
# Language support
# ---------------------------------------------------------------------------

def test_msg_limit_reached_english(mem_session):
    """language_override='en-US' → English message, not Spanish."""
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:50", user_limit=1, language_override="en-US")
    UserMessageGuard().try_handle(ctx)  # count=1
    result = UserMessageGuard().try_handle(ctx)  # blocked
    assert result is not None
    assert "limit" in result.text.lower()
    assert "límite" not in result.text.lower()


def test_msg_limit_reached_default_spanish(mem_session):
    """language_override='auto' → Spanish (default behaviour unchanged)."""
    from app.chat.user_message_guard import UserMessageGuard
    ctx = _make_ctx(mem_session, "user:51", user_limit=1, language_override="auto")
    UserMessageGuard().try_handle(ctx)
    result = UserMessageGuard().try_handle(ctx)
    assert result is not None
    assert "límite" in result.text.lower()

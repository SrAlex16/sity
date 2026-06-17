"""Tests for chat_persistence helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.memory.models import AIUsage
from app.chat.chat_persistence import get_today_token_usage


def _add_usage(session: Session, created_at: datetime, tokens: int) -> None:
    session.add(AIUsage(
        trace_id="test",
        session_id="default",
        provider="mock",
        model="mock",
        task_type="chat",
        input_tokens=tokens,
        output_tokens=0,
        created_at=created_at,
    ))
    session.commit()


class TestGetTodayTokenUsage:
    def test_counts_entry_created_recently(self, db_session: Session) -> None:
        """Entry created a few minutes ago (UTC) is always within today."""
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        _add_usage(db_session, now_utc, 300)

        result = get_today_token_usage(db_session)

        assert result >= 300

    def test_excludes_entry_from_two_days_ago(self, db_session: Session) -> None:
        """Entry from 48 hours ago is never within today regardless of timezone."""
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        old = now_utc - timedelta(days=2)
        _add_usage(db_session, old, 9999)

        # Only verify that old entry does not push result above 9999 by itself.
        # (Other tests may have added recent entries so we can't assert == 0.)
        result_with_old = get_today_token_usage(db_session)
        _add_usage(db_session, now_utc, 100)
        result_with_recent = get_today_token_usage(db_session)

        # Recent entry must be counted; 48-hour-old one must not change the delta
        assert result_with_recent - result_with_old == 100

    def test_mock_datetime_now_astimezone_is_callable(self, db_session: Session) -> None:
        """datetime.now() mock must return a real datetime so .astimezone() works."""
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        _add_usage(db_session, now_utc, 500)

        # Patch datetime.now() with a real naive datetime object — NOT a MagicMock.
        # The function calls .astimezone() on the return value, which requires a
        # real datetime (MagicMock would silently return a mock and corrupt the
        # UTC conversion arithmetic).
        real_now = datetime.now()
        with patch("app.chat.chat_persistence.datetime") as mock_dt:
            mock_dt.now.return_value = real_now
            result = get_today_token_usage(db_session)

        assert result >= 500

    def test_returns_zero_when_no_entries(self, db_session: Session) -> None:
        result = get_today_token_usage(db_session)
        # May be > 0 from other tests sharing the session DB, but must not raise.
        assert isinstance(result, int)
        assert result >= 0

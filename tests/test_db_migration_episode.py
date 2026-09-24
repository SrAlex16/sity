"""Tests for the AX-01 fix: _drop_stale_youtube_tables() in db.py.

The YouTube canal pipeline (eliminated 2026-07-08) left a table named
'episode' with a completely different schema (title, script_path, …).
SQLModel.create_all() is idempotent — it silently skips tables that already
exist — so the stale table would silently block the cognition Episode model.
The fix detects the stale schema (presence of 'title' column) and drops the
table before create_all() runs.

Properties verified:
1.  Stale YouTube-schema 'episode' table (with 'title' column) → dropped.
2.  After migration + create_all, PRAGMA table_info(episode) returns the
    cognition columns (user_id, occurred_at, summary, salience_total, etc.),
    NOT the YouTube columns.
3.  Idempotent: calling _drop_stale_youtube_tables() twice doesn't raise.
4.  Correct-schema episode table (with user_id) → NOT dropped (no-op).
5.  Stale 'newsitem' table → dropped.
6.  No 'newsitem' table → no-op (no error).
7.  Regression: maybe_create_episode() with salience ≥ 0.25 succeeds after
    migration (no OperationalError from schema mismatch).
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.memory.db import _drop_stale_youtube_tables, engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_YOUTUBE_EPISODE_DDL = """
    CREATE TABLE episode (
        id          INTEGER PRIMARY KEY,
        title       TEXT NOT NULL,
        script_path TEXT,
        audio_path  TEXT,
        video_path  TEXT,
        youtube_id  TEXT,
        status      TEXT NOT NULL DEFAULT 'draft',
        created_at  DATETIME
    )
"""

_NEWSITEM_DDL = """
    CREATE TABLE newsitem (
        id         INTEGER PRIMARY KEY,
        headline   TEXT NOT NULL,
        body       TEXT,
        created_at DATETIME
    )
"""

_COGNITION_EPISODE_COLS = {
    "user_id", "occurred_at", "summary", "salience_total",
    "strength", "semantically_processed",
}


def _col_names(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDropStaleYoutubeTables:
    """All tests use a fresh in-memory SQLite DB so they don't affect the shared
    test DB and don't interfere with each other."""

    def _make_engine(self):
        eng = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        return eng

    def test_stale_episode_dropped(self):
        eng = self._make_engine()
        with eng.connect() as conn:
            conn.execute(text(_YOUTUBE_EPISODE_DDL))
            conn.commit()
            assert "title" in _col_names(conn, "episode")

        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()

        with eng.connect() as conn:
            assert not _table_exists(conn, "episode"), (
                "episode table with YouTube schema should have been dropped"
            )

    def test_after_migration_episode_has_cognition_schema(self):
        """Drop stale table → create_all → cognition columns present."""
        eng = self._make_engine()
        with eng.connect() as conn:
            conn.execute(text(_YOUTUBE_EPISODE_DDL))
            conn.commit()

        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()

        import app.memory.models as _models  # noqa: F401 — registers metadata
        SQLModel.metadata.create_all(eng)

        with eng.connect() as conn:
            cols = _col_names(conn, "episode")

        assert _COGNITION_EPISODE_COLS.issubset(cols), (
            f"Expected cognition columns {_COGNITION_EPISODE_COLS - cols} to be present; "
            f"got: {cols}"
        )
        assert "title" not in cols, "YouTube 'title' column must not be in new schema"

    def test_correct_schema_not_dropped(self):
        """If episode already has cognition schema (user_id), must NOT be dropped."""
        eng = self._make_engine()
        import app.memory.models as _models  # noqa: F401
        SQLModel.metadata.create_all(eng)

        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()

        with eng.connect() as conn:
            assert _table_exists(conn, "episode"), (
                "episode with correct schema should not be dropped"
            )
            cols = _col_names(conn, "episode")
            assert "user_id" in cols

    def test_idempotent_no_episode_table(self):
        """No episode table at all → _drop_stale_youtube_tables does not raise."""
        eng = self._make_engine()
        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()  # must not raise
            _drop_stale_youtube_tables()  # second call also safe

    def test_newsitem_dropped(self):
        eng = self._make_engine()
        with eng.connect() as conn:
            conn.execute(text(_NEWSITEM_DDL))
            conn.commit()
            assert _table_exists(conn, "newsitem")

        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()

        with eng.connect() as conn:
            assert not _table_exists(conn, "newsitem"), (
                "newsitem table should have been dropped"
            )

    def test_no_newsitem_no_error(self):
        eng = self._make_engine()
        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()  # must not raise when newsitem absent

    def test_both_stale_tables_dropped_together(self):
        eng = self._make_engine()
        with eng.connect() as conn:
            conn.execute(text(_YOUTUBE_EPISODE_DDL))
            conn.execute(text(_NEWSITEM_DDL))
            conn.commit()

        with patch("app.memory.db.engine", eng):
            _drop_stale_youtube_tables()

        with eng.connect() as conn:
            assert not _table_exists(conn, "episode")
            assert not _table_exists(conn, "newsitem")


class TestMaybeCreateEpisodeAfterMigration:
    """Regression test: maybe_create_episode() must not raise OperationalError
    after _drop_stale_youtube_tables() cleans up the stale YouTube schema."""

    def test_maybe_create_episode_works_after_migration(self, db_session):
        """maybe_create_episode with alta salience must return an Episode, not crash."""
        from app.cognition.appraisal import AppraisalResult, GoalRelevance
        from app.cognition.episode_service import (
            EpisodeSummaryResult,
            maybe_create_episode,
            _STRENGTH_ALTA,
        )
        from app.cognition.perception import PerceptionResult

        perception = PerceptionResult(
            user_intent="reflection",
            tone="philosophical",
            challenge=0.8,
            novelty=0.7,
            social_signal=0.5,
        )
        appraisal = AppraisalResult(
            interest_delta=0.3,
            frustration_delta=0.0,
            trust_evidence=0.0,
            goal_relevance=[GoalRelevance(goal_id=1, relevance=0.9)],
            surprise=0.6,
            explicit_importance=0.8,
        )

        fake_summary = EpisodeSummaryResult(
            summary="Un momento filosófico importante.",
            topics=["filosofía", "existencia"],
            emotional_valence=0.4,
            emotional_arousal=0.5,
        )

        with patch(
            "app.cognition.episode_service._generate_episode_summary",
            return_value=fake_summary,
        ):
            episode = maybe_create_episode(
                session=db_session,
                user_id=9999,
                user_message="¿Cuál es el sentido de la existencia?",
                perception=perception,
                appraisal=appraisal,
                source_message_ids=[],
                trace_id="test-ax01",
            )

        assert episode is not None, (
            "maybe_create_episode must return an Episode for alta/muy_alta salience"
        )
        assert episode.user_id == 9999
        assert episode.strength == pytest.approx(_STRENGTH_ALTA)

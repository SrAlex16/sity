"""Tests for MINI-REMAKE v2.0 Punto 1 — episodic retrieval (retrieve_relevant_episodes).

Properties verified:

RecencyBoost:
1.  Episode created today → recency ≈ 1.0 (within tolerance).
2.  Episode created 30 days ago → recency ≈ 0.5 (within ±0.05).
3.  Episode created 365 days ago → recency ≈ 0.1 (within ±0.05).
4.  recency is never below _RECENCY_FLOOR (0.05), even for very old episodes.

TopicSimilarity:
5.  All topics match → similarity = 1.0.
6.  No topics match → similarity = _TOPIC_SIMILARITY_BASE (0.20).
7.  Partial overlap (1 of 2 episode topics) → similarity between base and 1.0.
8.  Empty current_topics → similarity = _TOPIC_SIMILARITY_BASE.
9.  Invalid JSON in topics_json → falls back to _TOPIC_SIMILARITY_BASE.

RecallScore (integration):
10. Old episode (2 years ago) with high salience (0.94) and full topic match →
    can outscore a recent episode with low salience (0.15) and no topic match.
11. RecallScore is always in [0, 1].

retrieve_relevant_episodes:
12. Returns at most `limit` results.
13. Returns [] when user has no episodes.
14. Returns the most relevant episode first (by RecallScore).
15. recall_count is incremented for each returned episode.
16. last_recalled_at is set (not None) for each returned episode.
17. User isolation: only episodes belonging to user_id are retrieved.
18. Results are ordered by RecallScore DESC.

Decision context:
19. _build_decision_context includes episode summaries when recalled_episodes given.
20. _build_decision_context without recalled_episodes produces no episode block.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from app.cognition.decision import _build_decision_context
from app.cognition.episode_service import (
    EPISODE_PROMPT_MIN_SCORE,
    RecalledEpisode,
    _RECENCY_FLOOR,
    _TOPIC_SIMILARITY_BASE,
    _compute_recall_score,
    _recency_boost,
    _topic_similarity,
    build_recalled_episodes_block,
    retrieve_relevant_episodes,
)
from app.memory.models import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mem_session() -> Session:
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_episode(
    session: Session,
    *,
    user_id: int = 90500,
    summary: str = "test summary",
    topics: list[str] | None = None,
    salience_total: float = 0.5,
    strength: float = 1.0,
    context_type: str = "casual_chat",
    days_ago: float = 0,
) -> Episode:
    occurred = _utc_now() - timedelta(days=days_ago)
    ep = Episode(
        user_id=user_id,
        occurred_at=occurred,
        summary=summary,
        topics_json=json.dumps(topics or [], ensure_ascii=False),
        source_message_ids_json="[]",
        salience_total=salience_total,
        strength=strength,
        context_type=context_type,
        recall_count=0,
        created_at=occurred,
    )
    session.add(ep)
    session.commit()
    session.refresh(ep)
    return ep


# ---------------------------------------------------------------------------
# 1–4. RecencyBoost
# ---------------------------------------------------------------------------

class TestRecencyBoost:
    def test_today_is_near_one(self) -> None:
        occurred = _utc_now()
        assert _recency_boost(occurred) >= 0.95

    def test_thirty_days_near_half(self) -> None:
        occurred = _utc_now() - timedelta(days=30)
        boost = _recency_boost(occurred)
        assert abs(boost - 0.5) <= 0.05, f"expected ≈0.5, got {boost:.4f}"

    def test_one_year_near_tenth(self) -> None:
        occurred = _utc_now() - timedelta(days=365)
        boost = _recency_boost(occurred)
        assert abs(boost - 0.1) <= 0.05, f"expected ≈0.1, got {boost:.4f}"

    def test_never_below_floor(self) -> None:
        very_old = _utc_now() - timedelta(days=3650)
        assert _recency_boost(very_old) >= _RECENCY_FLOOR


# ---------------------------------------------------------------------------
# 5–9. TopicSimilarity
# ---------------------------------------------------------------------------

class TestTopicSimilarity:
    def test_full_match_is_one(self) -> None:
        topics_json = json.dumps(["testing", "arquitectura"])
        similarity = _topic_similarity(topics_json, ["testing", "arquitectura"])
        assert similarity == 1.0

    def test_no_match_is_base(self) -> None:
        topics_json = json.dumps(["familia", "viaje"])
        similarity = _topic_similarity(topics_json, ["testing", "arquitectura"])
        assert similarity == _TOPIC_SIMILARITY_BASE

    def test_partial_overlap_between_base_and_one(self) -> None:
        topics_json = json.dumps(["testing", "arquitectura"])
        similarity = _topic_similarity(topics_json, ["testing", "otro"])
        assert _TOPIC_SIMILARITY_BASE < similarity < 1.0

    def test_empty_current_topics_returns_base(self) -> None:
        topics_json = json.dumps(["testing"])
        assert _topic_similarity(topics_json, []) == _TOPIC_SIMILARITY_BASE

    def test_invalid_json_returns_base(self) -> None:
        assert _topic_similarity("not-json", ["testing"]) == _TOPIC_SIMILARITY_BASE


# ---------------------------------------------------------------------------
# 10–11. RecallScore
# ---------------------------------------------------------------------------

class TestRecallScore:
    def _mock_episode(
        self,
        *,
        topics: list[str],
        salience: float,
        strength: float,
        days_ago: float,
        context_type: str = "casual_chat",
    ) -> Episode:
        ep = MagicMock(spec=Episode)
        ep.topics_json = json.dumps(topics)
        ep.salience_total = salience
        ep.strength = strength
        ep.occurred_at = _utc_now() - timedelta(days=days_ago)
        ep.context_type = context_type
        return ep

    def test_old_high_salience_can_beat_recent_low_salience(self) -> None:
        old_high = self._mock_episode(
            topics=["testing", "arquitectura"],
            salience=0.94,
            strength=1.0,
            days_ago=730,   # 2 years
        )
        recent_low = self._mock_episode(
            topics=[],      # no topic overlap
            salience=0.15,
            strength=0.5,
            days_ago=0,
        )
        score_old = _compute_recall_score(
            old_high,
            current_topics=["testing", "arquitectura"],
            context_type="casual_chat",
        )
        score_recent = _compute_recall_score(
            recent_low,
            current_topics=["testing"],
            context_type="casual_chat",
        )
        assert score_old > score_recent, (
            f"Old high-salience ({score_old:.4f}) should beat recent low-salience ({score_recent:.4f})"
        )

    def test_recall_score_in_unit_interval(self) -> None:
        ep = self._mock_episode(
            topics=["foo"],
            salience=0.8,
            strength=1.0,
            days_ago=10,
        )
        score = _compute_recall_score(ep, current_topics=["foo"], context_type="casual_chat")
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# 12–18. retrieve_relevant_episodes
# ---------------------------------------------------------------------------

class TestRetrieveRelevantEpisodes:
    def test_returns_at_most_limit(self) -> None:
        with _mem_session() as session:
            for i in range(5):
                _make_episode(session, user_id=90501, days_ago=float(i))
            result = retrieve_relevant_episodes(
                session, 90501,
                current_topics=["test"],
                context_type="casual_chat",
                limit=3,
            )
        assert len(result) <= 3

    def test_returns_empty_when_no_episodes(self) -> None:
        with _mem_session() as session:
            result = retrieve_relevant_episodes(
                session, 90502,
                current_topics=["test"],
                context_type="casual_chat",
            )
        assert result == []

    def test_first_result_has_highest_score(self) -> None:
        with _mem_session() as session:
            _make_episode(session, user_id=90503, salience_total=0.9, topics=["testing"], days_ago=0)
            _make_episode(session, user_id=90503, salience_total=0.1, topics=[], days_ago=0)
            result = retrieve_relevant_episodes(
                session, 90503,
                current_topics=["testing"],
                context_type="casual_chat",
            )
        assert len(result) >= 1
        scores = [r.recall_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_recall_count_incremented(self) -> None:
        with _mem_session() as session:
            ep = _make_episode(session, user_id=90504, days_ago=1)
            assert ep.recall_count == 0
            retrieve_relevant_episodes(
                session, 90504,
                current_topics=[],
                context_type="casual_chat",
            )
            session.refresh(ep)
            assert ep.recall_count == 1

    def test_last_recalled_at_set(self) -> None:
        with _mem_session() as session:
            ep = _make_episode(session, user_id=90505, days_ago=1)
            assert ep.last_recalled_at is None
            retrieve_relevant_episodes(
                session, 90505,
                current_topics=[],
                context_type="casual_chat",
            )
            session.refresh(ep)
            assert ep.last_recalled_at is not None

    def test_user_isolation(self) -> None:
        with _mem_session() as session:
            _make_episode(session, user_id=90506, summary="user A episode")
            _make_episode(session, user_id=90507, summary="user B episode")
            result_a = retrieve_relevant_episodes(
                session, 90506,
                current_topics=[],
                context_type="casual_chat",
            )
            result_b = retrieve_relevant_episodes(
                session, 90507,
                current_topics=[],
                context_type="casual_chat",
            )
            # Read summaries while session is still open
            a_summaries = {r.episode.summary for r in result_a}
            b_summaries = {r.episode.summary for r in result_b}
        assert "user A episode" in a_summaries
        assert "user B episode" not in a_summaries
        assert "user B episode" in b_summaries
        assert "user A episode" not in b_summaries

    def test_results_ordered_by_score_desc(self) -> None:
        with _mem_session() as session:
            _make_episode(session, user_id=90508, salience_total=0.9, topics=["testing"], days_ago=0)
            _make_episode(session, user_id=90508, salience_total=0.3, topics=[], days_ago=200)
            _make_episode(session, user_id=90508, salience_total=0.6, topics=["testing"], days_ago=5)
            result = retrieve_relevant_episodes(
                session, 90508,
                current_topics=["testing"],
                context_type="casual_chat",
                limit=3,
            )
        scores = [r.recall_score for r in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 19–20. Decision context
# ---------------------------------------------------------------------------

class TestDecisionContext:
    def _base_scores(self) -> dict:
        return {a: 0.5 for a in ("answer", "help", "ask", "challenge", "refuse",
                                  "set_boundary", "use_tool", "wait", "initiate", "change_topic")}

    def _signals(self) -> dict:
        return {"user_intent": "question", "tone": "neutral", "context_type": "casual_chat",
                "challenge": 0.1, "novelty": 0.2, "frustration": 0.2, "interest": 0.6,
                "defensiveness": 0.1, "boredom": 0.05, "affinity": 0.5, "conflict": 0.1,
                "trust_avg": 0.6, "domain_activated": False, "intent_request": False,
                "max_goal_priority": 0.0}

    def test_episode_block_present_when_recalled(self) -> None:
        ep = MagicMock(spec=Episode)
        ep.occurred_at = _utc_now() - timedelta(days=2)
        ep.summary = "El usuario mencionó que le gusta programar en Python"
        ep.salience_total = 0.7
        recalled = [RecalledEpisode(episode=ep, recall_score=0.75)]
        ctx = _build_decision_context("hola", self._base_scores(), self._signals(),
                                      recalled_episodes=recalled)
        assert "EPISODIOS RELEVANTES" in ctx
        assert "Python" in ctx

    def test_no_episode_block_without_recalled(self) -> None:
        ctx = _build_decision_context("hola", self._base_scores(), self._signals())
        assert "EPISODIOS RELEVANTES" not in ctx

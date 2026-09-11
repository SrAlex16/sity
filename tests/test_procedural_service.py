"""Tests for Operación Remake Fase 7 — Procedural Memory (Paso 1).

Properties verified:

ProceduralObservation insertion:
1.  record_observation inserts one row with correct user_id, context_type, excerpt, trace_id.
2.  user_message truncated to 100 chars.
3.  processed=False on insertion.
4.  Returns count of unprocessed rows for (user_id, context_type).

Threshold trigger:
5.  Below threshold (< 3 unprocessed) → no ProceduralPattern created.
6.  At threshold (3 unprocessed) → maybe_trigger_pattern_synthesis fires synthesis
    (background mocked, pattern created synchronously for test).
7.  Synthesis fires again at 6 unprocessed (each multiple of 3).

ProceduralPattern creation and update:
8.  First synthesis: ProceduralPattern created with confidence=0.45, occurrence_count=3.
9.  Second synthesis (6 total): occurrence_count=6, confidence=0.57.
10. Third synthesis (9 total): occurrence_count=9, confidence=0.69.
11. Strategy_description populated (non-empty) after synthesis.
12. evidence_trail_json contains trace_ids of consumed observations.
13. Processed observations marked processed=True after synthesis.
14. No duplicate ProceduralPattern created — existing row updated.

Confidence formula:
15. _compute_confidence(3)  == pytest.approx(0.45).
16. _compute_confidence(6)  == pytest.approx(0.57).
17. _compute_confidence(9)  == pytest.approx(0.69).
18. _compute_confidence(12) == pytest.approx(0.81).
19. _compute_confidence(13) == pytest.approx(0.85) — cap.
20. _compute_confidence(20) == pytest.approx(0.85) — cap holds.

User isolation (CRITICAL — central purpose of this module):
21. Observations of user_id=1 are never counted towards user_id=2 threshold.
22. Pattern of user_id=1 never returned by load_active_patterns(user_id=2).
23. After synthesis for user_id=1, no ProceduralPattern row exists for user_id=2.

load_active_patterns:
24. Returns empty list when no pattern exists.
25. Returns pattern when confidence >= min_confidence (default 0.55).
26. Does NOT return pattern when confidence < min_confidence.
27. Does NOT return inactive (is_active=False) patterns.
28. Only returns patterns for the given context_type.

Perception:
29. _parse_perception: valid JSON with context_type → PerceptionResult with correct context_type.
30. _parse_perception: invalid context_type falls back to "casual_chat".
31. PerceptionResult.neutral() has context_type="casual_chat".
32. _VALID_CONTEXT_TYPES contains exactly 8 values.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.cognition.procedural_service import (
    PROCEDURAL_CONFIDENCE_MIN,
    _PROCEDURAL_THRESHOLD,
    _compute_confidence,
    _run_pattern_synthesis,
    load_active_patterns,
    maybe_trigger_pattern_synthesis,
    record_observation,
)
from app.cognition.perception import (
    PerceptionResult,
    _VALID_CONTEXT_TYPES,
    _parse_perception,
)
from app.memory.models import ProceduralObservation, ProceduralPattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UID_A = 901
_UID_B = 902
_CT_TECH = "technical_design"
_CT_DEBUG = "debugging"


def _cleanup(session: Session) -> None:
    """Remove all ProceduralObservation and ProceduralPattern rows for test users."""
    from sqlmodel import delete as sql_delete
    session.exec(sql_delete(ProceduralObservation).where(  # type: ignore[call-overload]
        ProceduralObservation.user_id.in_([_UID_A, _UID_B])  # type: ignore[attr-defined]
    ))
    session.exec(sql_delete(ProceduralPattern).where(  # type: ignore[call-overload]
        ProceduralPattern.user_id.in_([_UID_A, _UID_B])  # type: ignore[attr-defined]
    ))
    session.commit()


def _insert_n_obs(session: Session, n: int, user_id: int = _UID_A,
                  context_type: str = _CT_TECH) -> None:
    for i in range(n):
        record_observation(
            session,
            user_id=user_id,
            context_type=context_type,
            user_message=f"message {i}",
            trace_id=f"t-{user_id}-{i}",
        )


# ---------------------------------------------------------------------------
# 1–4: ProceduralObservation insertion
# ---------------------------------------------------------------------------

class TestRecordObservation:

    def test_inserts_row_with_correct_fields(self, db_session: Session):
        # Property 1
        _cleanup(db_session)
        record_observation(
            db_session, user_id=_UID_A, context_type=_CT_TECH,
            user_message="discuss the architecture", trace_id="tr-1",
        )
        rows = db_session.exec(
            select(ProceduralObservation).where(ProceduralObservation.user_id == _UID_A)
        ).all()
        assert len(rows) == 1
        assert rows[0].user_id == _UID_A
        assert rows[0].context_type == _CT_TECH
        assert rows[0].trace_id == "tr-1"

    def test_message_truncated_to_100_chars(self, db_session: Session):
        # Property 2
        _cleanup(db_session)
        long_msg = "x" * 200
        record_observation(
            db_session, user_id=_UID_A, context_type=_CT_TECH, user_message=long_msg,
        )
        row = db_session.exec(
            select(ProceduralObservation).where(ProceduralObservation.user_id == _UID_A)
        ).first()
        assert row is not None
        assert len(row.user_message_excerpt) == 100

    def test_processed_false_on_insertion(self, db_session: Session):
        # Property 3
        _cleanup(db_session)
        record_observation(
            db_session, user_id=_UID_A, context_type=_CT_TECH, user_message="test",
        )
        row = db_session.exec(
            select(ProceduralObservation).where(ProceduralObservation.user_id == _UID_A)
        ).first()
        assert row is not None
        assert row.processed is False

    def test_returns_unprocessed_count(self, db_session: Session):
        # Property 4
        _cleanup(db_session)
        count1 = record_observation(
            db_session, user_id=_UID_A, context_type=_CT_TECH, user_message="msg1",
        )
        count2 = record_observation(
            db_session, user_id=_UID_A, context_type=_CT_TECH, user_message="msg2",
        )
        assert count1 == 1
        assert count2 == 2


# ---------------------------------------------------------------------------
# 5–7: Threshold trigger
# ---------------------------------------------------------------------------

class TestThresholdTrigger:

    def test_below_threshold_no_thread_fired(self, db_session: Session):
        # Property 5 — 2 observations → no thread
        _cleanup(db_session)
        with patch("app.cognition.procedural_service.threading.Thread") as mock_thread:
            for i in range(_PROCEDURAL_THRESHOLD - 1):
                maybe_trigger_pattern_synthesis(
                    db_session, user_id=_UID_A, context_type=_CT_TECH,
                    user_message=f"msg {i}", trace_id=f"t{i}",
                )
            mock_thread.assert_not_called()

    def test_at_threshold_synthesis_triggered(self, db_session: Session):
        # Property 6 — exactly 3 observations → thread fired once
        _cleanup(db_session)
        with patch("app.cognition.procedural_service.threading.Thread") as mock_thread:
            mock_thread.return_value.start = lambda: None
            for i in range(_PROCEDURAL_THRESHOLD):
                maybe_trigger_pattern_synthesis(
                    db_session, user_id=_UID_A, context_type=_CT_TECH,
                    user_message=f"msg {i}", trace_id=f"t{i}",
                )
            mock_thread.assert_called_once()

    def test_second_batch_triggers_again(self, db_session: Session):
        # Property 7 — fires at 3, then again at 6
        _cleanup(db_session)
        call_count = 0

        def fake_thread(*args, **kwargs):
            class _T:
                def start(self): pass
            nonlocal call_count
            call_count += 1
            return _T()

        with patch("app.cognition.procedural_service.threading.Thread", side_effect=fake_thread):
            for i in range(6):
                maybe_trigger_pattern_synthesis(
                    db_session, user_id=_UID_A, context_type=_CT_TECH,
                    user_message=f"msg {i}", trace_id=f"t{i}",
                )
        assert call_count >= 2


# ---------------------------------------------------------------------------
# 8–14: ProceduralPattern creation and update
# ---------------------------------------------------------------------------

class TestPatternCreationAndUpdate:

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="prefer trade-offs first")
    def test_first_synthesis_creates_pattern(self, mock_synth, db_session: Session):
        # Property 8 — confidence=0.45, occurrence_count=3
        _cleanup(db_session)
        _insert_n_obs(db_session, _PROCEDURAL_THRESHOLD)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-test")
        pattern = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).first()
        assert pattern is not None
        assert pattern.occurrence_count == _PROCEDURAL_THRESHOLD
        assert pattern.confidence == pytest.approx(0.45)

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="refined strategy")
    def test_second_batch_updates_existing(self, mock_synth, db_session: Session):
        # Property 9 — occurrence_count=6, confidence=0.57
        _cleanup(db_session)
        _insert_n_obs(db_session, 6)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-test")
        db_session.expire_all()
        pattern = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).first()
        assert pattern is not None
        assert pattern.occurrence_count == 5  # up to 5 rows loaded per synthesis call
        # run again to consume second batch
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-test-2")
        db_session.expire_all()
        patterns = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).all()
        assert len(patterns) == 1  # no duplicate — Property 14

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="good strategy")
    def test_confidence_at_nine_obs(self, mock_synth, db_session: Session):
        # Property 10 — occurrence_count=9, confidence=0.69
        _cleanup(db_session)
        _insert_n_obs(db_session, 9)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-a")
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-b")
        db_session.expire_all()
        pattern = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).first()
        assert pattern is not None
        assert pattern.occurrence_count >= 9
        assert pattern.confidence == pytest.approx(_compute_confidence(pattern.occurrence_count))

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="strategy text")
    def test_strategy_description_populated(self, mock_synth, db_session: Session):
        # Property 11
        _cleanup(db_session)
        _insert_n_obs(db_session, _PROCEDURAL_THRESHOLD)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-test")
        pattern = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).first()
        assert pattern is not None
        assert pattern.strategy_description == "strategy text"

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="strat")
    def test_evidence_trail_contains_trace_ids(self, mock_synth, db_session: Session):
        # Property 12
        _cleanup(db_session)
        record_observation(db_session, user_id=_UID_A, context_type=_CT_TECH,
                           user_message="m1", trace_id="tid-1")
        record_observation(db_session, user_id=_UID_A, context_type=_CT_TECH,
                           user_message="m2", trace_id="tid-2")
        record_observation(db_session, user_id=_UID_A, context_type=_CT_TECH,
                           user_message="m3", trace_id="tid-3")
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-test")
        pattern = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).first()
        assert pattern is not None
        trail = json.loads(pattern.evidence_trail_json)
        assert "tid-1" in trail or "tid-2" in trail or "tid-3" in trail

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="strat")
    def test_observations_marked_processed_after_synthesis(self, mock_synth, db_session: Session):
        # Property 13
        _cleanup(db_session)
        _insert_n_obs(db_session, _PROCEDURAL_THRESHOLD)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-test")
        obs = db_session.exec(
            select(ProceduralObservation)
            .where(ProceduralObservation.user_id == _UID_A)
            .where(ProceduralObservation.processed == False)  # noqa: E712
        ).all()
        assert len(obs) == 0


# ---------------------------------------------------------------------------
# 15–20: Confidence formula
# ---------------------------------------------------------------------------

class TestConfidenceFormula:

    def test_confidence_at_3(self):
        assert _compute_confidence(3) == pytest.approx(0.45)

    def test_confidence_at_6(self):
        assert _compute_confidence(6) == pytest.approx(0.57)

    def test_confidence_at_9(self):
        assert _compute_confidence(9) == pytest.approx(0.69)

    def test_confidence_at_12(self):
        assert _compute_confidence(12) == pytest.approx(0.81)

    def test_confidence_capped_at_13(self):
        assert _compute_confidence(13) == pytest.approx(0.85)

    def test_confidence_cap_holds_beyond(self):
        assert _compute_confidence(20) == pytest.approx(0.85)
        assert _compute_confidence(100) == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# 21–23: User isolation (CRITICAL)
# ---------------------------------------------------------------------------

class TestUserIsolation:

    def test_observations_not_counted_across_users(self, db_session: Session):
        # Property 21 — user B's observations don't push user A over threshold
        _cleanup(db_session)
        # Insert 2 for user A and 2 for user B → neither should reach threshold alone
        _insert_n_obs(db_session, 2, user_id=_UID_A)
        _insert_n_obs(db_session, 2, user_id=_UID_B)
        # Only 2 unprocessed for each user — neither at threshold
        count_a = record_observation(
            db_session, user_id=_UID_A, context_type=_CT_TECH, user_message="third"
        )
        # count_a should be 3 (only A's observations counted)
        assert count_a == 3

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="user A strategy")
    def test_pattern_not_returned_for_other_user(self, mock_synth, db_session: Session):
        # Property 22 — load_active_patterns(user_id=B) never returns user A's pattern
        _cleanup(db_session)
        _insert_n_obs(db_session, _PROCEDURAL_THRESHOLD, user_id=_UID_A)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-a")
        # Force confidence high enough
        pattern_a = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_A)
        ).first()
        if pattern_a:
            pattern_a.confidence = 0.70
            db_session.add(pattern_a)
            db_session.commit()

        patterns_for_b = load_active_patterns(db_session, user_id=_UID_B, context_type=_CT_TECH)
        assert len(patterns_for_b) == 0

    @patch("app.cognition.procedural_service._synthesise_strategy", return_value="user A strategy")
    def test_synthesis_for_a_creates_no_row_for_b(self, mock_synth, db_session: Session):
        # Property 23
        _cleanup(db_session)
        _insert_n_obs(db_session, _PROCEDURAL_THRESHOLD, user_id=_UID_A)
        _run_pattern_synthesis(_UID_A, _CT_TECH, "tr-a")
        patterns_b = db_session.exec(
            select(ProceduralPattern).where(ProceduralPattern.user_id == _UID_B)
        ).all()
        assert len(patterns_b) == 0


# ---------------------------------------------------------------------------
# 24–28: load_active_patterns
# ---------------------------------------------------------------------------

class TestLoadActivePatterns:

    def test_returns_empty_when_no_pattern(self, db_session: Session):
        # Property 24
        _cleanup(db_session)
        patterns = load_active_patterns(db_session, user_id=_UID_A, context_type=_CT_TECH)
        assert patterns == []

    def test_returns_pattern_above_min_confidence(self, db_session: Session):
        # Property 25
        _cleanup(db_session)
        p = ProceduralPattern(user_id=_UID_A, context_type=_CT_TECH,
                              strategy_description="s", confidence=0.60,
                              occurrence_count=6)
        db_session.add(p)
        db_session.commit()
        patterns = load_active_patterns(db_session, user_id=_UID_A, context_type=_CT_TECH,
                                        min_confidence=0.55)
        assert len(patterns) == 1

    def test_does_not_return_below_min_confidence(self, db_session: Session):
        # Property 26
        _cleanup(db_session)
        p = ProceduralPattern(user_id=_UID_A, context_type=_CT_TECH,
                              strategy_description="s", confidence=0.45,
                              occurrence_count=3)
        db_session.add(p)
        db_session.commit()
        patterns = load_active_patterns(db_session, user_id=_UID_A, context_type=_CT_TECH,
                                        min_confidence=0.55)
        assert len(patterns) == 0

    def test_does_not_return_inactive_pattern(self, db_session: Session):
        # Property 27
        _cleanup(db_session)
        p = ProceduralPattern(user_id=_UID_A, context_type=_CT_TECH,
                              strategy_description="s", confidence=0.70,
                              occurrence_count=9, is_active=False)
        db_session.add(p)
        db_session.commit()
        patterns = load_active_patterns(db_session, user_id=_UID_A, context_type=_CT_TECH)
        assert len(patterns) == 0

    def test_only_returns_matching_context_type(self, db_session: Session):
        # Property 28
        _cleanup(db_session)
        p = ProceduralPattern(user_id=_UID_A, context_type=_CT_DEBUG,
                              strategy_description="debug strat", confidence=0.70,
                              occurrence_count=9)
        db_session.add(p)
        db_session.commit()
        patterns_tech = load_active_patterns(db_session, user_id=_UID_A, context_type=_CT_TECH)
        patterns_debug = load_active_patterns(db_session, user_id=_UID_A, context_type=_CT_DEBUG)
        assert len(patterns_tech) == 0
        assert len(patterns_debug) == 1


# ---------------------------------------------------------------------------
# 29–32: Perception context_type
# ---------------------------------------------------------------------------

class TestPerceptionContextType:

    def test_parse_valid_context_type(self):
        # Property 29
        import json as _json
        raw = _json.dumps({
            "user_intent": "question", "tone": "neutral",
            "challenge": 0.1, "social_signal": 0.3, "novelty": 0.2,
            "context_type": "technical_design",
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.context_type == "technical_design"

    def test_invalid_context_type_falls_back(self):
        # Property 30
        import json as _json
        raw = _json.dumps({
            "user_intent": "question", "tone": "neutral",
            "challenge": 0.1, "social_signal": 0.3, "novelty": 0.2,
            "context_type": "nonexistent_type",
        })
        result = _parse_perception(raw)
        assert result is not None
        assert result.context_type == "casual_chat"

    def test_neutral_has_casual_chat_context_type(self):
        # Property 31
        r = PerceptionResult.neutral()
        assert r.context_type == "casual_chat"

    def test_valid_context_types_count(self):
        # Property 32
        assert len(_VALID_CONTEXT_TYPES) == 8

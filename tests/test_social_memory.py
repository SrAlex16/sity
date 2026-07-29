"""Tests for Social Memory — Fase 4, Pasos 2 y 3.

Paso 2 properties:
1. <R:N> tag is always stripped before save_message and before user delivery.
2. Valid tag stores load value in SocialProfile.pending_loads_json.
3. Missing tag logs WARN for user: sessions; silent for guest:/other sessions.
4. Out-of-range value (<R:99>) logs WARN and still strips the malformed tag.
5. Guest session never gets a SocialProfile row.
6. Persona prompt includes turn_load_instruction for user: sessions only.
7. _append_pending_load is safe under concurrent calls (atomic SQL upsert).

Paso 3 properties:
8. compute_batch_opinion formula correctness.
9. compute_trust formula correctness (three reference cases).
10. _run_social_update clears pending_loads and updates opinion/trust atomically.
11. Empty pending_loads → early return with no state change.
12. Atomicity on failure: exception before commit leaves DB unchanged.
13. Snapshot semantics: loads arriving while update runs are NOT consumed.
"""
from __future__ import annotations

import json
import statistics
import time
import threading
from typing import Any
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from app.chat.final_response_builder import (
    _append_pending_load,
    _strip_turn_load_tag,
    build_final_ai_response,
)
from app.core.persona_engine import PersonaEngine
from app.cortex.schemas import AIResponse, AIUsageData
from app.memory.models import OpinionSnapshot, SocialProfile
from app.social.update import (
    _run_social_update,
    compute_batch_opinion,
    compute_trust,
)


# ---------------------------------------------------------------------------
# Unit tests for _strip_turn_load_tag
# ---------------------------------------------------------------------------

def test_strip_removes_tag_at_end() -> None:
    text, raw = _strip_turn_load_tag("Hola mundo.<R:+1>")
    assert raw == "+1"
    assert text == "Hola mundo."
    assert "<R:" not in text


def test_strip_removes_tag_with_trailing_whitespace() -> None:
    text, raw = _strip_turn_load_tag("Texto aquí.<R:0>  \n")
    assert raw == "0"
    assert "<R:" not in text


def test_strip_removes_negative_tag() -> None:
    text, raw = _strip_turn_load_tag("Respuesta difícil.<R:-2>")
    assert raw == "-2"
    assert "<R:" not in text


def test_strip_no_match_returns_text_unchanged() -> None:
    original = "Sin tag aquí."
    text, raw = _strip_turn_load_tag(original)
    assert raw is None
    assert text == original


def test_strip_tag_mid_sentence_not_matched() -> None:
    # Tag NOT at end of string should not match
    original = "Texto <R:+1> más texto."
    text, raw = _strip_turn_load_tag(original)
    assert raw is None
    assert text == original


def test_strip_out_of_range_value_still_stripped() -> None:
    # <R:99> is invalid but should still be stripped from text
    text, raw = _strip_turn_load_tag("Respuesta.<R:99>")
    assert raw == "99"
    assert "<R:" not in text


# ---------------------------------------------------------------------------
# Unit tests for _append_pending_load
# ---------------------------------------------------------------------------

def _clear_profile(session: Session, user_id: int) -> None:
    profile = session.exec(select(SocialProfile).where(SocialProfile.user_id == user_id)).first()
    if profile:
        session.delete(profile)
        session.commit()


def test_append_creates_profile_if_missing(db_session: Session) -> None:
    _clear_profile(db_session, 9901)
    _append_pending_load(db_session, "user:9901", 1)
    db_session.commit()
    profile = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == 9901)).first()
    assert profile is not None
    assert json.loads(profile.pending_loads_json) == [1]


def test_append_accumulates_loads(db_session: Session) -> None:
    _clear_profile(db_session, 9902)
    _append_pending_load(db_session, "user:9902", 1)
    db_session.commit()
    _append_pending_load(db_session, "user:9902", -1)
    db_session.commit()
    _append_pending_load(db_session, "user:9902", 0)
    db_session.commit()
    profile = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == 9902)).first()
    assert json.loads(profile.pending_loads_json) == [1, -1, 0]


def test_append_invalid_session_id_is_silent(db_session: Session) -> None:
    # Should not raise, should not create any row
    _append_pending_load(db_session, "guest:abc", 1)
    db_session.commit()
    _append_pending_load(db_session, "malformed", 0)
    db_session.commit()
    # No SocialProfile created for these
    row = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == 0)).first()
    assert row is None


# ---------------------------------------------------------------------------
# Integration: build_final_ai_response strips tag before save and return
# ---------------------------------------------------------------------------

def _make_response(text: str) -> AIResponse:
    return AIResponse(
        ok=True,
        provider="mock",
        model="mock-model",
        text=text,
        usage=AIUsageData(input_tokens=10, output_tokens=5),
        latency_ms=100,
        fallback_used=False,
    )


def _run_build_final(
    db_session: Session,
    response_text: str,
    session_id: str = "user:1",
    captured_saves: list[str] | None = None,
) -> tuple[Any, list[str]]:
    """Call build_final_ai_response with a minimal mock context."""
    saved: list[str] = captured_saves if captured_saves is not None else []

    def _save(*, role: str, text: str, **_kwargs: Any) -> None:
        saved.append(text)

    result = build_final_ai_response(
        session=db_session,
        trace_id="trc_test_social",
        response=_make_response(response_text),
        daily_budget=100_000,
        warning_threshold=0.7,
        critical_threshold=0.9,
        get_today_token_usage=lambda s: 0,
        save_message=_save,
        refusal_mode=False,
        user_message="hola",
        updated_parameters=[],
        artifacts=[],
        session_id=session_id,
    )
    return result, saved


def test_tag_stripped_from_returned_response_text(db_session: Session) -> None:
    result, _ = _run_build_final(db_session, "Respuesta normal.<R:+1>")
    assert "<R:" not in result.text
    assert result.text == "Respuesta normal."


def test_tag_stripped_from_saved_message(db_session: Session) -> None:
    _, saved = _run_build_final(db_session, "Texto guardado.<R:0>")
    sity_text = saved[-1]  # last save is the sity message
    assert "<R:" not in sity_text


def test_tag_stripped_even_when_value_invalid(db_session: Session) -> None:
    result, saved = _run_build_final(db_session, "Respuesta.<R:99>")
    assert "<R:" not in result.text
    assert all("<R:" not in s for s in saved)


def test_valid_tag_creates_pending_load(db_session: Session) -> None:
    uid = 9910
    _clear_profile(db_session, uid)
    _run_build_final(db_session, "Respuesta.<R:+2>", session_id=f"user:{uid}")
    profile = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
    assert profile is not None
    assert 2 in json.loads(profile.pending_loads_json)


def test_guest_session_no_profile_created(db_session: Session) -> None:
    result, _ = _run_build_final(db_session, "Hola guest.<R:+1>", session_id="guest:abc123")
    # Guest: tag is stripped but no SocialProfile created
    assert "<R:" not in result.text
    # There should be no SocialProfile for any user matching guest session
    # (guest: prefix → _append_pending_load bails early)
    all_profiles = db_session.exec(select(SocialProfile)).all()
    for p in all_profiles:
        # Any existing profile should not correspond to a "guest:" session parse
        assert p.user_id > 0


# ---------------------------------------------------------------------------
# Logging: WARN emitted for missing or invalid tags
# ---------------------------------------------------------------------------

def test_missing_tag_logs_warning_for_user_session(db_session: Session) -> None:
    with patch("app.chat.final_response_builder.write_log") as mock_log:
        _run_build_final(db_session, "Sin tag aquí.", session_id="user:1")

    warn_calls = [
        call for call in mock_log.call_args_list
        if call.kwargs.get("event") == "turn_load_tag_missing"
    ]
    assert len(warn_calls) == 1
    assert warn_calls[0].kwargs["level"] == "WARN"
    assert warn_calls[0].kwargs["payload"]["session_id"] == "user:1"


def test_missing_tag_no_warning_for_guest_session(db_session: Session) -> None:
    with patch("app.chat.final_response_builder.write_log") as mock_log:
        _run_build_final(db_session, "Sin tag.", session_id="guest:abc")

    social_warns = [
        call for call in mock_log.call_args_list
        if call.kwargs.get("module") == "social"
    ]
    assert len(social_warns) == 0


def test_invalid_tag_value_logs_warning(db_session: Session) -> None:
    with patch("app.chat.final_response_builder.write_log") as mock_log:
        _run_build_final(db_session, "Respuesta.<R:99>", session_id="user:1")

    invalid_calls = [
        call for call in mock_log.call_args_list
        if call.kwargs.get("event") == "turn_load_tag_invalid"
    ]
    assert len(invalid_calls) == 1
    assert invalid_calls[0].kwargs["payload"]["raw_value"] == "99"


# ---------------------------------------------------------------------------
# Concurrency: atomic upsert preserves both loads
# ---------------------------------------------------------------------------

def test_concurrent_writes_preserve_all_loads() -> None:
    """Two threads writing to the same user_id must not lose each other's loads.

    The old read-modify-write pattern (SELECT → json.loads → append → UPDATE)
    would silently drop the first load if the second thread read before the
    first committed.  The atomic INSERT...ON CONFLICT...DO UPDATE with
    json_insert fixes this: each call is a single SQL statement that SQLite
    executes as one serialised unit.
    """
    from app.memory.db import engine

    uid = 9960
    # Clean up any leftover state from previous runs
    with Session(engine) as setup_sess:
        existing = setup_sess.exec(
            select(SocialProfile).where(SocialProfile.user_id == uid)
        ).first()
        if existing:
            setup_sess.delete(existing)
            setup_sess.commit()

    errors: list[Exception] = []

    def write_load(load: int) -> None:
        try:
            with Session(engine) as sess:
                _append_pending_load(sess, f"user:{uid}", load)
                sess.commit()
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=write_load, args=(1,))
    t2 = threading.Thread(target=write_load, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"concurrent writes raised: {errors}"

    with Session(engine) as verify_sess:
        profile = verify_sess.exec(
            select(SocialProfile).where(SocialProfile.user_id == uid)
        ).first()
        assert profile is not None
        loads = json.loads(profile.pending_loads_json)
        assert 1 in loads, f"load 1 missing from {loads}"
        assert 2 in loads, f"load 2 missing from {loads}"
        assert len(loads) == 2, f"expected exactly 2 loads, got {loads}"


# ---------------------------------------------------------------------------
# Persona prompt: turn_load_instruction injected only for user: sessions
# ---------------------------------------------------------------------------

def test_turn_load_instruction_in_user_prompt() -> None:
    engine = PersonaEngine()
    result = engine.build_persona_prompt({}, "hola", session_id="user:1")
    assert "INSTRUCCIÓN INTERNA — ETIQUETA DE CARGA CONVERSACIONAL" in result.system_prompt
    assert "<R:N>" in result.system_prompt


def test_turn_load_instruction_absent_for_guest_prompt() -> None:
    engine = PersonaEngine()
    result = engine.build_persona_prompt({}, "hola", session_id="guest:abc")
    assert "ETIQUETA DE CARGA CONVERSACIONAL" not in result.system_prompt
    assert "<R:N>" not in result.system_prompt


def test_turn_load_instruction_absent_for_default_session() -> None:
    engine = PersonaEngine()
    result = engine.build_persona_prompt({}, "hola", session_id="")
    assert "ETIQUETA DE CARGA CONVERSACIONAL" not in result.system_prompt


# ===========================================================================
# Paso 3 — formula unit tests
# ===========================================================================

class TestComputeBatchOpinion:
    def test_all_neutral(self) -> None:
        assert compute_batch_opinion([0, 0, 0]) == 0.0

    def test_all_max_positive(self) -> None:
        # load=+2, weight=3 → raw=2.0 → normalized=1.0
        assert compute_batch_opinion([2, 2, 2]) == pytest.approx(1.0)

    def test_all_max_negative(self) -> None:
        assert compute_batch_opinion([-2, -2, -2]) == pytest.approx(-1.0)

    def test_symmetric_cancels(self) -> None:
        # +2 and -2 have same weight → cancel out
        assert compute_batch_opinion([2, -2]) == pytest.approx(0.0)

    def test_asymmetric_positive(self) -> None:
        # loads=[+2, 0]: w=[3,1], sum=6, total_w=4, raw=1.5, norm=0.75
        assert compute_batch_opinion([2, 0]) == pytest.approx(0.75)

    def test_single_positive_one(self) -> None:
        # load=+1, weight=2 → raw=1.0 → norm=0.5
        assert compute_batch_opinion([1]) == pytest.approx(0.5)

    def test_empty_returns_zero(self) -> None:
        assert compute_batch_opinion([]) == 0.0

    def test_extremes_weighted_more(self) -> None:
        # Extreme loads have more weight, so batch should skew toward them
        # [+2, +1, 0] vs [+1, +1, +1]: the first should give higher opinion
        opinion_with_extreme = compute_batch_opinion([2, 1, 0])
        opinion_uniform = compute_batch_opinion([1, 1, 1])
        assert opinion_with_extreme > opinion_uniform


class TestComputeTrust:
    # Reference case 1: 1 year known, perfectly stable opinion history
    def test_long_stable_yields_max_trust(self) -> None:
        from datetime import timedelta
        now = _utcnow()
        created_at = (now - timedelta(days=365)).isoformat()
        trust = compute_trust(
            created_at_str=created_at,
            snapshot_opinions=[0.5, 0.5, 0.5],
            now=now,
        )
        assert trust == pytest.approx(1.0, abs=1e-6)

    # Reference case 2: 1 year, strong negative outlier but generally positive
    def test_long_with_outlier_trust_reduced(self) -> None:
        from datetime import timedelta
        now = _utcnow()
        created_at = (now - timedelta(days=365)).isoformat()
        opinions = [0.5, 0.5, 0.5, 0.5, -0.8]
        std_dev = statistics.pstdev(opinions)
        stability_factor = max(0.0, 1.0 - std_dev)
        expected_trust = 1.0 * (0.5 + 0.5 * stability_factor)
        trust = compute_trust(
            created_at_str=created_at,
            snapshot_opinions=opinions,
            now=now,
        )
        assert trust == pytest.approx(expected_trust, abs=1e-6)
        # Trust is reduced compared to perfect stability, but still > 0.5
        assert trust < 1.0
        assert trust > 0.5

    # Reference case 3: brand-new user (1 day), no history
    def test_new_user_near_zero_trust(self) -> None:
        from datetime import timedelta
        now = _utcnow()
        created_at = (now - timedelta(days=1)).isoformat()
        trust = compute_trust(
            created_at_str=created_at,
            snapshot_opinions=[0.0],
            now=now,
        )
        expected = (1.0 / 365.0) * 1.0  # time_factor × max_stability
        assert trust == pytest.approx(expected, abs=1e-6)
        assert trust < 0.01

    def test_single_snapshot_full_stability(self) -> None:
        # Only 1 snapshot → pstdev undefined, stability_factor = 1.0
        from datetime import timedelta
        now = _utcnow()
        created_at = (now - timedelta(days=180)).isoformat()
        trust = compute_trust(
            created_at_str=created_at,
            snapshot_opinions=[0.3],
            now=now,
        )
        time_factor = min(1.0, 180 / 365)
        assert trust == pytest.approx(time_factor * 1.0, abs=1e-6)

    def test_very_volatile_caps_stability_at_zero(self) -> None:
        # Extreme volatility: pstdev >= 1.0 → stability_factor = 0.0
        from datetime import timedelta
        now = _utcnow()
        created_at = (now - timedelta(days=365)).isoformat()
        opinions = [1.0, -1.0, 1.0, -1.0]  # pstdev = 1.0
        trust = compute_trust(
            created_at_str=created_at,
            snapshot_opinions=opinions,
            now=now,
        )
        # stability_factor = max(0, 1 - 1.0) = 0 → trust = 1.0 × 0.5 = 0.5
        assert trust == pytest.approx(0.5, abs=1e-4)


def _utcnow() -> "datetime":
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _setup_profile_with_loads(engine: Any, uid: int, loads: list[int]) -> None:
    """Create a fresh SocialProfile with the given pending loads."""
    with Session(engine) as sess:
        existing = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
        if existing:
            # Also delete associated snapshots
            snaps = sess.exec(select(OpinionSnapshot).where(OpinionSnapshot.profile_id == existing.id)).all()
            for s in snaps:
                sess.delete(s)
            sess.delete(existing)
            sess.commit()
        for load in loads:
            _append_pending_load(sess, f"user:{uid}", load)
        sess.commit()


# ===========================================================================
# Paso 3 — _run_social_update integration tests
# ===========================================================================

class TestRunSocialUpdate:
    def test_basic_update_clears_loads_and_updates_opinion(self) -> None:
        from app.memory.db import engine
        uid = 9980
        _setup_profile_with_loads(engine, uid, [1, 1, 1, 1, 1, 1, 1, 1, 1, 1])

        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            assert json.loads(profile.pending_loads_json) == [], "pending_loads should be empty after update"
            assert profile.opinion == pytest.approx(0.15, abs=1e-6), (
                "10 loads of +1 → batch_norm=0.5, new_opinion=0.3×0.5+0.7×0.0=0.15"
            )
            assert profile.trust >= 0.0
            assert profile.last_updated_at is not None

        with Session(engine) as sess:
            snaps = sess.exec(select(OpinionSnapshot).where(
                OpinionSnapshot.profile_id != 0
            )).all()
            matching = [s for s in snaps if abs(s.opinion_value - 0.15) < 1e-4]
            assert len(matching) >= 1, "OpinionSnapshot should have been inserted with opinion ≈ 0.15"

    def test_empty_pending_loads_returns_early(self) -> None:
        from app.memory.db import engine
        uid = 9981
        _setup_profile_with_loads(engine, uid, [])

        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            # Profile may not exist (no loads were added, so _append_pending_load created '[]')
            # In either case, pending_loads should not have been cleared or opinion changed
            if profile is not None:
                assert profile.opinion == 0.0, "opinion must not change if no loads"
                assert profile.trust == 0.0

    def test_nonexistent_profile_returns_early(self) -> None:
        # Should not raise; nothing in DB for this uid
        _run_social_update(999999, "test_trace")

    def test_second_run_accumulates_ema(self) -> None:
        from app.memory.db import engine
        uid = 9982
        _setup_profile_with_loads(engine, uid, [2, 2, 2, 2, 2, 2, 2, 2, 2, 2])
        _run_social_update(uid, "test_trace")  # first batch: all +2

        with Session(engine) as sess:
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            _append_pending_load(sess, f"user:{uid}", -2)
            sess.commit()
        _run_social_update(uid, "test_trace")  # second batch: all -2

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            # After first run: opinion = 0.3×1.0 + 0.7×0.0 = 0.30
            # After second run: opinion = 0.3×(-1.0) + 0.7×0.30 = -0.30 + 0.21 = -0.09
            assert profile.opinion == pytest.approx(-0.09, abs=1e-6)

    # -----------------------------------------------------------------------
    # Case 2 (edge): atomicity — exception before commit leaves DB unchanged
    # -----------------------------------------------------------------------

    def test_atomicity_exception_before_commit_leaves_state_unchanged(self) -> None:
        """Simulate a crash mid-job: pending_loads and opinion must not change.

        This mirrors the real-world scenario of a backend restart while the
        daemon thread is in progress (same invariant as bg_after_tools).
        """
        from app.memory.db import engine
        uid = 9983
        original_loads = [1, -1, 2]
        _setup_profile_with_loads(engine, uid, original_loads)

        # Capture state before the failed run
        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            pre_opinion = profile.opinion
            pre_trust = profile.trust
            pre_loads = json.loads(profile.pending_loads_json)
            pre_snapshot_count = len(
                sess.exec(select(OpinionSnapshot).where(OpinionSnapshot.profile_id == profile.id)).all()
            )

        def blow_up() -> None:
            raise RuntimeError("simulated mid-job failure")

        _run_social_update(uid, "test_trace", _test_hook_before_commit=blow_up)

        # Verify: DB state must be identical to before the failed run
        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            assert json.loads(profile.pending_loads_json) == pre_loads, (
                "pending_loads_json must be unchanged after rollback"
            )
            assert profile.opinion == pytest.approx(pre_opinion, abs=1e-9), (
                "opinion must be unchanged after rollback"
            )
            assert profile.trust == pytest.approx(pre_trust, abs=1e-9), (
                "trust must be unchanged after rollback"
            )
            post_snapshot_count = len(
                sess.exec(select(OpinionSnapshot).where(OpinionSnapshot.profile_id == profile.id)).all()
            )
            assert post_snapshot_count == pre_snapshot_count, (
                "no OpinionSnapshot must be inserted after rollback"
            )

    # -----------------------------------------------------------------------
    # Case 1 (edge): snapshot semantics — loads arriving during update are not lost
    # -----------------------------------------------------------------------

    def test_snapshot_semantics_concurrent_load_not_consumed(self) -> None:
        """Loads appended while update runs must survive to the next cycle.

        _run_social_update holds BEGIN IMMEDIATE before reading pending_loads.
        Any concurrent _append_pending_load is therefore serialised AFTER
        the commit: it appends to the cleared '[]', not to the snapshot being
        processed.  This test proves that property with real threads.
        """
        from app.memory.db import engine
        uid = 9984
        _setup_profile_with_loads(engine, uid, [1] * 10)

        concurrent_write_started = threading.Event()
        concurrent_write_done = threading.Event()

        def concurrent_write_fn() -> None:
            concurrent_write_started.set()  # signal: thread is running
            # This write is blocked by _run_social_update's BEGIN IMMEDIATE lock.
            # It will proceed only after _run_social_update commits.
            with Session(engine) as bg_sess:
                _append_pending_load(bg_sess, f"user:{uid}", 99)
                bg_sess.commit()
            concurrent_write_done.set()

        def hook_after_read() -> None:
            # Fire the concurrent writer while the write lock is held.
            t = threading.Thread(target=concurrent_write_fn, daemon=True)
            t.start()
            # Wait for the thread to have started (it will then block on the write lock)
            concurrent_write_started.wait(timeout=2.0)
            # Small pause to let the thread reach and block on the SQLite write lock
            time.sleep(0.1)
            # Return: _run_social_update continues to commit, unblocking the thread

        _run_social_update(uid, "test_trace", _test_hook_after_read=hook_after_read)

        # Wait for the concurrent write to complete after the lock was released
        assert concurrent_write_done.wait(timeout=5.0), (
            "concurrent write did not complete within 5 s after update committed"
        )

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            remaining = json.loads(profile.pending_loads_json)
            assert remaining == [99], (
                f"expected only the concurrent load [99] in pending_loads, got {remaining}"
            )
            # The batch of 10×(+1) was processed: opinion should be ~0.15
            assert profile.opinion == pytest.approx(0.15, abs=1e-6), (
                f"opinion should be 0.15 from the batch of 10×(+1), got {profile.opinion}"
            )

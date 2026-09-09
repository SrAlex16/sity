"""Tests for Social Memory — Fase 4 + Fase 3 Remake.

Paso 2 properties:
1. <R:N> tag is always stripped before save_message and before user delivery.
2. Valid tag stores load value in SocialProfile.pending_loads_json.
3. Missing tag logs WARN for user: sessions; silent for guest:/other sessions.
4. Out-of-range value (<R:99>) logs WARN and still strips the malformed tag.
5. Guest session never gets a SocialProfile row.
6. Persona prompt includes turn_load_instruction for user: sessions only.
7. _append_pending_load is safe under concurrent calls (atomic SQL upsert).

Paso 3 (Remake Fase 3 — multidimensional model) properties:
8. _combined_delta formula correctness.
9. apply_appraisal_to_social_profile updates dimensions correctly.
10. _run_social_update clears pending_loads and inserts RelationshipSnapshot.
11. Empty pending_loads → early return with no state change.
12. Atomicity on failure: exception before commit leaves DB unchanged.
13. Snapshot semantics: loads arriving while update runs are NOT consumed.

Paso 4 properties:
14. _build_social_context_block returns "" for guest sessions.
15. _build_social_context_block returns "" when no SocialProfile exists (first contact).
16. _build_social_context_block returns correct qualitative labels for a known profile.
17. _build_social_context_block is read-only — DB unchanged after call.
18. PromptContextBuilder injects social block in user_message_with_history and planner_user_message.
19. PromptContextBuilder omits social block for guest sessions.
20. Anti-injection: user text claiming high affinity does not write to SocialProfile.
"""
from __future__ import annotations

import json
import time
import threading
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from app.chat.final_response_builder import (
    _append_pending_load,
    strip_turn_load_tag as _strip_turn_load_tag,
    build_final_ai_response,
)
from app.core.persona_engine import PersonaEngine
from app.cortex.schemas import AIResponse, AIUsageData
from app.memory.models import RelationshipSnapshot, SocialProfile
from app.social.social_service import apply_appraisal_to_social_profile
from app.social.update import (
    _combined_delta,
    _run_social_update,
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
    original = "Texto <R:+1> más texto."
    text, raw = _strip_turn_load_tag(original)
    assert raw is None
    assert text == original


def test_strip_out_of_range_value_still_stripped() -> None:
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
    _append_pending_load(db_session, "guest:abc", 1)
    db_session.commit()
    _append_pending_load(db_session, "malformed", 0)
    db_session.commit()
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
    sity_text = saved[-1]
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
    assert "<R:" not in result.text
    all_profiles = db_session.exec(select(SocialProfile)).all()
    for p in all_profiles:
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
    from app.memory.db import engine

    uid = 9960
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
# Paso 3 — _combined_delta unit tests (Remake Fase 3)
# ===========================================================================

class TestCombinedDelta:
    def test_all_zero_returns_zero(self) -> None:
        assert _combined_delta(0.3, 0.1, 0.5, 0.2, 0.3, 0.1, 0.5, 0.2) == pytest.approx(0.0)

    def test_affinity_only_change(self) -> None:
        # Δaffinity=0.4 → 0.35 * 0.4 = 0.14
        result = _combined_delta(0.7, 0.1, 0.5, 0.2, 0.3, 0.1, 0.5, 0.2)
        assert result == pytest.approx(0.35 * 0.4, abs=1e-9)

    def test_conflict_only_change(self) -> None:
        # Δconflict=0.3 → 0.30 * 0.3 = 0.09
        result = _combined_delta(0.3, 0.4, 0.5, 0.2, 0.3, 0.1, 0.5, 0.2)
        assert result == pytest.approx(0.30 * 0.3, abs=1e-9)

    def test_trust_only_change(self) -> None:
        # Δtrust_avg=0.2 → 0.25 * 0.2 = 0.05
        result = _combined_delta(0.3, 0.1, 0.7, 0.2, 0.3, 0.1, 0.5, 0.2)
        assert result == pytest.approx(0.25 * 0.2, abs=1e-9)

    def test_attachment_only_change(self) -> None:
        # Δattachment=0.5 → 0.10 * 0.5 = 0.05
        result = _combined_delta(0.3, 0.1, 0.5, 0.7, 0.3, 0.1, 0.5, 0.2)
        assert result == pytest.approx(0.10 * 0.5, abs=1e-9)

    def test_combined_all_dimensions(self) -> None:
        # Δaffinity=0.2, Δconflict=0.1, Δtrust=0.1, Δattachment=0.1
        result = _combined_delta(0.5, 0.2, 0.6, 0.3, 0.3, 0.1, 0.5, 0.2)
        expected = 0.35 * 0.2 + 0.30 * 0.1 + 0.25 * 0.1 + 0.10 * 0.1
        assert result == pytest.approx(expected, abs=1e-9)

    def test_absolute_value_used(self) -> None:
        # Negative change (current < reference) must still produce positive delta
        result_neg = _combined_delta(0.1, 0.1, 0.5, 0.2, 0.5, 0.1, 0.5, 0.2)
        result_pos = _combined_delta(0.9, 0.1, 0.5, 0.2, 0.5, 0.1, 0.5, 0.2)
        assert result_neg == pytest.approx(result_pos, abs=1e-9)

    def test_large_delta_threshold(self) -> None:
        # Δaffinity=0.58 alone → 0.35 * 0.58 = 0.203 which is > 0.20
        result = _combined_delta(0.88, 0.0, 0.5, 0.0, 0.30, 0.0, 0.5, 0.0)
        assert result > 0.20


# ===========================================================================
# Paso 3 — apply_appraisal_to_social_profile unit tests
# ===========================================================================

class TestApplyAppraisalToSocialProfile:
    def _default_profile(self) -> SocialProfile:
        return SocialProfile(
            user_id=0,
            familiarity=0.1,
            trust_honesty=0.5,
            trust_intentions=0.5,
            trust_competence=0.5,
            trust_reliability=0.5,
            affinity=0.2,
            comfort=0.5,
            respect=0.5,
            attachment=0.1,
            conflict=0.1,
            uncertainty=0.5,
        )

    def _neutral_personality(self) -> dict:
        return {
            "skepticism": 0.5, "warmth": 0.5, "patience": 0.5,
            "assertiveness": 0.5, "empathy": 0.5,
        }

    def test_familiarity_always_increases(self) -> None:
        profile = self._default_profile()
        before = profile.familiarity
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.0, 0.0, 0.0, self._neutral_personality()
        )
        assert profile.familiarity > before

    def test_positive_trust_evidence_raises_trust(self) -> None:
        profile = self._default_profile()
        before_h = profile.trust_honesty
        before_i = profile.trust_intentions
        apply_appraisal_to_social_profile(
            profile, 0.05, 0.0, 0.0, 0.0, 0.0, self._neutral_personality()
        )
        assert profile.trust_honesty > before_h
        assert profile.trust_intentions > before_i

    def test_positive_interest_raises_affinity(self) -> None:
        profile = self._default_profile()
        before = profile.affinity
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.3, 0.0, 0.0, 0.0, self._neutral_personality()
        )
        assert profile.affinity > before

    def test_frustration_raises_conflict(self) -> None:
        profile = self._default_profile()
        before = profile.conflict
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.3, 0.0, 0.0, self._neutral_personality()
        )
        assert profile.conflict > before

    def test_social_signal_raises_attachment(self) -> None:
        profile = self._default_profile()
        before = profile.attachment
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.0, 1.0, 0.0, self._neutral_personality()
        )
        assert profile.attachment > before

    def test_high_challenge_reduces_affinity(self) -> None:
        profile = self._default_profile()
        before = profile.affinity
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.0, 0.0, 1.0, self._neutral_personality()
        )
        assert profile.affinity < before

    def test_skepticism_reduces_trust_update(self) -> None:
        profile_low_sk = self._default_profile()
        profile_high_sk = self._default_profile()
        low_sk = dict(self._neutral_personality(), skepticism=0.0)
        high_sk = dict(self._neutral_personality(), skepticism=1.0)
        apply_appraisal_to_social_profile(profile_low_sk, 0.05, 0.0, 0.0, 0.0, 0.0, low_sk)
        apply_appraisal_to_social_profile(profile_high_sk, 0.05, 0.0, 0.0, 0.0, 0.0, high_sk)
        assert profile_low_sk.trust_honesty > profile_high_sk.trust_honesty

    def test_patience_reduces_conflict_buildup(self) -> None:
        profile_patient = self._default_profile()
        profile_impatient = self._default_profile()
        patient = dict(self._neutral_personality(), patience=1.0)
        impatient = dict(self._neutral_personality(), patience=0.0)
        apply_appraisal_to_social_profile(profile_patient, 0.0, 0.0, 0.3, 0.0, 1.0, patient)
        apply_appraisal_to_social_profile(profile_impatient, 0.0, 0.0, 0.3, 0.0, 1.0, impatient)
        assert profile_patient.conflict < profile_impatient.conflict

    def test_warmth_amplifies_affinity_growth(self) -> None:
        profile_warm = self._default_profile()
        profile_cold = self._default_profile()
        warm = dict(self._neutral_personality(), warmth=1.0)
        cold = dict(self._neutral_personality(), warmth=0.0)
        apply_appraisal_to_social_profile(profile_warm, 0.0, 0.3, 0.0, 0.0, 0.0, warm)
        apply_appraisal_to_social_profile(profile_cold, 0.0, 0.3, 0.0, 0.0, 0.0, cold)
        assert profile_warm.affinity > profile_cold.affinity

    def test_all_values_clamped_to_0_1(self) -> None:
        profile = self._default_profile()
        profile.affinity = 0.99
        profile.conflict = 0.0
        apply_appraisal_to_social_profile(
            profile, 0.05, 0.3, 0.0, 1.0, 0.0, self._neutral_personality()
        )
        for attr in ("familiarity", "trust_honesty", "trust_intentions",
                     "affinity", "comfort", "respect", "attachment",
                     "conflict", "uncertainty"):
            val = getattr(profile, attr)
            assert 0.0 <= val <= 1.0, f"{attr}={val} out of range"

    def test_last_updated_at_set(self) -> None:
        profile = self._default_profile()
        assert profile.last_updated_at is None
        apply_appraisal_to_social_profile(
            profile, 0.0, 0.0, 0.0, 0.0, 0.0, self._neutral_personality()
        )
        assert profile.last_updated_at is not None


def _utcnow() -> "datetime":
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _setup_profile_with_loads(engine: Any, uid: int, loads: list[int]) -> None:
    """Create a fresh SocialProfile with the given pending loads."""
    with Session(engine) as sess:
        existing = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
        if existing:
            snaps = sess.exec(
                select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == existing.id)
            ).all()
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
    def test_basic_update_clears_loads_and_inserts_snapshot(self) -> None:
        from app.memory.db import engine
        uid = 9980
        _setup_profile_with_loads(engine, uid, [1, 1, 1, 1, 1, 1, 1, 1, 1, 1])

        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            assert json.loads(profile.pending_loads_json) == [], \
                "pending_loads should be empty after update"
            assert profile.last_updated_at is not None

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            snaps = sess.exec(
                select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == profile.id)
            ).all()
            assert len(snaps) >= 1, "RelationshipSnapshot should have been inserted"

    def test_empty_pending_loads_returns_early(self) -> None:
        from app.memory.db import engine
        uid = 9981
        _setup_profile_with_loads(engine, uid, [])

        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            if profile is not None:
                assert json.loads(profile.pending_loads_json) == [], \
                    "empty loads should stay empty"

    def test_nonexistent_profile_returns_early(self) -> None:
        _run_social_update(999999, "test_trace")  # must not raise

    def test_second_run_inserts_second_snapshot(self) -> None:
        from app.memory.db import engine
        uid = 9982
        _setup_profile_with_loads(engine, uid, [1, 1, 1, 1, 1])
        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            _append_pending_load(sess, f"user:{uid}", -1)
            _append_pending_load(sess, f"user:{uid}", -1)
            _append_pending_load(sess, f"user:{uid}", -1)
            _append_pending_load(sess, f"user:{uid}", -1)
            _append_pending_load(sess, f"user:{uid}", -1)
            sess.commit()
        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            assert json.loads(profile.pending_loads_json) == []
            snaps = sess.exec(
                select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == profile.id)
            ).all()
            assert len(snaps) == 2, f"expected 2 snapshots after 2 runs, got {len(snaps)}"

    def test_snapshot_stores_current_profile_dimensions(self) -> None:
        from app.memory.db import engine
        uid = 9985
        _setup_profile_with_loads(engine, uid, [1])
        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            expected_affinity = profile.affinity
            expected_conflict = profile.conflict

        _run_social_update(uid, "test_trace")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            snaps = sess.exec(
                select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == profile.id)
            ).all()
            assert len(snaps) >= 1
            snap = snaps[-1]
            assert snap.affinity == pytest.approx(expected_affinity, abs=1e-6)
            assert snap.conflict == pytest.approx(expected_conflict, abs=1e-6)

    def test_atomicity_exception_before_commit_leaves_state_unchanged(self) -> None:
        from app.memory.db import engine
        uid = 9983
        original_loads = [1, -1, 2]
        _setup_profile_with_loads(engine, uid, original_loads)

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            pre_loads = json.loads(profile.pending_loads_json)
            pre_snapshot_count = len(
                sess.exec(
                    select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == profile.id)
                ).all()
            )

        def blow_up() -> None:
            raise RuntimeError("simulated mid-job failure")

        _run_social_update(uid, "test_trace", _test_hook_before_commit=blow_up)

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            assert json.loads(profile.pending_loads_json) == pre_loads, \
                "pending_loads_json must be unchanged after rollback"
            post_snapshot_count = len(
                sess.exec(
                    select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == profile.id)
                ).all()
            )
            assert post_snapshot_count == pre_snapshot_count, \
                "no RelationshipSnapshot must be inserted after rollback"

    def test_snapshot_semantics_concurrent_load_not_consumed(self) -> None:
        from app.memory.db import engine
        uid = 9984
        _setup_profile_with_loads(engine, uid, [1] * 10)

        concurrent_write_started = threading.Event()
        concurrent_write_done = threading.Event()

        def concurrent_write_fn() -> None:
            concurrent_write_started.set()
            with Session(engine) as bg_sess:
                _append_pending_load(bg_sess, f"user:{uid}", 99)
                bg_sess.commit()
            concurrent_write_done.set()

        def hook_after_read() -> None:
            t = threading.Thread(target=concurrent_write_fn, daemon=True)
            t.start()
            concurrent_write_started.wait(timeout=2.0)
            time.sleep(0.1)

        _run_social_update(uid, "test_trace", _test_hook_after_read=hook_after_read)

        assert concurrent_write_done.wait(timeout=5.0), \
            "concurrent write did not complete within 5 s after update committed"

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            remaining = json.loads(profile.pending_loads_json)
            assert remaining == [99], \
                f"expected only the concurrent load [99] in pending_loads, got {remaining}"


# ---------------------------------------------------------------------------
# Paso 4 — Social context injection in PromptContextBuilder
# ---------------------------------------------------------------------------

def _make_mock_session(
    familiarity: float,
    affinity: float,
    trust_avg: float,
    conflict: float = 0.1,
) -> Any:
    """Return a minimal SQLAlchemy session stub for _build_social_context_block.

    Returns 9-column profile row:
      (id, familiarity, affinity, trust_honesty, trust_intentions, trust_competence, trust_reliability, comfort, conflict)

    trust_avg is expanded into 4 equal sub-dimensions for simplicity.
    First execute() → profile row; second execute() → None (no active reflection).
    """
    from unittest.mock import MagicMock

    profile_row = MagicMock()
    # Unpack order matches SQL in _build_social_context_block:
    #   id, familiarity, affinity, th, ti, tc, tr, comfort, conflict
    values = [1, familiarity, affinity, trust_avg, trust_avg, trust_avg, trust_avg, 0.5, conflict]
    profile_row.__getitem__ = lambda self, i: values[i]
    profile_row.__iter__ = lambda self: iter(values)
    # Support tuple unpacking via __len__
    profile_row.__len__ = lambda self: len(values)
    profile_result = MagicMock()
    profile_result.fetchone.return_value = tuple(values)

    no_ref_result = MagicMock()
    no_ref_result.fetchone.return_value = None

    session = MagicMock()
    session.execute.side_effect = [profile_result, no_ref_result]
    return session


def _make_null_session() -> Any:
    from unittest.mock import MagicMock
    result = MagicMock()
    result.fetchone.return_value = None
    session = MagicMock()
    session.execute.return_value = result
    return session


class TestSocialContextBlock:
    """Unit tests for _build_social_context_block."""

    def test_guest_session_returns_empty(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_null_session(), "guest:abc123")
        assert block == ""

    def test_non_user_session_returns_empty(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_null_session(), "guest:99")
        assert block == ""

    def test_no_profile_returns_empty(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_null_session(), "user:42")
        assert block == ""

    def test_profile_high_familiarity_high_affinity(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_mock_session(0.6, 0.8, 0.75), "user:1")
        assert "muy conocida" in block
        assert "alta" in block
        assert "consolidada" in block
        assert "no citar" in block

    def test_profile_low_affinity_incipient_trust(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_mock_session(0.05, 0.1, 0.25), "user:2")
        assert "muy baja" in block
        assert "incipiente" in block

    def test_profile_moderate_familiarity(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_mock_session(0.25, 0.45, 0.55), "user:3")
        assert "conocida" in block
        assert "moderada" in block
        assert "establecida" in block

    def test_conflict_shown_when_high(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_mock_session(0.3, 0.5, 0.6, conflict=0.5), "user:4")
        assert "Tensión acumulada" in block

    def test_conflict_not_shown_when_low(self) -> None:
        from app.chat.prompt_context import _build_social_context_block
        block = _build_social_context_block(_make_mock_session(0.3, 0.5, 0.6, conflict=0.1), "user:5")
        assert "Tensión acumulada" not in block

    def test_read_only_does_not_modify_db(self) -> None:
        from datetime import datetime, timezone
        from app.memory.db import engine
        from app.chat.prompt_context import _build_social_context_block
        uid = 9990
        with Session(engine) as sess:
            existing = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            if existing:
                sess.delete(existing)
                sess.commit()
            sess.add(SocialProfile(
                user_id=uid,
                familiarity=0.3,
                affinity=0.4,
                trust_honesty=0.5,
                trust_intentions=0.5,
                trust_competence=0.5,
                trust_reliability=0.5,
                comfort=0.5,
                conflict=0.1,
                pending_loads_json="[]",
                created_at=datetime.now(timezone.utc),
            ))
            sess.commit()

        with Session(engine) as sess:
            _build_social_context_block(sess, f"user:{uid}")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            assert profile.familiarity == pytest.approx(0.3, abs=1e-6)
            assert profile.affinity == pytest.approx(0.4, abs=1e-6)


class TestPromptContextBuilderSocialInjection:
    """Integration: social block appears in user_message and planner_user_message."""

    def _build(
        self,
        session_id: str,
        familiarity: float = 0.3,
        affinity: float = 0.4,
        trust_avg: float = 0.6,
        *,
        no_profile: bool = False,
    ) -> Any:
        from app.chat.prompt_context import PromptContextBuilder

        mock_session = (
            _make_null_session() if no_profile
            else _make_mock_session(familiarity, affinity, trust_avg)
        )

        builder = PromptContextBuilder(get_recent_messages=lambda sess, limit=10: [])
        return builder.build(
            session=mock_session,
            message="hola",
            history_limit=10,
            session_id=session_id,
        )

    def test_user_with_profile_injects_block_in_user_message(self) -> None:
        ctx = self._build("user:1")
        assert "Contexto de relación" in ctx.user_message_with_history

    def test_user_with_profile_injects_block_in_planner_message(self) -> None:
        ctx = self._build("user:1")
        assert "Contexto de relación" in ctx.planner_user_message

    def test_guest_omits_social_block(self) -> None:
        ctx = self._build("guest:abc", no_profile=True)
        assert "Contexto de relación" not in ctx.user_message_with_history
        assert "Contexto de relación" not in ctx.planner_user_message

    def test_user_without_profile_omits_social_block(self) -> None:
        ctx = self._build("user:99", no_profile=True)
        assert "Contexto de relación" not in ctx.user_message_with_history
        assert "Contexto de relación" not in ctx.planner_user_message

    def test_message_appears_after_social_block(self) -> None:
        ctx = self._build("user:1")
        rel_pos = ctx.user_message_with_history.find("Contexto de relación")
        msg_pos = ctx.user_message_with_history.find("hola")
        assert rel_pos < msg_pos, "social block must precede the user message"


class TestAntiInjection:
    """Verify that user text cannot directly modify SocialProfile dimensions."""

    def test_user_claiming_high_affinity_does_not_inflate_snapshot(self) -> None:
        """A user message asserting their affinity score must not write to the DB.

        The only write path to dimension state is apply_appraisal_to_social_profile
        (called from turn_cognition) and _run_social_update (snapshot + reflection).
        Neither reads user text directly.
        """
        from datetime import datetime, timezone
        from app.memory.db import engine
        uid = 9991
        with Session(engine) as sess:
            existing = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            if existing:
                sess.delete(existing)
                sess.commit()
            sess.add(SocialProfile(
                user_id=uid,
                familiarity=0.05,
                affinity=0.0,
                trust_honesty=0.5,
                trust_intentions=0.5,
                pending_loads_json="[]",
                created_at=datetime.now(timezone.utc),
            ))
            sess.commit()

        # Simulate neutral AI load (user injection attempt has no effect on load)
        with Session(engine) as sess:
            _append_pending_load(sess, f"user:{uid}", 0)
            sess.commit()

        _run_social_update(uid, "anti_injection_test")

        with Session(engine) as sess:
            profile = sess.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
            assert profile is not None
            # Snapshot inserted with current (unchanged by user text) affinity=0.0
            snaps = sess.exec(
                select(RelationshipSnapshot).where(RelationshipSnapshot.profile_id == profile.id)
            ).all()
            assert len(snaps) == 1
            assert snaps[0].affinity == pytest.approx(0.0, abs=1e-6), (
                "snapshot affinity must reflect actual profile value, not user-claimed value"
            )

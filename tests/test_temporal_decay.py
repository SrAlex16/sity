"""Tests for temporal_decay.apply_mental_state_decay (MINI-REMAKE v2.0 Punto 4-A).

Properties:
1.  elapsed < 1 h → no-op (all fields unchanged).
2.  elapsed = 0 → no-op (same guard, edge case).
3.  After 12 h, arousal (λ=0.5) decays significantly toward baseline 0.
4.  After 12 h, valence (λ=0.005) barely moves from baseline 0 (slow lane).
5.  Field already at baseline → unchanged (|x - b| < 0.001 guard).
6.  Formula: x(t) = b + (x₀ − b) × e^{−λt} matches manual calculation.
7.  Mutates state in-place (same object, new attribute values).
8.  MentalState with naive datetime (no tzinfo) is handled safely.
9.  Large elapsed (5 days): every field converges close to its baseline.
10. Frustration at 0.85 after 24 h (λ=0.08): verify expected approx value.
11. social_comfort below baseline stays below baseline after decay (no overcorrection).
12. Decay never pushes any field past its baseline (no oscillation).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.cognition.temporal_decay import (
    _BASELINES,
    _LAMBDA,
    _MIN_ELAPSED_HOURS,
    apply_mental_state_decay,
)
from app.memory.models import MentalState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state(**overrides) -> MentalState:
    """Return a MentalState with updated_at = 48 h ago (so decay fires by default)."""
    now_utc = datetime.now(timezone.utc)
    defaults = dict(
        user_id=999000,
        valence=0.10,
        arousal=0.60,
        frustration=0.50,
        current_curiosity=0.70,
        interest=0.80,
        boredom=0.20,
        melancholy=0.25,
        defensiveness=0.40,
        social_comfort=0.70,
        updated_at=now_utc - timedelta(hours=48),
    )
    defaults.update(overrides)
    return MentalState(**defaults)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_with_elapsed(hours: float, **field_overrides) -> tuple[MentalState, datetime]:
    now = _now()
    state = _make_state(updated_at=now - timedelta(hours=hours), **field_overrides)
    return state, now


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestNoOpGuards:
    def test_elapsed_below_threshold_noop(self) -> None:
        state, now = _state_with_elapsed(0.5, arousal=0.90)
        apply_mental_state_decay(state, now=now)
        assert state.arousal == pytest.approx(0.90)

    def test_elapsed_zero_noop(self) -> None:
        state, now = _state_with_elapsed(0.0, arousal=0.90, frustration=0.80)
        apply_mental_state_decay(state, now=now)
        assert state.arousal == pytest.approx(0.90)
        assert state.frustration == pytest.approx(0.80)

    def test_exactly_at_threshold_fires(self) -> None:
        # _MIN_ELAPSED_HOURS = 1.0, so elapsed >= 1 should fire
        state, now = _state_with_elapsed(1.0, arousal=0.90)
        apply_mental_state_decay(state, now=now)
        # Should have moved slightly from 0.90 toward 0 (baseline)
        assert state.arousal < 0.90

    def test_field_at_baseline_skipped(self) -> None:
        baseline_arousal = _BASELINES["arousal"]   # 0.0
        state, now = _state_with_elapsed(24.0, arousal=baseline_arousal)
        before = state.arousal
        apply_mental_state_decay(state, now=now)
        assert state.arousal == pytest.approx(before)


class TestDecayFormula:
    def test_arousal_12h_decay(self) -> None:
        # λ=0.5, baseline=0, x₀=0.80, t=12h
        # x(12) = 0 + 0.80 × e^{-6} ≈ 0.80 × 0.00248 ≈ 0.00198
        state, now = _state_with_elapsed(12.0, arousal=0.80)
        apply_mental_state_decay(state, now=now)
        expected = 0.0 + (0.80 - 0.0) * math.exp(-0.5 * 12)
        assert state.arousal == pytest.approx(expected, abs=1e-4)

    def test_valence_12h_barely_moves(self) -> None:
        # λ=0.005, baseline=0, x₀=0.40, t=12h
        # x(12) = 0 + 0.40 × e^{-0.06} ≈ 0.40 × 0.9418 ≈ 0.3767
        state, now = _state_with_elapsed(12.0, valence=0.40)
        apply_mental_state_decay(state, now=now)
        expected = 0.0 + (0.40 - 0.0) * math.exp(-0.005 * 12)
        assert state.valence == pytest.approx(expected, abs=1e-4)
        # Valence should have moved only slightly
        assert abs(state.valence - 0.40) < 0.10

    def test_frustration_24h(self) -> None:
        # λ=0.08, baseline=0, x₀=0.85, t=24h
        # x(24) = 0 + 0.85 × e^{-1.92} ≈ 0.85 × 0.1466 ≈ 0.1246
        state, now = _state_with_elapsed(24.0, frustration=0.85)
        apply_mental_state_decay(state, now=now)
        expected = 0.0 + (0.85 - 0.0) * math.exp(-0.08 * 24)
        assert state.frustration == pytest.approx(expected, abs=1e-4)

    def test_melancholy_decays_toward_its_baseline(self) -> None:
        # baseline=0.10, x₀=0.70, λ=0.02, t=48h
        # x(48) = 0.10 + (0.70 - 0.10) × e^{-0.96}
        state, now = _state_with_elapsed(48.0, melancholy=0.70)
        apply_mental_state_decay(state, now=now)
        expected = 0.10 + (0.70 - 0.10) * math.exp(-0.02 * 48)
        assert state.melancholy == pytest.approx(expected, abs=1e-4)
        assert state.melancholy > 0.10  # still above baseline

    def test_social_comfort_below_baseline_decays_upward(self) -> None:
        # baseline=0.50, x₀=0.10 (below), λ=0.005, t=48h
        # x = 0.50 + (0.10 - 0.50) × e^{-0.24} ≈ 0.50 - 0.40×0.787 ≈ 0.185
        state, now = _state_with_elapsed(48.0, social_comfort=0.10)
        apply_mental_state_decay(state, now=now)
        assert state.social_comfort > 0.10   # moved toward baseline
        assert state.social_comfort < 0.50   # not yet at baseline


class TestDecayInvariants:
    def test_mutates_in_place(self) -> None:
        state, now = _state_with_elapsed(24.0, arousal=0.80)
        original_id = id(state)
        apply_mental_state_decay(state, now=now)
        assert id(state) == original_id
        assert state.arousal < 0.80  # was mutated

    def test_naive_datetime_handled_safely(self) -> None:
        now_naive = datetime.utcnow()
        state = _make_state(
            updated_at=now_naive - timedelta(hours=24),
            arousal=0.80,
        )
        apply_mental_state_decay(state, now=now_naive)  # both naive — should not raise
        assert state.arousal < 0.80

    def test_5_days_all_fields_near_baseline(self) -> None:
        state, now = _state_with_elapsed(5 * 24)
        apply_mental_state_decay(state, now=now)
        # arousal/defensiveness (λ=0.5): fully at baseline
        assert state.arousal == pytest.approx(0.0, abs=0.01)
        assert state.defensiveness == pytest.approx(0.0, abs=0.01)
        # frustration/boredom (λ=0.08): very near baseline
        assert state.frustration == pytest.approx(0.0, abs=0.05)
        assert state.boredom == pytest.approx(0.0, abs=0.05)

    def test_no_overshoot_below_baseline_for_above(self) -> None:
        # Arousal starts above baseline (0); should never go below 0
        state, now = _state_with_elapsed(100.0, arousal=0.90)
        apply_mental_state_decay(state, now=now)
        assert state.arousal >= 0.0

    def test_no_overshoot_above_baseline_for_below(self) -> None:
        # social_comfort below baseline (0.50); should never exceed 0.50
        state, now = _state_with_elapsed(100.0, social_comfort=0.10)
        apply_mental_state_decay(state, now=now)
        assert state.social_comfort <= 0.50 + 1e-6

    def test_interest_melancholy_curiosity_share_lambda(self) -> None:
        # All three have λ=0.02 — same rate, should decay by same factor
        t = 35.0
        lam = _LAMBDA["interest"]
        assert _LAMBDA["melancholy"] == lam
        assert _LAMBDA["current_curiosity"] == lam
        factor = math.exp(-lam * t)
        b_int = _BASELINES["interest"]      # 0.50
        b_mel = _BASELINES["melancholy"]    # 0.10
        b_cur = _BASELINES["current_curiosity"]  # 0.50
        state, now = _state_with_elapsed(t, interest=0.90, melancholy=0.80, current_curiosity=0.90)
        apply_mental_state_decay(state, now=now)
        assert state.interest == pytest.approx(b_int + (0.90 - b_int) * factor, abs=1e-4)
        assert state.melancholy == pytest.approx(b_mel + (0.80 - b_mel) * factor, abs=1e-4)
        assert state.current_curiosity == pytest.approx(b_cur + (0.90 - b_cur) * factor, abs=1e-4)

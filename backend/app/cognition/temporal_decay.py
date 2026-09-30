"""temporal_decay.py — Lazy MentalState decay toward baselines.

MINI-REMAKE v2.0 Punto 4-A.

Formula: x(t) = b + (x₀ − b) × e^{−λt}   (t in hours since last update)

Guards:
  - elapsed < 1 h  → no-op (too short to matter)
  - |x − b| < 0.001  → already at baseline, skip field
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.memory.models import MentalState

# ── Baselines ─────────────────────────────────────────────────────────────────
_BASELINES: dict[str, float] = {
    "valence":           0.0,
    "arousal":           0.0,
    "frustration":       0.0,
    "melancholy":        0.10,
    "current_curiosity": 0.50,
    "interest":          0.50,
    "boredom":           0.0,
    "defensiveness":     0.0,
    "social_comfort":    0.50,
}

# ── λ rates (half-life = ln2 / λ) ─────────────────────────────────────────────
# arousal/defensiveness: ~1.4 h  — acute spikes resolve fast
# frustration/boredom:   ~8.7 h  — overnight
# melancholy/interest/curiosity: ~34.7 h  — day-scale drift
# valence/social_comfort: ~138.6 h (~5.8 days)  — week-scale
_LAMBDA: dict[str, float] = {
    "arousal":           0.5,
    "defensiveness":     0.5,
    "frustration":       0.08,
    "boredom":           0.08,
    "melancholy":        0.02,
    "interest":          0.02,
    "current_curiosity": 0.02,
    "valence":           0.005,
    "social_comfort":    0.005,
}

_MIN_ELAPSED_HOURS: float = 1.0
_NEAR_BASELINE_EPS: float = 0.001


def apply_mental_state_decay(state: MentalState, now: datetime) -> None:
    """Decay all MentalState fields toward their baselines. Mutates state in-place.

    No-op when elapsed < 1 h or when the field is already at its baseline.
    Does NOT persist — caller must call save_mental_state() after appraisal.
    """
    updated = state.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    elapsed_hours = (now - updated).total_seconds() / 3600.0
    if elapsed_hours < _MIN_ELAPSED_HOURS:
        return

    for field_name, baseline in _BASELINES.items():
        lam = _LAMBDA.get(field_name, 0.02)
        x0 = getattr(state, field_name)
        if abs(x0 - baseline) < _NEAR_BASELINE_EPS:
            continue
        decayed = baseline + (x0 - baseline) * math.exp(-lam * elapsed_hours)
        setattr(state, field_name, round(decayed, 6))

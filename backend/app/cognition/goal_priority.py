"""Goal dynamic prioritization — Fase 2, Paso 2.

SECURITY EXCEPTION (confirmed by Alex, 2026-09-08):
  For Goal.is_wellbeing=True: the irony/humor tone reduction factor is NEVER applied.
  This is enforced as an EXPLICIT CODE RULE in _irony_factor() — NOT a prompt instruction.
  The early return `if is_wellbeing: return 1.0` in _irony_factor() completely bypasses
  irony computation before any other calculation runs. The LLM cannot override this.

Formula:
  effective_priority = BASE_WEIGHT * base_importance + BOOST_WEIGHT * relevance_boost_adj
  where: relevance_boost_adj = relevance_boost * irony_factor
  and:   irony_factor = 1.0  (always, unconditional) for is_wellbeing=True
                      = 1.0 - irony_score * IRONY_REDUCTION_STRENGTH  for others

Rationale for weighted combination (vs. max or multiplicative):
  - base_importance is fixed at creation and provides a stable floor: a high-importance
    goal stays relevant even when not contextually activated in a given turn.
  - relevance_boost is contextual (per-turn Appraisal output) and amplifies priority
    above the base, but can only reduce the boost component — never the base.
  - BOOST_WEIGHT=0.4 / BASE_WEIGHT=0.6: contextually sensitive without letting a single
    low-relevance turn collapse an important long-term goal.
  - Irony reduction operates only on the boost component (40%), not on base (60%).
    Even for non-wellbeing goals with extreme irony (irony_factor→0), the floor is
    BASE_WEIGHT * base_importance = 0.6 * base_importance.
  - For wellbeing goals: both floor and boost are fully preserved at all times.

Why not max(base_importance, relevance_boost)?
  max() loses the signal when relevance_boost < base_importance (treats it as zero),
  which means a highly-relevant but low-base-importance goal can't be properly amplified.
  The weighted formula preserves both signals.
"""
from __future__ import annotations

from app.settings.settings_service import clamp_01

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_WEIGHT: float = 0.6          # weight of base_importance in effective_priority
BOOST_WEIGHT: float = 0.4         # weight of relevance_boost in effective_priority

# Tones that indicate ironic/humorous content and their irony scores [0, 1]
_IRONY_SCORES: dict[str, float] = {
    "ironic":  0.90,   # strong irony — clear sarcasm signal
    "playful": 0.50,   # moderate — playfulness may or may not be ironic
    "joke":    0.85,   # guard against unexpected model output
}

# Maximum fraction by which irony reduces relevance_boost for non-wellbeing goals.
# With irony_score=1.0 and IRONY_REDUCTION_STRENGTH=0.8:
#   irony_factor = 1 - 1.0 * 0.8 = 0.2 (80% reduction)
# With irony_score=0.5: irony_factor = 0.6 (40% reduction)
IRONY_REDUCTION_STRENGTH: float = 0.80


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _irony_factor(tone: str, is_wellbeing: bool) -> float:
    """Return the relevance multiplier based on detected tone.

    SECURITY EXCEPTION — structural early return for wellbeing goals:
      When is_wellbeing=True, returns 1.0 unconditionally, before any irony
      computation is performed. This is a structural code rule, not a prompt
      instruction. The LLM cannot change this behavior.

      Rationale: ironic/playful tone may mask genuine distress. Reducing priority
      of a wellbeing goal because the user seems to be joking would be dangerous.
      The security exception ensures wellbeing goals always receive full relevance
      weight, regardless of detected tone. See Goal.is_wellbeing docstring.

    For non-wellbeing goals: detected irony reduces relevance_boost proportionally.
    Neutral/serious tones return 1.0 (no reduction).
    """
    # SECURITY EXCEPTION: explicit bypass — never irony-discount wellbeing goals
    if is_wellbeing:
        return 1.0

    irony_score = _IRONY_SCORES.get(tone.strip().lower(), 0.0)
    return 1.0 - irony_score * IRONY_REDUCTION_STRENGTH


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_effective_priority(
    base_importance: float,
    relevance_boost: float,
    tone: str,
    is_wellbeing: bool,
) -> float:
    """Compute the effective priority of a goal for this turn.

    Args:
        base_importance: fixed float [0, 1] set at goal creation.
        relevance_boost: contextual float [0, 1] from Appraisal for this turn.
        tone: detected tone from Perception (e.g. "ironic", "neutral", "serious").
        is_wellbeing: True iff goal relates to mental health/wellbeing.
            When True, irony-reduction is bypassed unconditionally (security exception).

    Returns:
        Effective priority in [0, 1].
    """
    irony_f = _irony_factor(tone, is_wellbeing)
    boost_adj = clamp_01(relevance_boost) * irony_f
    effective = BASE_WEIGHT * clamp_01(base_importance) + BOOST_WEIGHT * boost_adj
    return clamp_01(effective)

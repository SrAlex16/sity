"""social_service.py — per-turn SocialProfile operations (Remake Fase 3).

Public API:
  get_or_create_social_profile  — load or init a SocialProfile row for a user
  apply_appraisal_to_social_profile — update 11 dimensions from Appraisal + Perception signals
  trust_avg                     — helper: average of the four trust sub-dimensions

Principle (section 7 of architecture doc): personality traits MODULATE the magnitude
of updates, they are never copied into the relationship state.

Update signals:
  trust_evidence  [0, 0.05]  — Appraisal: evidence of trust in this interaction
  interest_delta  [-0.3,0.3] — Appraisal: engagement signal
  frustration_delta[-0.3,0.3]— Appraisal: friction signal
  social_signal   [0, 1]     — Perception: relational/bonding signal
  challenge       [0, 1]     — Perception: confrontation degree

Personality modulators:
  skepticism   — reduces trust nudge from trust_evidence
  warmth       — amplifies affinity growth from positive interest
  patience     — reduces conflict accumulation from frustration/challenge
  assertiveness — amplifies respect loss from high challenge
  empathy      — amplifies attachment growth from social_signal
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.memory.models import SocialProfile, utc_now


def get_or_create_social_profile(session: Session, user_id: int) -> SocialProfile:
    """Load the SocialProfile row for user_id, creating one with defaults if absent."""
    profile = session.exec(
        select(SocialProfile).where(SocialProfile.user_id == user_id)
    ).first()
    if profile is None:
        profile = SocialProfile(user_id=user_id, created_at=utc_now())
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def trust_avg(profile: SocialProfile) -> float:
    """Average of the four trust sub-dimensions."""
    return (
        profile.trust_honesty
        + profile.trust_intentions
        + profile.trust_competence
        + profile.trust_reliability
    ) / 4.0


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def apply_appraisal_to_social_profile(
    profile: SocialProfile,
    appraisal_trust_evidence: float,
    appraisal_interest_delta: float,
    appraisal_frustration_delta: float,
    perception_social_signal: float,
    perception_challenge: float,
    personality: dict,
) -> None:
    """Update the 11 SocialProfile dimensions in-place from Appraisal + Perception signals.

    Caller is responsible for session.add(profile) + session.commit() after this call.
    All values are clamped to [0, 1].
    """
    te  = appraisal_trust_evidence       # [0, 0.05]
    id_ = appraisal_interest_delta       # [-0.3, 0.3]
    fd  = appraisal_frustration_delta    # [-0.3, 0.3]
    ss  = perception_social_signal       # [0, 1]
    ch  = perception_challenge           # [0, 1]

    sk  = float(personality.get("skepticism",    0.5))
    wa  = float(personality.get("warmth",        0.5))
    pa  = float(personality.get("patience",      0.5))
    as_ = float(personality.get("assertiveness", 0.5))
    em  = float(personality.get("empathy",       0.5))

    trust_mod = 1.0 - sk * 0.4     # [0.6, 1.0] — skeptical Sity trusts less readily

    profile.familiarity     = _clamp(profile.familiarity     + 0.005 + ss * 0.003)
    profile.trust_honesty   = _clamp(profile.trust_honesty   + te * 0.5 * trust_mod)
    profile.trust_intentions = _clamp(profile.trust_intentions + te * 0.5 * trust_mod - ch * 0.015)
    # trust_competence and trust_reliability: near-stable in v1, no per-turn signal
    profile.affinity        = _clamp(profile.affinity        + max(0.0, id_) * 0.2 * (0.5 + wa * 0.5) - ch * 0.02)
    profile.comfort         = _clamp(profile.comfort         + te * 0.3 - ch * 0.04)
    profile.respect         = _clamp(profile.respect         + te * 0.2 - ch * 0.04 * (1.0 + as_ * 0.3))
    profile.attachment      = _clamp(profile.attachment      + ss * 0.008 * (0.5 + em * 0.5))
    profile.conflict        = _clamp(profile.conflict        + (max(0.0, fd) * 0.1 + ch * 0.04) * (1.0 - pa * 0.4))
    profile.uncertainty     = _clamp(profile.uncertainty     - te * 0.3 - ss * 0.01)

    profile.last_updated_at = utc_now()

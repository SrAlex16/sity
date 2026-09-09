"""Post-turn achievement checks for Sity.

Called once per successful authenticated turn from _run_turn_in_background.
All checks are cheap (SQL + in-memory math, no LLM calls) and never raise.
Each sub-check is isolated — one failure does not skip the rest.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.trace.logger import write_log


def check_post_turn_achievements(db: Any, user_id: int, session_id: str) -> None:
    try:
        from app.achievements.unlock import try_unlock_achievement
        from app.settings.config_loader import load_default_config
        cfg = load_default_config().get("achievements", {})
        _check_personality(db, user_id, cfg, try_unlock_achievement)
        _check_social(db, user_id, cfg, try_unlock_achievement)
        _check_account_age(db, user_id, cfg, try_unlock_achievement)
        _check_voice_count(db, user_id, cfg, try_unlock_achievement)
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _check_personality(db: Any, user_id: int, cfg: dict, unlock) -> None:
    try:
        from app.settings.settings_service import SettingsService, CANONICAL_PERSONALITY
        personality = SettingsService(db).get_personality(session_id=f"user:{user_id}")

        # who_am_i: normalized euclidean distance from canonical ≥ threshold
        keys = list(CANONICAL_PERSONALITY.keys())
        sq_sum = sum(
            (personality.get(k, CANONICAL_PERSONALITY[k]) - CANONICAL_PERSONALITY[k]) ** 2
            for k in keys
        )
        dist = math.sqrt(sq_sum) / math.sqrt(len(keys))
        if dist >= float(cfg.get("who_am_i_distance_threshold", 0.5)):
            unlock(db, user_id, "who_am_i")

        # chaos_head: confirmed formula (Remake Fase 1)
        chaos = (
            personality.get("playfulness", 0.0) * 0.35
            + (1.0 - personality.get("warmth", 1.0)) * 0.30
            + personality.get("assertiveness", 0.0) * 0.20
            + personality.get("independence", 0.0) * 0.15
        )
        if chaos >= float(cfg.get("chaos_head_threshold", 0.95)):
            unlock(db, user_id, "chaos_head")
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_personality_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _check_social(db: Any, user_id: int, cfg: dict, unlock) -> None:
    try:
        from sqlmodel import col, select
        from app.memory.models import RelationshipSnapshot, SocialProfile
        from app.social.social_service import trust_avg as _trust_avg

        profile = db.exec(
            select(SocialProfile).where(SocialProfile.user_id == user_id)
        ).first()
        if profile is None:
            return

        ta = _trust_avg(profile)

        # remember_me: trust_avg AND familiarity both above threshold
        if (ta >= float(cfg.get("remember_me_trust_avg_threshold", 0.65))
                and profile.familiarity >= float(cfg.get("remember_me_familiarity_threshold", 0.30))):
            unlock(db, user_id, "remember_me")

        liw_conflict = float(cfg.get("love_is_war_conflict_threshold", 0.50))
        liw_affinity = float(cfg.get("love_is_war_affinity_ceiling",   0.20))

        # love_is_war: significant conflict, almost no affinity
        if profile.conflict >= liw_conflict and profile.affinity < liw_affinity:
            unlock(db, user_id, "love_is_war")

        # its_over_9000: extreme version of love_is_war
        if (profile.conflict >= float(cfg.get("its_over_9000_conflict_threshold", 0.75))
                and profile.affinity < float(cfg.get("its_over_9000_affinity_ceiling", 0.10))):
            unlock(db, user_id, "its_over_9000")

        if profile.id is None:
            return

        snapshots = db.exec(
            select(RelationshipSnapshot)
            .where(RelationshipSnapshot.profile_id == profile.id)
            .order_by(col(RelationshipSnapshot.computed_at))
        ).all()

        if not snapshots:
            return

        # redemption: was in "war" state in history, currently recovered
        was_bad = any(
            s.conflict >= liw_conflict and s.affinity < liw_affinity
            for s in snapshots
        )
        currently_good = profile.affinity >= 0.35 and profile.conflict < 0.30
        if was_bad and currently_good:
            unlock(db, user_id, "redemption")

        # schizophrenia: ≥ min_flips state transitions (bad = conflict ≥ 0.35)
        _FLIP_THR = 0.35
        min_flips = int(cfg.get("schizophrenia_min_flips", 3))
        states = ["bad" if s.conflict >= _FLIP_THR else "good" for s in snapshots]
        transitions = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])
        if transitions >= min_flips:
            unlock(db, user_id, "schizophrenia")

    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_social_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def check_curiosity_achievement(db: Any, user_id: int, user_message: str) -> None:
    """Fire curiosity_killed_the_cat when user asks how to unlock an achievement.

    Keyword-detectable, no Haiku needed. Fires at most once (try_unlock is idempotent).
    """
    try:
        from app.achievements.unlock import try_unlock_achievement
        msg = user_message.lower()
        has_logro = "logro" in msg
        has_how = "cómo" in msg or "desbloquear" in msg or "conseguir" in msg
        if has_logro and has_how:
            try_unlock_achievement(db, user_id, "curiosity_killed_the_cat")
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_curiosity_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _check_voice_count(db: Any, user_id: int, cfg: dict, unlock) -> None:
    try:
        from sqlmodel import select, func
        from app.memory.models import ChatMessage

        session_id_prefix = f"user:{user_id}"
        threshold = int(cfg.get("hello_voice_threshold", 10))
        count = db.exec(
            select(func.count()).where(
                ChatMessage.session_id == session_id_prefix,
                ChatMessage.role == "user",
                ChatMessage.input_mode == "voice",
            )
        ).one()
        if count >= threshold:
            unlock(db, user_id, "hello_voice")
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_voice_count_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _check_account_age(db: Any, user_id: int, cfg: dict, unlock) -> None:
    try:
        from sqlmodel import select
        from app.memory.models import User

        user = db.exec(select(User).where(User.id == user_id)).first()
        if user is None:
            return

        min_days = int(cfg.get("account_age_days", 30))
        now = datetime.now(timezone.utc)
        created = user.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).days >= min_days:
            unlock(db, user_id, "a_long_time_ago")
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_account_age_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )

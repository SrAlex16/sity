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
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _check_personality(db: Any, user_id: int, cfg: dict, unlock) -> None:
    try:
        from app.settings.settings_service import SettingsService, CANONICAL_PERSONALITY
        personality = SettingsService(db).get_personality(session_id=None)

        # who_am_i: normalized euclidean distance from canonical ≥ threshold
        keys = list(CANONICAL_PERSONALITY.keys())
        sq_sum = sum(
            (personality.get(k, CANONICAL_PERSONALITY[k]) - CANONICAL_PERSONALITY[k]) ** 2
            for k in keys
        )
        dist = math.sqrt(sq_sum) / math.sqrt(len(keys))
        if dist >= float(cfg.get("who_am_i_distance_threshold", 0.5)):
            unlock(db, user_id, "who_am_i")

        # chaos_head: encabronamiento formula ≥ threshold
        chaos = (
            personality.get("rudeness_level", 0.0) * 0.4
            + personality.get("sarcasm_level", 0.0) * 0.3
            + personality.get("contrarian_level", 0.0) * 0.2
            + personality.get("dry_humor_level", 0.0) * 0.1
        )
        if chaos >= float(cfg.get("chaos_head_threshold", 0.95)):
            unlock(db, user_id, "chaos_head")

        # maximum_overdrive: any slider at 1.0
        if any(v >= 1.0 for v in personality.values()):
            unlock(db, user_id, "maximum_overdrive")

        # ice_queen: frialdad ≥ 0.9 AND warmth ≤ 0.1
        if (
            personality.get("frialdad_afectiva_level", 0.0) >= 0.9
            and personality.get("warmth_level", 1.0) <= 0.1
        ):
            unlock(db, user_id, "ice_queen")

        # saint: patience ≥ 0.9 AND rudeness ≤ 0.1
        if (
            personality.get("patience_level", 0.0) >= 0.9
            and personality.get("rudeness_level", 1.0) <= 0.1
        ):
            unlock(db, user_id, "saint")

        # chaos_agent: rudeness + sarcasm + contrarian all ≥ 0.8
        if (
            personality.get("rudeness_level", 0.0) >= 0.8
            and personality.get("sarcasm_level", 0.0) >= 0.8
            and personality.get("contrarian_level", 0.0) >= 0.8
        ):
            unlock(db, user_id, "chaos_agent")
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_personality_check_error",
            payload={"user_id": user_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _check_social(db: Any, user_id: int, cfg: dict, unlock) -> None:
    try:
        from sqlmodel import select
        from app.memory.models import SocialProfile, OpinionSnapshot

        profile = db.exec(select(SocialProfile).where(SocialProfile.user_id == user_id)).first()
        if profile is None:
            return

        if profile.trust >= float(cfg.get("remember_me_trust_threshold", 0.30)):
            unlock(db, user_id, "remember_me")

        neg_threshold = float(cfg.get("opinion_negative_threshold", -0.5))
        ext_threshold = float(cfg.get("opinion_extreme_threshold", -1.5))
        if profile.opinion <= neg_threshold:
            unlock(db, user_id, "love_is_war")
        if profile.opinion <= ext_threshold:
            unlock(db, user_id, "its_over_9000")

        snapshots = db.exec(
            select(OpinionSnapshot)
            .where(OpinionSnapshot.profile_id == profile.id)
            .order_by(OpinionSnapshot.computed_at.desc())
        ).all()
        if not snapshots:
            return

        # redemption: most recent snapshot negative + current opinion positive
        if snapshots[0].opinion_value < 0 and profile.opinion > 0:
            unlock(db, user_id, "redemption")

        # schizophrenia: ≥ N sign changes across full snapshot history
        min_flips = int(cfg.get("schizophrenia_min_flips", 3))
        opinions = [s.opinion_value for s in snapshots]
        flips = sum(
            1
            for i in range(len(opinions) - 1)
            if (opinions[i] >= 0) != (opinions[i + 1] >= 0)
        )
        if flips >= min_flips:
            unlock(db, user_id, "schizophrenia")
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="post_turn_social_check_error",
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

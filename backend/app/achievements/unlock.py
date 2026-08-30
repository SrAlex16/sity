"""Achievement unlock engine.

Public API:
  try_unlock_achievement(db, user_id, slug) -> bool
      Unlock an achievement for a user. Returns True only on a NEW unlock.
      Idempotent: safe to call multiple times with the same arguments.

  get_user_achievements(db, user_id) -> list[dict]
      Return the full catalog with unlock status for user_id.
      user_id=None (Guest) → all locked, secrets category omitted entirely.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.achievements.catalog import CATALOG, get_by_slug
from app.memory.models import UserAchievement
from app.trace.logger import write_log


def try_unlock_achievement(db: Session, user_id: int, slug: str) -> bool:
    """Unlock achievement `slug` for `user_id`. Returns True only if newly unlocked.

    Idempotent: a second call with the same (user_id, slug) returns False and
    writes no new row. Unknown slugs are logged as WARN and return False.

    On a NEW unlock, dispatches an achievement_unlocked notification (SSE + push
    if available). Dispatch errors are logged but never block the unlock.
    """
    achievement_def = get_by_slug(slug)
    if achievement_def is None:
        write_log(
            level="WARN", module="achievements", event="achievement_slug_unknown",
            payload={"slug": slug, "user_id": user_id},
        )
        return False

    existing = db.exec(
        select(UserAchievement).where(
            UserAchievement.user_id == user_id,
            UserAchievement.slug == slug,
        )
    ).first()

    if existing is not None:
        write_log(
            level="DEBUG", module="achievements", event="achievement_already_unlocked",
            payload={"slug": slug, "user_id": user_id},
        )
        return False

    db.add(UserAchievement(user_id=user_id, slug=slug))
    db.commit()

    write_log(
        level="INFO", module="achievements", event="achievement_unlocked",
        payload={"slug": slug, "user_id": user_id},
    )

    _dispatch_unlock_notification(db, user_id, slug, achievement_def.name)
    return True


def _dispatch_unlock_notification(db: Session, user_id: int, slug: str, name: str) -> None:
    """Fire-and-forget notification for a newly unlocked achievement.

    Reuses the existing notification infrastructure (SSE + push + pending).
    No rate limit applied — achievements are discrete, infrequent events and
    the (user_id, slug) pair is inherently unique (unlock is idempotent).
    Errors are logged and swallowed so the unlock itself is never blocked.
    """
    try:
        from app.notifications.fact import NotificationFact
        from app.notifications.dispatcher import dispatch
        fact = NotificationFact(
            session_id=f"user:{user_id}",
            notification_type="achievement_unlocked",
            fact_id=f"achievement:{slug}:{user_id}",
            payload={
                "title": "Sity",
                "body": f"Logro desbloqueado: {name}",
                "slug": slug,
                "achievement_name": name,
            },
            urgency="medium",
        )
        dispatch(fact, db)
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="achievement_notification_dispatch_error",
            payload={"slug": slug, "user_id": user_id, "error": str(exc)[:200]},
        )


def get_user_achievements(
    db: Session,
    user_id: Optional[int],
) -> list[dict]:
    """Return the catalog with per-user unlock state.

    Secrets visibility rules:
      - Guest (user_id=None): secrets category omitted entirely.
      - Authenticated user with no secret unlocked: secrets omitted.
      - Authenticated user with ≥1 secret unlocked: all secrets shown
        (locked or unlocked).
    """
    unlocked: dict[str, datetime] = {}
    if user_id is not None:
        rows = db.exec(
            select(UserAchievement).where(UserAchievement.user_id == user_id)
        ).all()
        unlocked = {r.slug: r.unlocked_at for r in rows}

    has_unlocked_secret = any(
        a.is_secret for a in CATALOG if a.slug in unlocked
    )
    show_secrets = user_id is not None and has_unlocked_secret

    result: list[dict] = []
    for a in CATALOG:
        if a.is_secret and not show_secrets:
            continue

        unlocked_at = unlocked.get(a.slug)
        is_unlocked = unlocked_at is not None
        result.append({
            "slug": a.slug,
            "category": a.category,
            "name": a.name,
            "description": a.description_full if is_unlocked else a.description_hint,
            "unlocked": is_unlocked,
            "unlocked_at": unlocked_at.isoformat() if unlocked_at else None,
        })

    return result

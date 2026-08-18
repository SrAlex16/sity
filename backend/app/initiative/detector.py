"""detector.py — read-only trigger detection for the initiative runner.

Each check function tests one trigger condition for a single User/Admin session.
Never writes to DB, never calls LLM. Respects the per-session sub-toggles.

Called by runner.py (Paso 3) to get the list of trigger candidates before
the IS_NOW_A_GOOD_TIME? gate and Haiku evaluation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, col, desc, select

from app.initiative.settings import get_initiative_settings
from app.memory.models import ChatMessage, OpenLoop
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log


def _cfg() -> dict:
    return load_default_config().get("initiative", {})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TriggerCandidate:
    trigger_type: str          # "conversation_abandoned" | "long_inactivity" | "open_loop"
    session_id: str
    context: dict = field(default_factory=dict)
    open_loop_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_trigger_candidates(
    session_id: str,
    db: Session,
) -> list[TriggerCandidate]:
    """Return all active trigger candidates for a session.

    Always returns an empty list for non-user sessions (guest:, etc.).
    Respects each individual sub-toggle in InitiativeSettings.
    """
    if not session_id.startswith("user:"):
        return []

    settings = get_initiative_settings(db, session_id=session_id)
    if not settings.enabled:
        return []

    candidates: list[TriggerCandidate] = []

    if settings.trigger_conversation_abandoned:
        c = _check_conversation_abandoned(session_id, db)
        if c:
            candidates.append(c)

    if settings.trigger_long_inactivity:
        c = _check_long_inactivity(session_id, db)
        if c:
            candidates.append(c)

    if settings.trigger_open_loop:
        c = _check_open_loop(session_id, db)
        if c:
            candidates.append(c)

    if candidates:
        write_log(
            level="INFO",
            module="initiative",
            event="trigger_candidates_found",
            session_id=session_id,
            payload={"triggers": [c.trigger_type for c in candidates]},
        )
    else:
        write_log(
            level="INFO",
            module="initiative",
            event="session_skipped_no_trigger",
            session_id=session_id,
        )

    return candidates


# ---------------------------------------------------------------------------
# Individual trigger checks
# ---------------------------------------------------------------------------

def _check_conversation_abandoned(
    session_id: str,
    db: Session,
) -> Optional[TriggerCandidate]:
    """Last message is from Sity and is between min_hours and max_days old."""
    cfg = _cfg()
    min_hours = int(cfg.get("conversation_abandoned_min_hours", 24))
    max_days = int(cfg.get("conversation_abandoned_max_days", 4))
    now = _utc_now()

    last_msg = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    ).first()

    if last_msg is None or last_msg.role != "sity":
        return None

    age = now - last_msg.created_at.replace(tzinfo=timezone.utc) if last_msg.created_at.tzinfo is None else now - last_msg.created_at
    hours_old = age.total_seconds() / 3600

    if hours_old < min_hours or hours_old > max_days * 24:
        return None

    # Fetch last 3 messages for evaluator context
    recent = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(3)
    ).all()

    context = {
        "hours_since_last_message": round(hours_old, 1),
        "last_messages": [
            {"role": m.role, "text": m.text[:300]}
            for m in reversed(recent)
        ],
    }

    write_log(
        level="INFO",
        module="initiative",
        event="trigger_conversation_abandoned_detected",
        session_id=session_id,
        payload={"hours_since_last": round(hours_old, 1)},
    )
    return TriggerCandidate(
        trigger_type="conversation_abandoned",
        session_id=session_id,
        context=context,
    )


def _check_long_inactivity(
    session_id: str,
    db: Session,
) -> Optional[TriggerCandidate]:
    """No messages from any role in the last long_inactivity_min_days days."""
    cfg = _cfg()
    min_days = int(cfg.get("long_inactivity_min_days", 5))
    now = _utc_now()

    last_msg = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    ).first()

    if last_msg is None:
        return None

    age = now - (last_msg.created_at.replace(tzinfo=timezone.utc) if last_msg.created_at.tzinfo is None else last_msg.created_at)
    days_old = age.total_seconds() / 86400

    if days_old < min_days:
        return None

    context = {
        "days_since_last_message": round(days_old, 1),
        "last_message_role": last_msg.role,
        "last_message_text": last_msg.text[:300],
    }

    write_log(
        level="INFO",
        module="initiative",
        event="trigger_long_inactivity_detected",
        session_id=session_id,
        payload={"days_since_last": round(days_old, 1)},
    )
    return TriggerCandidate(
        trigger_type="long_inactivity",
        session_id=session_id,
        context=context,
    )


def _check_open_loop(
    session_id: str,
    db: Session,
) -> Optional[TriggerCandidate]:
    """Oldest pending OpenLoop that has been waiting more than open_loop_min_days."""
    cfg = _cfg()
    min_days = int(cfg.get("open_loop_min_days", 3))
    now = _utc_now()
    cutoff = now - timedelta(days=min_days)

    loop = db.exec(
        select(OpenLoop)
        .where(
            OpenLoop.session_id == session_id,
            OpenLoop.status == "pending",
            OpenLoop.detected_at <= cutoff,
        )
        .order_by(OpenLoop.detected_at)   # oldest first → most overdue
        .limit(1)
    ).first()

    if loop is None:
        return None

    age_days = (now - (loop.detected_at.replace(tzinfo=timezone.utc) if loop.detected_at.tzinfo is None else loop.detected_at)).total_seconds() / 86400

    # Fetch messages sent AFTER detected_at — evaluator uses them to judge resolution
    after_msgs = db.exec(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.created_at > loop.detected_at,
        )
        .order_by(desc(ChatMessage.created_at))
        .limit(5)
    ).all()

    context = {
        "extracted_intent": loop.extracted_intent,
        "days_since_detected": round(age_days, 1),
        "original_user_message": loop.user_message[:300],
        "recent_messages_after_detection": [
            {"role": m.role, "text": m.text[:300]}
            for m in reversed(after_msgs)
        ],
    }

    write_log(
        level="INFO",
        module="initiative",
        event="trigger_open_loop_detected",
        session_id=session_id,
        payload={"loop_id": loop.id, "days_since_detected": round(age_days, 1)},
    )
    return TriggerCandidate(
        trigger_type="open_loop",
        session_id=session_id,
        context=context,
        open_loop_id=loop.id,
    )

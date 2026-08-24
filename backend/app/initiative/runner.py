"""runner.py — initiative job periódico (ciclo de 6h por defecto).

Corrutina asyncio iniciada en main.py on_startup, mismo patrón que
timers/runner.py (start_runner + loop.create_task) y notifications_gc_loop.

Cada ciclo:
  0. GC: marcar expired los OpenLoop caducados.
  1. Enumerar todos los User activos → session_ids "user:{id}".
  2. Para cada sesión: IS_NOW_A_GOOD_TIME? (initiative enabled, silencio,
     trust, rate limit diario) — verificaciones baratas sin Haiku.
  3. detector.get_trigger_candidates() → candidato priorizado
     (open_loop > conversation_abandoned > long_inactivity).
  4. evaluator.evaluate() → EvalResult (con su propio rate limit + Haiku).
  5. Si decision="send": persistir ChatMessage + dispatch NotificationFact.
     Si trigger_type="open_loop": marcar OpenLoop.status="dispatched".

Errores por sesión se registran como WARN y no interrumpen el ciclo.
Errores globales del ciclo se registran como ERROR.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, desc, select

from app.initiative.detector import TriggerCandidate, get_trigger_candidates
from app.initiative.evaluator import EvalResult, evaluate
from app.initiative.settings import get_initiative_settings
from app.memory.db import engine
from app.memory.models import ChatMessage, NotificationLog, OpenLoop, SocialProfile, User
from app.notifications.dispatcher import dispatch
from app.notifications.fact import NotificationFact
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log

# Priority order: lower value = higher priority.
_PRIORITY = {"open_loop": 0, "conversation_abandoned": 1, "long_inactivity": 2}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today_start() -> datetime:
    now = _utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


# ---------------------------------------------------------------------------
# GC — expire stale open loops
# ---------------------------------------------------------------------------

def _gc_expired_open_loops(db: Session) -> None:
    """Mark pending OpenLoops past their expires_at as expired."""
    now = _utc_now()
    loops = db.exec(
        select(OpenLoop).where(
            OpenLoop.status == "pending",
            OpenLoop.expires_at <= now,
        )
    ).all()
    if not loops:
        return
    for loop in loops:
        loop.status = "expired"
        db.add(loop)
    db.commit()
    write_log(
        level="INFO",
        module="initiative",
        event="open_loops_expired",
        payload={"count": len(loops)},
    )


# ---------------------------------------------------------------------------
# IS_NOW_A_GOOD_TIME? — cheap pre-filters before detector + evaluator
# ---------------------------------------------------------------------------

def _is_now_a_good_time(
    session_id: str,
    db: Session,
    silence_hours: int,
    min_trust: float,
    max_per_day: int,
) -> Optional[str]:
    """Returns skip reason string if this session should be skipped, else None.

    Checks in cheapness order: settings → silence → trust → rate limit.
    """
    settings = get_initiative_settings(db, session_id=session_id)
    if not settings.enabled:
        return "initiative_disabled"

    last_msg = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    ).first()
    if last_msg is not None:
        last_at = last_msg.created_at
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        age_hours = (_utc_now() - last_at).total_seconds() / 3600
        if age_hours < silence_hours:
            return "silence_recent"

    try:
        user_id = int(session_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return "invalid_session_id"

    social = db.exec(select(SocialProfile).where(SocialProfile.user_id == user_id)).first()
    if social is not None and social.trust < min_trust:
        return "trust_too_low"

    today_count = len(db.exec(
        select(NotificationLog).where(
            NotificationLog.session_id == session_id,
            NotificationLog.notification_type == "proactive_initiative",
            NotificationLog.created_at >= _utc_today_start(),
            NotificationLog.delivery_status != "failed",
        )
    ).all())
    if today_count >= max_per_day:
        return "rate_limited"

    return None


# ---------------------------------------------------------------------------
# Candidate prioritization
# ---------------------------------------------------------------------------

def _pick_candidate(candidates: list[TriggerCandidate]) -> TriggerCandidate:
    """Return highest-priority candidate (open_loop > conversation_abandoned > long_inactivity)."""
    return min(candidates, key=lambda c: _PRIORITY.get(c.trigger_type, 99))


# ---------------------------------------------------------------------------
# TTS synthesis for initiative messages
# ---------------------------------------------------------------------------

def _maybe_synthesize_tts(
    message: str,
    session_id: str,
    trace_id: str,
    db: Session,
) -> Optional[tuple[str, str]]:
    """Synthesize TTS for an initiative message using the user's voice preference.

    Returns (url, filename) if audio was generated and persisted, or None if
    the user has voice disabled or synthesis fails for any reason.
    Errors are logged as WARN and never propagate — TTS failure must not block dispatch.
    """
    try:
        from app.audio.tts_dispatcher import synthesize_fragment
        from app.settings.config_loader import load_default_config
        from app.settings.settings_service import SettingsService

        svc = SettingsService(db)
        voice_settings = svc.get_voice_settings(session_id=session_id)

        if voice_settings.voice_response_mode == "never":
            return None

        raw_cfg = load_default_config().get("audio", {})
        voice_id = str(raw_cfg.get("elevenlabs_voice_id", "EXAVITQu4vr4xnSDxMaL"))
        daily_limit = int(raw_cfg.get("elevenlabs_daily_char_limit", 0))

        tts_text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', message)
        tts_text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', tts_text)
        tts_text = re.sub(r'`([^`]+)`', r'\1', tts_text)
        tts_text = re.sub(r'^#{1,6}\s+', '', tts_text, flags=re.MULTILINE).strip()

        url, filename = synthesize_fragment(
            tts_text,
            session=db,
            session_id=session_id,
            tts_engine=voice_settings.tts_engine,
            persist=True,
            trace_id=trace_id,
            voice_id=voice_id,
            daily_limit=daily_limit,
        )
        return url, filename

    except Exception as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="initiative_tts_error",
            session_id=session_id,
            payload={"error": str(exc)[:200]},
        )
        return None


# ---------------------------------------------------------------------------
# Dispatch — persist ChatMessage + send notification + mark open_loop
# ---------------------------------------------------------------------------

def _dispatch_initiative(
    candidate: TriggerCandidate,
    result: EvalResult,
    db: Session,
) -> None:
    message = result.message or ""
    now = _utc_now()
    trace_id = f"init:{candidate.session_id}:{now.date().isoformat()}"

    chat_msg = ChatMessage(
        session_id=candidate.session_id,
        role="sity",
        text=message,
        trace_id=trace_id,
    )
    db.add(chat_msg)
    db.commit()
    db.refresh(chat_msg)

    tts_result = _maybe_synthesize_tts(message, candidate.session_id, trace_id, db)
    if tts_result is not None:
        _url, filename = tts_result
        chat_msg.audio_filename = filename
        chat_msg.tts_fragments = 1
        db.add(chat_msg)
        db.commit()

    fact = NotificationFact(
        session_id=candidate.session_id,
        notification_type="proactive_initiative",
        fact_id=f"initiative:{candidate.session_id}:{now.date().isoformat()}",
        payload={
            "title": "Sity",
            "body": message[:80],
            "full_text": message,
            "trigger_type": candidate.trigger_type,
        },
        urgency="low",
        subtype=candidate.trigger_type,
    )
    dispatch(fact, db)

    if candidate.trigger_type == "open_loop" and candidate.open_loop_id:
        loop = db.exec(select(OpenLoop).where(OpenLoop.id == candidate.open_loop_id)).first()
        if loop and loop.status == "pending":
            loop.status = "dispatched"
            db.add(loop)
            db.commit()

    write_log(
        level="INFO",
        module="initiative",
        event="initiative_dispatched",
        session_id=candidate.session_id,
        payload={
            "trigger_type": candidate.trigger_type,
            "open_loop_id": candidate.open_loop_id,
            "message_preview": message[:80],
        },
    )


# ---------------------------------------------------------------------------
# Main cycle — synchronous, runs in executor
# ---------------------------------------------------------------------------

def _run_cycle_sync() -> None:
    """One initiative cycle. Called from run_in_executor — no asyncio inside."""
    start = _now_ms()
    cfg = load_default_config()
    notif_cfg = cfg.get("notifications", {})

    silence_hours = int(notif_cfg.get("initiative_silence_hours", 4))
    min_trust = float(notif_cfg.get("initiative_min_trust", 0.30))
    max_per_day = int(notif_cfg.get("max_proactive_per_day_user", 1))

    try:
        with Session(engine) as db:
            _gc_expired_open_loops(db)

            users = db.exec(select(User).where(User.is_active == True)).all()  # noqa: E712
            session_ids = [f"user:{u.id}" for u in users]

            write_log(
                level="INFO",
                module="initiative",
                event="runner_cycle_start",
                payload={"eligible_sessions": len(session_ids)},
            )

            evaluated = sent = skipped = 0

            for sid in session_ids:
                try:
                    skip_reason = _is_now_a_good_time(sid, db, silence_hours, min_trust, max_per_day)
                    if skip_reason:
                        write_log(
                            level="INFO",
                            module="initiative",
                            event="session_skipped",
                            session_id=sid,
                            payload={"reason": skip_reason},
                        )
                        skipped += 1
                        continue

                    candidates = get_trigger_candidates(sid, db)
                    if not candidates:
                        write_log(
                            level="INFO",
                            module="initiative",
                            event="session_skipped",
                            session_id=sid,
                            payload={"reason": "no_trigger"},
                        )
                        skipped += 1
                        continue

                    candidate = _pick_candidate(candidates)
                    result = evaluate(candidate, db)
                    evaluated += 1

                    if result.decision == "send" and result.message:
                        _dispatch_initiative(candidate, result, db)
                        sent += 1
                    else:
                        write_log(
                            level="INFO",
                            module="initiative",
                            event="evaluation_complete",
                            session_id=sid,
                            payload={
                                "trigger": candidate.trigger_type,
                                "decision": "skip",
                                "reason": result.skip_reason,
                            },
                        )
                        skipped += 1

                except Exception as exc:
                    write_log(
                        level="WARN",
                        module="initiative",
                        event="session_evaluation_error",
                        session_id=sid,
                        payload={"error": str(exc)[:200]},
                    )
                    skipped += 1

            elapsed = _now_ms() - start
            write_log(
                level="INFO",
                module="initiative",
                event="runner_cycle_done",
                payload={
                    "elapsed_ms": elapsed,
                    "evaluated": evaluated,
                    "sent": sent,
                    "skipped": skipped,
                },
            )

    except Exception as exc:
        write_log(
            level="ERROR",
            module="initiative",
            event="runner_cycle_error",
            payload={"error": str(exc)[:300]},
        )


# ---------------------------------------------------------------------------
# Async loop + startup entry point
# ---------------------------------------------------------------------------

async def initiative_runner_loop(interval_seconds: float) -> None:
    """Async loop. Sleeps interval_seconds, then runs one cycle in executor."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(interval_seconds)
        await loop.run_in_executor(None, _run_cycle_sync)


def start_initiative_runner(loop: asyncio.AbstractEventLoop) -> None:
    """Called from main.py on_startup."""
    cfg = load_default_config()
    interval_hours = float(cfg.get("initiative", {}).get("job_interval_hours", 6))
    interval_seconds = interval_hours * 3600
    loop.create_task(initiative_runner_loop(interval_seconds))
    write_log(
        level="INFO",
        module="initiative",
        event="runner_started",
        payload={"interval_hours": interval_hours},
    )

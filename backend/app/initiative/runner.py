"""runner.py — adaptive initiative runner.

Architecture (post-redesign):
  A daemon thread wakes on either a threading.Event signal (set by turn_runner.py
  when urgent goals are detected post-turn) or a dynamic timeout chosen by Haiku.

  Each wake:
    1. GC: expire stale OpenLoops.
    2. For each active User session:
       a. Load enriched context (goals, MentalState, SocialProfile, local time,
          initiative history).
       b. Call Haiku (timing gate): → {should_initiate, next_check_seconds, reasoning}.
       c. If should_initiate: run existing initiative flow (detector → evaluator →
          dispatch). The IS_NOW_A_GOOD_TIME? cheap pre-filter still applies.
    3. Sleep for min(next_check_seconds across sessions), or signal — whichever
       comes first.

Public API:
  signal_if_urgent_goals(session_id, db)  — called post-turn, never raises
  start_initiative_runner(loop)           — called from main.py on_startup

Internal functions kept stable for existing tests (test_initiative_step4.py):
  _gc_expired_open_loops, _is_now_a_good_time, _pick_candidate,
  _dispatch_initiative, _run_cycle_sync (legacy direct-cycle used by tests)
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, desc, select

from app.audio.tts_service import maybe_attach_tts
from app.cognition.goal_priority import compute_effective_priority
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.initiative._json_utils import strip_json_fences
from app.initiative.detector import TriggerCandidate, get_trigger_candidates
from app.initiative.evaluator import EvalResult, evaluate
from app.initiative.settings import get_initiative_settings
from app.memory.db import engine
from app.memory.models import (
    ChatMessage, Goal, MentalState, NotificationLog, OpenLoop, SocialProfile, User,
)
from app.notifications.dispatcher import dispatch
from app.notifications.fact import NotificationFact
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log

# ---------------------------------------------------------------------------
# Module-level event and constants
# ---------------------------------------------------------------------------

_runner_wake_event = threading.Event()

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MIN_CHECK_SECONDS = 60
_MAX_CHECK_SECONDS = 86400
_FALLBACK_CHECK_SECONDS = 3600
_URGENT_GOAL_THRESHOLD = 0.85   # same as detector._GOAL_URGENT_PRIORITY_MIN
_GOAL_CONTEXT_THRESHOLD = 0.75  # slightly lower — gives Haiku more context


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today_start() -> datetime:
    now = _utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


# ---------------------------------------------------------------------------
# Public: signal from turn pipeline
# ---------------------------------------------------------------------------

def signal_if_urgent_goals(session_id: str, db: Session) -> None:
    """Set the runner wake event if the session has active goals with high priority.

    Called post-turn from turn_runner.py after each successful user turn.
    Never raises — any error is logged and swallowed.
    """
    if not session_id.startswith("user:"):
        return
    try:
        user_id = int(session_id.split(":", 1)[1])
        goals = db.exec(
            select(Goal).where(
                Goal.user_id == user_id,
                Goal.status == "active",
                Goal.scope == "long_term",
            )
        ).all()
        for g in goals:
            ep = compute_effective_priority(
                base_importance=g.base_importance,
                relevance_boost=1.0,
                tone="neutral",
                is_wellbeing=g.is_wellbeing,
            )
            if ep >= _URGENT_GOAL_THRESHOLD:
                _runner_wake_event.set()
                write_log(
                    level="INFO",
                    module="initiative",
                    event="runner_woken_by_urgent_goal",
                    session_id=session_id,
                    payload={"goal_id": g.id, "effective_priority": round(ep, 3)},
                )
                return
    except Exception as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="signal_if_urgent_goals_error",
            payload={"error": str(exc)[:200]},
        )


# ---------------------------------------------------------------------------
# GC — expire stale open loops
# ---------------------------------------------------------------------------

def _gc_expired_open_loops(db: Session) -> None:
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
# IS_NOW_A_GOOD_TIME? — cheap pre-filters (rate limit, silence, trust)
# ---------------------------------------------------------------------------

def _is_now_a_good_time(
    session_id: str,
    db: Session,
    silence_hours: int,
    min_familiarity: float,
    max_per_day: int,
) -> Optional[str]:
    """Returns skip reason string if this session should be skipped, else None."""
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
    if social is not None and social.familiarity < min_familiarity:
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

_PRIORITY = {"open_loop": 0, "goal_urgent": 1, "conversation_abandoned": 2, "long_inactivity": 3}


def _pick_candidate(candidates: list[TriggerCandidate]) -> TriggerCandidate:
    return min(candidates, key=lambda c: _PRIORITY.get(c.trigger_type, 99))


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

    from app.settings.settings_service import SettingsService
    _lang_override = SettingsService(db).get_language_override(
        session_id=candidate.session_id
    )
    tts_result = maybe_attach_tts(
        text=message,
        session=db,
        session_id=candidate.session_id,
        trace_id=trace_id,
        force_persist=True,
        language_override=_lang_override,
    )
    if tts_result is not None:
        n_fragments, audio_filename = tts_result
        chat_msg.audio_filename = audio_filename
        chat_msg.tts_fragments = n_fragments
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

    from app.achievements.triggers.inline import fire as _fire_ach
    _fire_ach(db, candidate.session_id, "voices")

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
# Legacy cycle — kept intact for test_initiative_step4.py
# ---------------------------------------------------------------------------

def _run_cycle_sync() -> None:
    """One initiative cycle (fixed-interval legacy path). Kept for tests.

    Called directly by test_initiative_step4.py. In production the runner
    uses _run_adaptive_cycle_sync, which adds a Haiku timing gate on top.
    """
    start = _now_ms()
    cfg = load_default_config()
    notif_cfg = cfg.get("notifications", {})

    silence_hours = int(notif_cfg.get("initiative_silence_hours", 4))
    min_familiarity = float(notif_cfg.get("initiative_min_familiarity", 0.05))
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
                    skip_reason = _is_now_a_good_time(sid, db, silence_hours, min_familiarity, max_per_day)
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
# Timing Haiku — context builder + caller
# ---------------------------------------------------------------------------

_TIMING_SYSTEM = (
    "Eres el módulo de timing de Sity. Decides si Sity debe iniciar una conversación ahora\n"
    "y cuándo debe revisar de nuevo.\n\n"
    "PRINCIPIOS:\n"
    "- Durante la madrugada (franja 'madrugada'), evita iniciar contacto salvo que haya\n"
    "  una meta de bienestar muy urgente — el descanso del usuario tiene prioridad.\n"
    "  No es una regla absoluta: usa tu criterio.\n"
    "- Si Sity ya escribió sin respuesta en las últimas horas: incrementa next_check\n"
    "  significativamente. No insistas dos veces sin respuesta.\n"
    "- Melancolía alta (≥0.6) o aburrimiento alto (≥0.7) suprimen la iniciativa aunque\n"
    "  haya meta urgente.\n"
    "- Sin metas urgentes y sin conversación reciente: next_check alto (≥7200) es la\n"
    "  opción conservadora correcta.\n"
    "- El rango válido de next_check_seconds es [60, 86400].\n\n"
    'Responde ÚNICAMENTE con JSON válido, sin markdown:\n'
    '{"should_initiate": true|false, "next_check_seconds": <int>, "reasoning": "<1-2 frases en castellano>"}\n'
    "reasoning: para logs internos, no llega al usuario."
)


def _get_local_time_info() -> tuple[int, str, str]:
    """(local_hour, franja, display_str). Server local time == user local time (same Pi)."""
    now_local = datetime.now()
    h = now_local.hour
    if h < 7:
        franja = "madrugada"
    elif h < 12:
        franja = "mañana"
    elif h < 18:
        franja = "tarde"
    else:
        franja = "noche"
    day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    day = day_names[now_local.weekday()]
    display = f"{now_local.strftime('%H:%M')} ({day})"
    return h, franja, display


def _count_unanswered_initiatives(session_id: str, db: Session) -> int:
    """Count Sity initiatives in last 24h that received no subsequent user reply."""
    cutoff = _utc_now() - timedelta(hours=24)
    initiatives = db.exec(
        select(NotificationLog)
        .where(
            NotificationLog.session_id == session_id,
            NotificationLog.notification_type == "proactive_initiative",
            NotificationLog.created_at >= cutoff,
            NotificationLog.delivery_status != "failed",
        )
        .order_by(NotificationLog.created_at)
    ).all()

    if not initiatives:
        return 0

    last_user_msg = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    ).first()

    if last_user_msg is None:
        return len(initiatives)

    last_user_at = last_user_msg.created_at
    if last_user_at.tzinfo is None:
        last_user_at = last_user_at.replace(tzinfo=timezone.utc)

    return sum(
        1 for init in initiatives
        if (
            init.created_at.replace(tzinfo=timezone.utc)
            if init.created_at.tzinfo is None
            else init.created_at
        ) > last_user_at
    )


def _build_timing_message(session_id: str, db: Session, woken_by_signal: bool) -> str:
    """Build the Haiku user-message for the timing decision."""
    _, franja, local_time_str = _get_local_time_info()

    # Days since last real user message
    last_user_msg = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "user")
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    ).first()
    if last_user_msg:
        last_at = last_user_msg.created_at
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        days_inactive = round((_utc_now() - last_at).total_seconds() / 86400, 1)
    else:
        days_inactive = 0.0

    unanswered = _count_unanswered_initiatives(session_id, db)

    # MentalState
    try:
        user_id = int(session_id.split(":", 1)[1])
        ms = db.exec(select(MentalState).where(MentalState.user_id == user_id)).first()
    except Exception:
        ms = None
        user_id = 0

    interest      = round(ms.interest,      2) if ms else 0.75
    melancholy    = round(ms.melancholy,    2) if ms else 0.10
    boredom       = round(ms.boredom,       2) if ms else 0.05
    frustration   = round(ms.frustration,   2) if ms else 0.20
    social_comfort = round(ms.social_comfort, 2) if ms else 0.60

    # SocialProfile
    try:
        uid = user_id or int(session_id.split(":", 1)[1])
        social = db.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
    except Exception:
        social = None

    if social:
        ta = round(
            (social.trust_honesty + social.trust_intentions
             + social.trust_competence + social.trust_reliability) / 4.0, 2
        )
        familiarity = round(social.familiarity, 2)
        affinity    = round(social.affinity,    2)
    else:
        ta = 0.50
        familiarity = 0.0
        affinity    = 0.0

    # Active goals with effective_priority >= context threshold
    goals_lines: list[str] = []
    try:
        uid2 = user_id or int(session_id.split(":", 1)[1])
        goals = db.exec(
            select(Goal).where(
                Goal.user_id == uid2,
                Goal.status == "active",
                Goal.scope == "long_term",
            )
        ).all()
        for g in goals:
            ep = compute_effective_priority(
                base_importance=g.base_importance,
                relevance_boost=1.0,
                tone="neutral",
                is_wellbeing=g.is_wellbeing,
            )
            if ep >= _GOAL_CONTEXT_THRESHOLD:
                wb = ", bienestar" if g.is_wellbeing else ""
                goals_lines.append(f'- "{g.description}" (priority={ep:.2f}{wb})')
    except Exception:
        pass

    goals_block = "\n".join(goals_lines) if goals_lines else "Ninguna"
    trigger_reason = "signal_urgente" if woken_by_signal else "timeout_programado"

    return (
        f"Hora local: {local_time_str}\n"
        f"Franja horaria: {franja}\n"
        f"Días sin conversación real del usuario: {days_inactive}\n"
        f"Iniciativas de Sity sin respuesta (últimas 24h): {unanswered}\n"
        f"Motivo del ciclo: {trigger_reason}\n\n"
        f"Estado emocional actual:\n"
        f"  interés={interest}  melancolía={melancholy}  aburrimiento={boredom}\n"
        f"  frustración={frustration}  confort_social={social_comfort}\n\n"
        f"Relación con el usuario:\n"
        f"  familiaridad={familiarity}  confianza={ta}  afinidad={affinity}\n\n"
        f"Metas activas con priority ≥ {_GOAL_CONTEXT_THRESHOLD}:\n"
        f"{goals_block}"
    )


def _call_timing_haiku(user_msg: str) -> tuple[bool, int, str]:
    """Call Haiku for the timing decision.

    Returns (should_initiate, next_check_seconds, reasoning).
    On any failure: conservative fallback (False, _FALLBACK_CHECK_SECONDS, "haiku_error").
    next_check_seconds is NOT clamped here — caller applies _MIN/_MAX_CHECK_SECONDS.
    """
    try:
        provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id="",
            task_type="initiative_timing",
            system_prompt=_TIMING_SYSTEM,
            user_message=user_msg,
            max_tokens=120,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if not response.ok or not response.text:
            return False, _FALLBACK_CHECK_SECONDS, "haiku_empty_response"

        parsed = json.loads(strip_json_fences(response.text))
        should_initiate = bool(parsed.get("should_initiate", False))
        raw_next = int(parsed.get("next_check_seconds", _FALLBACK_CHECK_SECONDS))
        reasoning = str(parsed.get("reasoning", ""))[:200]
        return should_initiate, raw_next, reasoning

    except Exception as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="timing_haiku_error",
            payload={"error": str(exc)[:200]},
        )
        return False, _FALLBACK_CHECK_SECONDS, "haiku_error"


# ---------------------------------------------------------------------------
# Adaptive cycle — one iteration of the new runner
# ---------------------------------------------------------------------------

def _run_adaptive_cycle_sync(woken_by_signal: bool) -> int:
    """One adaptive cycle. Returns next_check_seconds for the runner to sleep.

    For each active user:
      1. Build enriched context.
      2. Call timing Haiku → should_initiate + next_check_seconds.
      3. If should_initiate: run existing initiative flow (IS_NOW_A_GOOD_TIME? +
         detector + evaluator + dispatch).
    Returns min(next_check_seconds across sessions), or _FALLBACK_CHECK_SECONDS
    if no sessions or a global error occurs.
    """
    start = _now_ms()
    cfg = load_default_config()
    notif_cfg = cfg.get("notifications", {})
    silence_hours   = int(notif_cfg.get("initiative_silence_hours", 4))
    min_familiarity = float(notif_cfg.get("initiative_min_familiarity", 0.05))
    max_per_day     = int(notif_cfg.get("max_proactive_per_day_user", 1))

    min_next_check = _MAX_CHECK_SECONDS

    try:
        with Session(engine) as db:
            _gc_expired_open_loops(db)

            users = db.exec(select(User).where(User.is_active == True)).all()  # noqa: E712
            session_ids = [f"user:{u.id}" for u in users]

            write_log(
                level="INFO",
                module="initiative",
                event="adaptive_cycle_start",
                payload={
                    "eligible_sessions": len(session_ids),
                    "woken_by": "signal" if woken_by_signal else "timeout",
                },
            )

            if not session_ids:
                return _FALLBACK_CHECK_SECONDS

            evaluated = sent = skipped = 0

            for sid in session_ids:
                try:
                    timing_msg = _build_timing_message(sid, db, woken_by_signal)
                    should_initiate, raw_next, reasoning = _call_timing_haiku(timing_msg)
                    next_check = max(_MIN_CHECK_SECONDS, min(_MAX_CHECK_SECONDS, raw_next))
                    min_next_check = min(min_next_check, next_check)

                    write_log(
                        level="INFO",
                        module="initiative",
                        event="timing_decision",
                        session_id=sid,
                        payload={
                            "should_initiate": should_initiate,
                            "next_check_seconds": next_check,
                            "woken_by": "signal" if woken_by_signal else "timeout",
                            "reasoning": reasoning[:120],
                        },
                    )

                    if not should_initiate:
                        skipped += 1
                        continue

                    # Haiku approves — run existing initiative flow
                    skip_reason = _is_now_a_good_time(
                        sid, db, silence_hours, min_familiarity, max_per_day
                    )
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
                    min_next_check = min(min_next_check, _FALLBACK_CHECK_SECONDS)

            elapsed = _now_ms() - start
            write_log(
                level="INFO",
                module="initiative",
                event="adaptive_cycle_done",
                payload={
                    "elapsed_ms": elapsed,
                    "evaluated": evaluated,
                    "sent": sent,
                    "skipped": skipped,
                    "next_check_seconds": min_next_check,
                    "woken_by": "signal" if woken_by_signal else "timeout",
                },
            )

    except Exception as exc:
        write_log(
            level="ERROR",
            module="initiative",
            event="adaptive_cycle_error",
            payload={"error": str(exc)[:300]},
        )
        return _FALLBACK_CHECK_SECONDS

    return min_next_check if min_next_check < _MAX_CHECK_SECONDS else _FALLBACK_CHECK_SECONDS


# ---------------------------------------------------------------------------
# Runner loop — daemon thread
# ---------------------------------------------------------------------------

def _runner_loop_sync(initial_delay: float) -> None:
    """Full runner loop. Runs in a daemon thread. Never returns."""
    next_check = initial_delay
    while True:
        _runner_wake_event.clear()
        woken_by_signal = _runner_wake_event.wait(timeout=next_check)
        _runner_wake_event.clear()
        next_check = float(_run_adaptive_cycle_sync(woken_by_signal=woken_by_signal))


def start_initiative_runner(loop: asyncio.AbstractEventLoop) -> None:  # loop kept for API compat
    """Called from main.py on_startup. Starts the adaptive runner as a daemon thread."""
    cfg = load_default_config()
    initial_delay = float(
        cfg.get("initiative", {}).get("initial_delay_seconds", float(_FALLBACK_CHECK_SECONDS))
    )

    thread = threading.Thread(target=_runner_loop_sync, args=(initial_delay,), daemon=True)
    thread.name = "initiative-runner"
    thread.start()

    write_log(
        level="INFO",
        module="initiative",
        event="runner_started",
        payload={"initial_delay_seconds": initial_delay, "mode": "adaptive"},
    )

"""evaluator.py — SHOULD_I_TALK? decision gate for the initiative runner.

evaluate(candidate, db) → EvalResult

Flow:
  1. Rate limit check (daily max + cooldown) — cheap DB query, no Haiku cost.
  2. SocialProfile fetch for context injection.
  3. Build trigger-specific Haiku prompt and call Haiku.
  4. Parse JSON response; for open_loop trigger, handle resolution signal.
  5. Persist InitiativeEvalLog (always — both send and skip).
  6. Return EvalResult.

Never raises — all errors log as WARN and return skip/evaluator_error.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.initiative._json_utils import strip_json_fences
from app.initiative.detector import TriggerCandidate
from app.memory.models import InitiativeEvalLog, NotificationLog, OpenLoop, SocialProfile
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today_start() -> datetime:
    now = _utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    decision: str                      # "send" | "skip"
    message: Optional[str] = None      # None if decision="skip"
    reasoning: str = ""                # for InitiativeEvalLog.haiku_reasoning
    skip_reason: Optional[str] = None  # rate_limited | cooldown_active | model_skip | open_loop_resolved | evaluator_error
    haiku_verdict: Optional[str] = None  # "send" | "skip" | None (Haiku not called)


def evaluate(candidate: TriggerCandidate, db: Session) -> EvalResult:
    """Evaluate one TriggerCandidate. Never raises."""
    notif_cfg = load_default_config().get("notifications", {})

    # Rate limits first — avoids Haiku cost when already over budget.
    rate_reason = _check_rate_limits(candidate.session_id, db, notif_cfg)
    if rate_reason:
        result = EvalResult(decision="skip", skip_reason=rate_reason)
        _persist_eval_log(candidate, result, db)
        return result

    social = _get_social_profile(candidate.session_id, db)

    write_log(
        level="INFO",
        module="initiative",
        event="evaluation_start",
        session_id=candidate.session_id,
        payload={"trigger_type": candidate.trigger_type},
    )
    try:
        haiku_result = _call_haiku(candidate, social)
    except Exception as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="evaluation_haiku_error",
            session_id=candidate.session_id,
            payload={"error": str(exc)[:200], "trigger_type": candidate.trigger_type},
        )
        result = EvalResult(decision="skip", skip_reason="evaluator_error")
        _persist_eval_log(candidate, result, db)
        return result

    haiku_decision = haiku_result.get("decision", "skip")
    haiku_message = (haiku_result.get("message") or "")[:2000] if haiku_decision == "send" else None
    haiku_reasoning = (haiku_result.get("reasoning") or "")[:300]

    # For open_loop: if Haiku signals the intention was already resolved, mark it.
    if (
        candidate.trigger_type == "open_loop"
        and candidate.open_loop_id
        and haiku_result.get("open_loop_resolved") is True
    ):
        _mark_open_loop_resolved(candidate.open_loop_id, db)
        result = EvalResult(
            decision="skip",
            skip_reason="open_loop_resolved",
            haiku_verdict=haiku_decision,
            reasoning=haiku_reasoning,
        )
        _persist_eval_log(candidate, result, db)
        return result

    if haiku_decision == "send":
        result = EvalResult(
            decision="send",
            message=haiku_message,
            haiku_verdict="send",
            reasoning=haiku_reasoning,
        )
    else:
        result = EvalResult(
            decision="skip",
            skip_reason="model_skip",
            haiku_verdict=haiku_decision,
            reasoning=haiku_reasoning,
        )

    write_log(
        level="INFO",
        module="initiative",
        event="evaluation_complete",
        session_id=candidate.session_id,
        payload={
            "decision": result.decision,
            "trigger_type": candidate.trigger_type,
            "skip_reason": result.skip_reason,
            "reasoning_preview": haiku_reasoning[:80],
        },
    )
    _persist_eval_log(candidate, result, db)
    return result


# ---------------------------------------------------------------------------
# Rate limit checks
# ---------------------------------------------------------------------------

def _check_rate_limits(session_id: str, db: Session, cfg: dict) -> Optional[str]:
    """Returns skip_reason if rate-limited, else None."""
    max_per_day = int(cfg.get("max_proactive_per_day_user", 1))
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

    cooldown_hours = int(cfg.get("initiative_cooldown_hours", 24))
    cutoff = _utc_now() - timedelta(hours=cooldown_hours)
    recent = db.exec(
        select(NotificationLog).where(
            NotificationLog.session_id == session_id,
            NotificationLog.notification_type == "proactive_initiative",
            NotificationLog.created_at >= cutoff,
            NotificationLog.delivery_status != "failed",
        )
    ).first()
    if recent:
        return "cooldown_active"

    return None


# ---------------------------------------------------------------------------
# SocialProfile helper
# ---------------------------------------------------------------------------

def _get_social_profile(session_id: str, db: Session) -> Optional[SocialProfile]:
    try:
        user_id = int(session_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    return db.exec(select(SocialProfile).where(SocialProfile.user_id == user_id)).first()


# ---------------------------------------------------------------------------
# Haiku prompt construction and call
# ---------------------------------------------------------------------------

_SYSTEM_STANDARD = """\
Eres Sity. Decides si iniciar una conversación con el usuario.

REGLAS:
- Solo escribe si tienes algo genuino que aportar.
- Si el tema ya fue resuelto en la conversación, responde skip.
- Si la inactividad no tiene contexto aprovechable, responde skip.
- Si decides escribir, el mensaje debe ser corto (1–3 frases), natural, en el tono habitual.
- No menciones que "detectaste" nada ni que lleves días sin hablar de forma explícita.

Responde ÚNICAMENTE en JSON:
{"decision": "send" | "skip", "message": "...", "reasoning": "..."}"""

_SYSTEM_OPEN_LOOP = """\
Eres Sity. Decides si iniciar una conversación con el usuario sobre una intención que mencionó.

REGLAS:
- Revisa los mensajes posteriores a la detección: si la intención ya fue resuelta o mencionada, \
marca open_loop_resolved: true y responde skip.
- Si la intención sigue pendiente y es un buen momento para preguntar, responde send con un mensaje corto.
- El mensaje debe ser natural, 1–3 frases, en el tono habitual. No menciones que "detectaste" nada.

Responde ÚNICAMENTE en JSON:
{"decision": "send" | "skip", "open_loop_resolved": true | false, "message": "...", "reasoning": "..."}"""


def _build_user_message(candidate: TriggerCandidate, social: Optional[SocialProfile]) -> str:
    opinion_str = f"{social.opinion:.2f}" if social else "0.00"
    trust_str = f"{social.trust:.2f}" if social else "0.00"
    lines: list[str] = [
        f"Trigger: {candidate.trigger_type}",
        f"Perfil social: opinion={opinion_str}, trust={trust_str}",
        "",
    ]

    ctx = candidate.context
    if candidate.trigger_type == "conversation_abandoned":
        lines.append(f"Horas desde el último mensaje: {ctx.get('hours_since_last_message', '?')}")
        for m in ctx.get("last_messages", []):
            lines.append(f"  {m.get('role', '?')}: {m.get('text', '')}")

    elif candidate.trigger_type == "long_inactivity":
        lines.append(f"Días sin actividad: {ctx.get('days_since_last_message', '?')}")
        lines.append(
            f"Último mensaje ({ctx.get('last_message_role', '?')}): {ctx.get('last_message_text', '')}"
        )

    elif candidate.trigger_type == "open_loop":
        lines.append(f"Intención detectada hace {ctx.get('days_since_detected', '?')} días: {ctx.get('extracted_intent', '')}")
        lines.append(f"Mensaje original: {ctx.get('original_user_message', '')}")
        after_msgs = ctx.get("recent_messages_after_detection", [])
        if after_msgs:
            lines.append("Mensajes posteriores a la detección:")
            for m in after_msgs:
                lines.append(f"  {m.get('role', '?')}: {m.get('text', '')}")
        else:
            lines.append("No ha habido mensajes desde la detección.")

    return "\n".join(lines)


def _call_haiku(candidate: TriggerCandidate, social: Optional[SocialProfile]) -> dict:
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)

    system = _SYSTEM_OPEN_LOOP if candidate.trigger_type == "open_loop" else _SYSTEM_STANDARD
    request = AIRequest(
        trace_id="",
        task_type="initiative_evaluation",
        system_prompt=system,
        user_message=_build_user_message(candidate, social),
        max_tokens=200,
        tools_enabled=False,
    )
    response = provider.generate(request)
    if not response.ok or not response.text:
        write_log(
            level="WARN",
            module="initiative",
            event="evaluation_haiku_error",
            payload={"reason": "empty_or_failed_response", "trigger_type": candidate.trigger_type},
        )
        return {"decision": "skip", "reasoning": "provider_error"}

    try:
        parsed = json.loads(strip_json_fences(response.text))
        if not isinstance(parsed.get("decision"), str):
            raise ValueError("missing or invalid 'decision' key")
        return parsed
    except (json.JSONDecodeError, ValueError) as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="evaluation_haiku_error",
            payload={"reason": "json_parse_error", "error": str(exc)[:100], "raw": response.text[:200]},
        )
        return {"decision": "skip", "reasoning": "json_parse_error"}


# ---------------------------------------------------------------------------
# OpenLoop resolution
# ---------------------------------------------------------------------------

def _mark_open_loop_resolved(loop_id: str, db: Session) -> None:
    loop = db.exec(select(OpenLoop).where(OpenLoop.id == loop_id)).first()
    if loop:
        loop.status = "resolved"
        loop.resolved_at = _utc_now()
        db.add(loop)
        db.commit()
        write_log(
            level="INFO",
            module="initiative",
            event="open_loop_resolved",
            payload={"loop_id": loop_id},
        )


# ---------------------------------------------------------------------------
# InitiativeEvalLog persistence
# ---------------------------------------------------------------------------

def _persist_eval_log(candidate: TriggerCandidate, result: EvalResult, db: Session) -> None:
    log = InitiativeEvalLog(
        session_id=candidate.session_id,
        trigger_type=candidate.trigger_type,
        decision=result.decision,
        skip_reason=result.skip_reason,
        haiku_verdict=result.haiku_verdict,
        haiku_reasoning=result.reasoning[:300] if result.reasoning else None,
        message_preview=result.message[:200] if result.message else None,
        trigger_context_json=json.dumps(candidate.context, ensure_ascii=False, default=str),
        open_loop_id=candidate.open_loop_id,
    )
    db.add(log)
    db.commit()

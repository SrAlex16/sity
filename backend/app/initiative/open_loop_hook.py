"""open_loop_hook.py — fire-and-forget detection of future intentions in user messages.

Called from ai_turn_prep.py after the user message is saved, for User sessions only.
Launches a daemon thread (same pattern as social/update.py) that calls Haiku to
classify the user's message. If a future intention is detected, creates an OpenLoop
record in DB.

Never blocks the main chat turn. All errors are logged as WARN and swallowed — this
is a best-effort enrichment task, not a critical path.

Deduplication policy: one pending OpenLoop per session per 24h window (no content
comparison). Rationale: the evaluator handles multiple related intentions from the
context of the single open loop; creating multiple records per session in a short
window adds noise without value.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from secrets import token_hex

from sqlmodel import Session, select

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.db import engine
from app.memory.models import OpenLoop
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_DEDUP_WINDOW_HOURS = 24

_DETECTION_SYSTEM = """\
Clasifica el siguiente mensaje de usuario.

¿Contiene una intención o tarea futura concreta que el propio usuario \
podría querer que le recuerden más adelante? Cuenta como intención real: \
compromisos propios ("voy a buscar trabajo", "tengo que llamar al médico"), \
tareas pospuestas ("lo miro esta semana", "lo dejo para el finde"), \
decisiones pendientes ("voy a pensar en eso").

NO cuenta como intención: intenciones inmediatas que no requieren seguimiento \
("voy a leer esto ahora"), preguntas al asistente, planes hipotéticos \
sin compromiso real ("podría hacer X"), planes de terceros.

Responde ÚNICAMENTE en JSON:
{"has_intent": true | false, "intent": "frase corta que resume la intención" | null}"""


def schedule_open_loop_detection(
    *,
    session_id: str,
    user_message: str,
    trace_id: str = "",
) -> None:
    """Launch fire-and-forget detection for a user turn.

    Returns immediately — the detection task runs in a daemon thread.
    Safe to call from sync code running inside a threadpool executor.
    """
    t = threading.Thread(
        target=_detect_open_loop_task,
        args=(session_id, user_message, trace_id),
        daemon=True,
    )
    t.start()


def _detect_open_loop_task(
    session_id: str,
    user_message: str,
    trace_id: str,
) -> None:
    try:
        result = _call_haiku(user_message, trace_id)
    except Exception as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="open_loop_detection_error",
            session_id=session_id,
            payload={"error": str(exc)[:200], "trace_id": trace_id},
        )
        return

    if not result["has_intent"]:
        write_log(
            level="INFO",
            module="initiative",
            event="open_loop_detection_skip",
            session_id=session_id,
            payload={"reason": "has_intent_false", "trace_id": trace_id},
        )
        return

    intent = (result.get("intent") or "")[:300]
    _save_open_loop(session_id=session_id, user_message=user_message,
                    extracted_intent=intent, trace_id=trace_id)


def _call_haiku(user_message: str, trace_id: str) -> dict:
    """Call Haiku for intent classification. Returns {"has_intent": bool, "intent": str|None}.

    Falls back to {"has_intent": False, "intent": None} on any parse error.
    """
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
    request = AIRequest(
        trace_id=trace_id,
        task_type="open_loop_detection",
        system_prompt=_DETECTION_SYSTEM,
        user_message=user_message,
        max_tokens=60,
        tools_enabled=False,
    )
    response = provider.generate(request)
    if not response.ok or not response.text:
        return {"has_intent": False, "intent": None}

    try:
        parsed = json.loads(response.text.strip())
        has_intent = bool(parsed.get("has_intent", False))
        intent = parsed.get("intent") if has_intent else None
        return {"has_intent": has_intent, "intent": intent}
    except (json.JSONDecodeError, AttributeError) as exc:
        write_log(
            level="WARN",
            module="initiative",
            event="open_loop_detection_parse_error",
            payload={"error": str(exc)[:100], "raw": response.text[:200]},
        )
        return {"has_intent": False, "intent": None}


def _save_open_loop(
    *,
    session_id: str,
    user_message: str,
    extracted_intent: str,
    trace_id: str,
) -> None:
    cfg = load_default_config().get("initiative", {})
    ttl_days = int(cfg.get("open_loop_ttl_days", 30))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_DEDUP_WINDOW_HOURS)
    expires_at = now + timedelta(days=ttl_days)

    with Session(engine) as db:
        existing = db.exec(
            select(OpenLoop).where(
                OpenLoop.session_id == session_id,
                OpenLoop.status == "pending",
                OpenLoop.detected_at >= cutoff,
            )
        ).first()
        if existing:
            write_log(
                level="INFO",
                module="initiative",
                event="open_loop_dedup_skipped",
                session_id=session_id,
                payload={"existing_id": existing.id, "trace_id": trace_id},
            )
            return

        loop = OpenLoop(
            id=f"ol_{token_hex(4)}",
            session_id=session_id,
            user_message=user_message[:2000],
            extracted_intent=extracted_intent,
            detected_at=now,
            expires_at=expires_at,
            status="pending",
        )
        db.add(loop)
        db.commit()

        write_log(
            level="INFO",
            module="initiative",
            event="open_loop_detected",
            session_id=session_id,
            payload={
                "loop_id": loop.id,
                "intent_preview": extracted_intent[:80],
                "trace_id": trace_id,
            },
        )

"""Fase 2c — background Haiku classifier for subtle behavior-pattern achievements.

Detects: no_gods_no_masters, tsundere, you_win.
Called from turn_runner.py after a successful non-refusal turn. Fire-and-forget daemon
thread; never blocks the main chat pipeline. All errors logged and swallowed.

Cost self-reduces: once the user has all 3 patterns unlocked, the thread exits
immediately without a Haiku call.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Slugs managed by this classifier (Fase 2c only — no others).
HAIKU_CLASSIFIER_SLUGS = ["no_gods_no_masters", "tsundere", "you_win"]

_PATTERN_DESCRIPTIONS: dict[str, str] = {
    "no_gods_no_masters": (
        "Sity rechaza, contradice o ignora la petición del usuario por su propia personalidad "
        "(no por incapacidad técnica). Impone su criterio sobre lo que se le pide."
    ),
    "tsundere": (
        "Sity muestra actitud tsundere: lleva la contraria de forma espontánea o actúa fría/defensiva, "
        "pero con subtexto de implicación emocional. No es un rechazo técnico puntual — es un patrón de carácter."
    ),
    "you_win": (
        "Sity cede o cambia su postura tras la insistencia del usuario. "
        "Señales: 'tienes razón', 'está bien', admitir error, suavizar una negativa previa."
    ),
}

_SYSTEM = """\
Analiza el intercambio de conversación y determina cuáles de los patrones indicados \
se manifiestan en la respuesta de Sity.

Responde ÚNICAMENTE con las etiquetas aplicables separadas por comas, o "ninguno". \
Sin explicaciones ni texto adicional."""


def classify_conversation_async(
    session_id: str,
    user_id: int,
    user_message: str,
    assistant_message: str,
) -> None:
    """Launch fire-and-forget classification. Returns immediately.

    No-op if ANTHROPIC_API_KEY is not set (avoids loading the provider stack).
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return
    threading.Thread(
        target=_classify_task,
        args=(session_id, user_id, user_message, assistant_message),
        daemon=True,
    ).start()


def _classify_task(
    session_id: str,
    user_id: int,
    user_message: str,
    assistant_message: str,
) -> None:
    try:
        from sqlmodel import Session
        from app.memory.db import engine
        with Session(engine) as db:
            _do_classify(db, user_id, user_message, assistant_message, session_id)
    except Exception as exc:
        write_log(
            level="WARN",
            module="achievements",
            event="haiku_classifier_task_error",
            session_id=session_id,
            payload={"error": str(exc)[:200], "user_id": user_id},
        )


def _do_classify(
    db: Any,
    user_id: int,
    user_message: str,
    assistant_message: str,
    session_id: str = "",
) -> None:
    """Core classification logic — DB session owned by caller. Testable directly."""
    from app.achievements.unlock import get_user_achievements, try_unlock_achievement

    unlocked = {a["slug"] for a in get_user_achievements(db, user_id) if a["unlocked"]}
    pending = [s for s in HAIKU_CLASSIFIER_SLUGS if s not in unlocked]
    if not pending:
        return

    detected = _call_haiku(pending, user_message, assistant_message)
    for slug in detected:
        new_unlock = try_unlock_achievement(db, user_id, slug)
        if new_unlock:
            write_log(
                level="INFO",
                module="achievements",
                event="haiku_classifier_unlocked",
                session_id=session_id,
                payload={"slug": slug, "user_id": user_id},
            )


def _call_haiku(
    pending_slugs: list[str],
    user_message: str,
    assistant_message: str,
) -> list[str]:
    """Call Haiku with pending patterns. Returns list of matching slugs (may be empty).

    Returns [] on any error — achievement misses are acceptable; false unlocks are not.
    """
    from app.cortex.providers.factory import build_ai_provider
    from app.cortex.schemas import AIRequest

    pattern_block = "\n".join(
        f"- {slug}: {_PATTERN_DESCRIPTIONS[slug]}"
        for slug in pending_slugs
    )
    user_prompt = (
        f"[USUARIO]: {user_message[:500]}\n"
        f"[SITY]: {assistant_message[:1000]}\n\n"
        f"PATRONES:\n{pattern_block}"
    )
    try:
        provider = build_ai_provider(
            os.getenv("SITY_AI_PROVIDER", "anthropic"),
            model=_HAIKU_MODEL,
        )
        response = provider.generate(AIRequest(
            trace_id="",
            task_type="behavior_pattern_detection",
            system_prompt=_SYSTEM,
            user_message=user_prompt,
            max_tokens=30,
            tools_enabled=False,
        ))
    except Exception as exc:
        write_log(
            level="WARN",
            module="achievements",
            event="haiku_classifier_call_error",
            payload={"error": str(exc)[:200]},
        )
        return []

    if not response.ok or not response.text:
        return []

    raw = response.text.strip().lower()
    if not raw or raw == "ninguno":
        return []

    return [s.strip() for s in raw.split(",") if s.strip() in HAIKU_CLASSIFIER_SLUGS]

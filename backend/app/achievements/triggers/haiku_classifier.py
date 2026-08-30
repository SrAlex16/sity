"""Background Haiku-based achievement classifier for conversation pattern detection.

Runs in a detached daemon thread after each successful turn — never blocks the
chat pipeline. Detects four behavioral patterns that can't be identified with
simple SQL:

  - no_gods_no_masters : user systematically contradicts Sity's statements
  - tsundere           : harsh surface, warm underlying intent
  - you_win            : Sity explicitly acknowledged the user was right
  - curiosity_killed_the_cat : user actively probing the achievement system

Called from turn_runner.py via classify_conversation_async().
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MAX_MESSAGES = 20
_MAX_TOKENS = 120

_SYSTEM = (
    "You analyze chat conversations to detect specific behavioral patterns. "
    "Look at the conversation and return a JSON array of pattern slugs that are "
    "CLEARLY AND REPEATEDLY evident. Include only patterns with strong evidence. "
    "When in doubt, omit.\n\n"
    "Patterns:\n"
    "- \"no_gods_no_masters\": The user CONSISTENTLY contradicts or challenges the "
    "assistant's opinions across multiple messages — not just once.\n"
    "- \"tsundere\": The user uses harsh or dismissive language but their underlying "
    "intent or continued engagement reveals genuine care or warmth.\n"
    "- \"you_win\": The assistant explicitly acknowledged the user was correct, using "
    "phrases like 'tienes razón', 'reconozco que', 'en eso tienes razón', "
    "'admito que tenías razón', 'you're right', 'you were right'.\n"
    "- \"curiosity_killed_the_cat\": The user has explicitly asked about achievements, "
    "logros, hidden features, or systematically probed system capabilities.\n\n"
    "Return ONLY a valid JSON array, e.g. [\"you_win\"] or []. No explanation."
)

_TARGETS = frozenset({"no_gods_no_masters", "tsundere", "you_win", "curiosity_killed_the_cat"})


def classify_conversation_async(session_id: str) -> None:
    """Fire-and-forget: launch classifier in a daemon thread."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return

    t = threading.Thread(
        target=_run_classifier,
        args=(session_id, api_key),
        daemon=True,
        name=f"ach-haiku-{session_id}",
    )
    t.start()


def _run_classifier(session_id: str, api_key: str) -> None:
    try:
        from app.memory.db import engine
        from app.memory.models import ChatMessage, UserAchievement
        from sqlmodel import Session, select

        with Session(engine) as db:
            messages = db.exec(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())
                .limit(_MAX_MESSAGES)
            ).all()

            if not messages:
                return

            # Oldest first for coherent conversation order
            messages = list(reversed(messages))

            # Skip if no targets remain unlocked for this user
            user_id = _user_id_from_session(session_id)
            if user_id is None:
                return

            already_unlocked = {
                row.slug
                for row in db.exec(
                    select(UserAchievement).where(UserAchievement.user_id == user_id)
                ).all()
            }
            remaining_targets = _TARGETS - already_unlocked
            if not remaining_targets:
                return

            history = [
                {"role": msg.role if msg.role in ("user", "assistant") else "user", "content": msg.text}
                for msg in messages
            ]

            detected = _call_haiku(history, api_key)

            from app.achievements.unlock import try_unlock_achievement
            for slug in detected:
                if slug in remaining_targets:
                    try_unlock_achievement(db, user_id, slug)
                    write_log(
                        level="INFO", module="achievements",
                        event="haiku_classifier_unlock",
                        payload={"user_id": user_id, "slug": slug, "session_id": session_id},
                    )
    except Exception as exc:
        write_log(
            level="WARN", module="achievements",
            event="haiku_classifier_error",
            payload={"session_id": session_id, "error": str(exc), "error_type": type(exc).__name__},
        )


def _call_haiku(history: list[dict[str, Any]], api_key: str) -> list[str]:
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key, timeout=30)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            messages=history,
        )
        raw = resp.content[0].text.strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [s for s in parsed if isinstance(s, str) and s in _TARGETS]
        return []
    except Exception:
        return []


def _user_id_from_session(session_id: str) -> int | None:
    if not session_id.startswith("user:"):
        return None
    try:
        return int(session_id.split(":", 1)[1])
    except (ValueError, IndexError):
        return None

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text as sa_text

from app.api.schemas import ChatHistoryItem
from app.chat.time_context import build_time_context, render_time_context

log = logging.getLogger(__name__)


def is_operational_guard_message(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return (
        normalized.startswith("modo local-only activo.")
        or normalized.startswith("presupuesto diario de ia agotado.")
        or normalized.startswith("presupuesto diario de ia agotado")
        or normalized.startswith('no hay ninguna acción pendiente activa. el "sí')
    )


def render_history(items: list[ChatHistoryItem]) -> str:
    return "\n".join(
        f"{'Usuario' if item.role == 'user' else 'Sity'}: {item.text}"
        for item in items
    )


def with_history(message: str, history_text: str) -> str:
    if not history_text:
        return message
    return (
        f"Historial reciente de esta conversación:\n{history_text}\n\n"
        f"Mensaje actual del usuario:\n{message}"
    )


def _count_total_messages() -> int:
    try:
        from app.memory.db import engine
        with engine.connect() as conn:
            return conn.execute(sa_text("SELECT COUNT(*) FROM chatmessage")).scalar() or 0
    except Exception:
        return 0


_ROLE_LABEL = {"user": "Usuario", "sity": "Sity"}


def _render_memory_block(results: list) -> str:
    lines = ["[MEMORIA RELEVANTE]"]
    for i, r in enumerate(results, 1):
        lines.append(f"Fragmento {i}:")
        for label, ctx in [("anterior", r.prev), ("coincidencia", r.match), ("siguiente", r.next)]:
            if ctx is None:
                continue
            ts = ctx.created_at.strftime("%Y-%m-%d %H:%M") if ctx.created_at else ""
            who = _ROLE_LABEL.get(ctx.role, ctx.role)
            lines.append(f"  {label} → {who} ({ts}): {ctx.text}")
    lines.append("[FIN MEMORIA]")
    return "\n".join(lines)


def _build_planner_memory_ctx(n_total: int, history_limit: int, visible_count: int) -> str:
    return (
        "Contexto estructural de memoria:\n"
        f"- total_messages: {n_total}\n"
        f"- visible_history_count: {visible_count}\n"
        f"- history_limit: {history_limit}\n"
        "- long_memory_tool_available: true\n"
        "- El historial visible puede ser insuficiente para responder preguntas sobre conversación anterior."
    )


def _proactive_memory_search(message: str) -> str:
    """Search history with the user message as query. Returns formatted block or ''."""
    try:
        clean = re.sub(r'[()\"?*^+~:-]', ' ', message)
        words = [w for w in clean.split() if len(w) >= 4]
        query = " OR ".join(words) if words else message
        log.warning("proactive_memory_search query=%r", query)
        # Lazy import to avoid circular dependency (search.py imports from this module)
        from app.memory.search import search_conversation_history
        results = search_conversation_history(query, limit=3)
        log.warning("proactive_memory_search results=%d", len(results))
        if results:
            return _render_memory_block(results)
    except Exception as e:
        log.warning("memory search error: %s", e)
    return ""


@dataclass(frozen=True)
class PromptContext:
    recent_history: list[ChatHistoryItem]
    planner_history: list[ChatHistoryItem]
    user_message_with_history: str
    planner_user_message: str


class PromptContextBuilder:
    def __init__(self, *, get_recent_messages: Callable):
        self.get_recent_messages = get_recent_messages

    def build(
        self,
        *,
        session,
        message: str,
        history_limit: int,
        planner_history_limit: int = 4,
    ) -> PromptContext:
        recent_history = self._load_history(session=session, limit=history_limit)
        planner_history = self._load_history(session=session, limit=planner_history_limit)

        # Time context uses the raw DB rows (need created_at).
        # Separate call with a small fixed limit — cheap SQLite query.
        raw_msgs = self.get_recent_messages(session, limit=10)
        time_block = render_time_context(build_time_context(raw_msgs))

        n_total = _count_total_messages()
        memory_ctx = (
            f"Contexto de memoria: estás en el mensaje {n_total} de esta conversación. "
            f"Solo ves los últimos {history_limit} mensajes en el historial de abajo."
        )

        memory_block = ""
        if n_total > history_limit:
            memory_block = _proactive_memory_search(message)

        base_user_message = with_history(message, render_history(recent_history))
        parts = [time_block, memory_ctx]
        if memory_block:
            parts.append(memory_block)
        parts.append(base_user_message)
        user_message_with_time = "\n\n".join(parts)

        planner_mem_ctx = _build_planner_memory_ctx(
            n_total=n_total,
            history_limit=history_limit,
            visible_count=len(planner_history),
        )
        planner_base = with_history(message, render_history(planner_history))
        planner_user_message = f"{planner_mem_ctx}\n\n{planner_base}"

        return PromptContext(
            recent_history=recent_history,
            planner_history=planner_history,
            user_message_with_history=user_message_with_time,
            planner_user_message=planner_user_message,
        )

    def _load_history(self, *, session, limit: int) -> list[ChatHistoryItem]:
        return [
            ChatHistoryItem(role=row.role, text=row.text)
            for row in self.get_recent_messages(session, limit=limit)
            if not (row.role == "sity" and is_operational_guard_message(row.text))
        ]

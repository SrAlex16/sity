from __future__ import annotations

import logging
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


def _history_to_messages(items: list[ChatHistoryItem]) -> list[dict]:
    """Convert history items to structured API messages, merging consecutive same-role turns."""
    result: list[dict] = []
    for item in items:
        role = "user" if item.role == "user" else "assistant"
        if result and result[-1]["role"] == role:
            result[-1]["content"] += "\n" + item.text
        else:
            result.append({"role": role, "content": item.text})
    return result


def _count_total_messages() -> int:
    try:
        from app.memory.db import engine
        with engine.connect() as conn:
            return conn.execute(sa_text("SELECT COUNT(*) FROM chatmessage")).scalar() or 0
    except Exception:
        return 0


def _build_task_context_block(ctx: dict[str, str] | None) -> str:
    if not ctx:
        return ""
    lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items())
    return f"Contexto de tarea activa (datos ya resueltos en este hilo):\n{lines}"


def _build_planner_memory_ctx(n_total: int, history_limit: int, visible_count: int) -> str:
    return (
        "Contexto estructural de memoria:\n"
        f"- total_messages: {n_total}\n"
        f"- visible_history_count: {visible_count}\n"
        f"- history_limit: {history_limit}\n"
        "- long_memory_tool_available: true\n"
        "- El historial visible puede ser insuficiente para responder preguntas sobre conversación anterior."
    )


@dataclass(frozen=True)
class PromptContext:
    recent_history: list[ChatHistoryItem]
    planner_history: list[ChatHistoryItem]
    user_message_with_history: str
    planner_user_message: str
    prior_messages: list[dict]
    planner_prior_messages: list[dict]


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
        trace_id: str = "",
        input_mode: str = "text",
        output_mode: str = "text",
        skip_last_turns: int = 0,
        task_context: dict[str, str] | None = None,
    ) -> PromptContext:
        recent_history = self._load_history(session=session, limit=history_limit, skip_last=skip_last_turns)
        planner_history = self._load_history(session=session, limit=planner_history_limit, skip_last=skip_last_turns)

        # Time context uses the raw DB rows (need created_at).
        # Separate call with a small fixed limit — cheap SQLite query.
        raw_msgs = self.get_recent_messages(session, limit=10)
        time_block = render_time_context(build_time_context(raw_msgs))

        n_total = _count_total_messages()
        memory_ctx = (
            f"Contexto de memoria: estás en el mensaje {n_total} de esta conversación. "
            f"Solo ves los últimos {history_limit} mensajes en el historial de abajo."
        )

        parts = [time_block, memory_ctx]
        if input_mode == "voice":
            parts.append("[input_mode: voice]")
        if output_mode == "voice":
            parts.append("[output_mode: voice]")
        parts.append(message)
        user_message_with_time = "\n\n".join(parts)

        prior_messages = _history_to_messages(recent_history)
        planner_prior_messages = _history_to_messages(planner_history)

        planner_mem_ctx = _build_planner_memory_ctx(
            n_total=n_total,
            history_limit=history_limit,
            visible_count=len(planner_history),
        )
        task_ctx_block = _build_task_context_block(task_context)
        planner_user_message = (
            f"{planner_mem_ctx}\n\n{task_ctx_block}\n\n{message}"
            if task_ctx_block
            else f"{planner_mem_ctx}\n\n{message}"
        )

        return PromptContext(
            recent_history=recent_history,
            planner_history=planner_history,
            user_message_with_history=user_message_with_time,
            planner_user_message=planner_user_message,
            prior_messages=prior_messages,
            planner_prior_messages=planner_prior_messages,
        )

    def _load_history(self, *, session, limit: int, skip_last: int = 0) -> list[ChatHistoryItem]:
        rows = [
            ChatHistoryItem(role=row.role, text=row.text)
            for row in self.get_recent_messages(session, limit=limit + skip_last)
            if not (row.role == "sity" and is_operational_guard_message(row.text))
        ]
        if skip_last > 0:
            rows = rows[:-skip_last] if len(rows) > skip_last else []
        return rows

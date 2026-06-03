from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text as sa_text

from app.api.schemas import ChatHistoryItem
from app.chat.time_context import build_time_context, render_time_context


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
            f"Solo ves los últimos {history_limit} mensajes en el historial de abajo. "
            f"El historial completo está almacenado y puedes buscarlo con "
            f"search_conversation_history."
        )

        base_user_message = with_history(message, render_history(recent_history))
        user_message_with_time = f"{time_block}\n\n{memory_ctx}\n\n{base_user_message}"

        return PromptContext(
            recent_history=recent_history,
            planner_history=planner_history,
            user_message_with_history=user_message_with_time,
            planner_user_message=with_history(message, render_history(planner_history)),
        )

    def _load_history(self, *, session, limit: int) -> list[ChatHistoryItem]:
        return [
            ChatHistoryItem(role=row.role, text=row.text)
            for row in self.get_recent_messages(session, limit=limit)
            if not (row.role == "sity" and is_operational_guard_message(row.text))
        ]

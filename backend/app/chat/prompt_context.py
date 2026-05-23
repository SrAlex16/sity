from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.api.schemas import ChatHistoryItem


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

        return PromptContext(
            recent_history=recent_history,
            planner_history=planner_history,
            user_message_with_history=with_history(message, render_history(recent_history)),
            planner_user_message=with_history(message, render_history(planner_history)),
        )

    def _load_history(self, *, session, limit: int) -> list[ChatHistoryItem]:
        return [
            ChatHistoryItem(role=row.role, text=row.text)
            for row in self.get_recent_messages(session, limit=limit)
            if not (row.role == "sity" and is_operational_guard_message(row.text))
        ]

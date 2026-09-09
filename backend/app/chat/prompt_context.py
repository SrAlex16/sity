from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text as sa_text
from sqlmodel import Session, select as _select

from app.api.schemas import ChatHistoryItem
from app.chat.time_context import build_time_context, render_time_context

log = logging.getLogger(__name__)

# Max number of history turns (user messages) from which images are included.
# Images from turns older than this are silently dropped to cap token cost.
_IMAGE_HISTORY_TURNS_MAX = 2


def is_operational_guard_message(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return (
        normalized.startswith("modo local-only activo.")
        or normalized.startswith("presupuesto diario de ia agotado.")
        or normalized.startswith("presupuesto diario de ia agotado")
        or normalized.startswith('no hay ninguna acción pendiente activa. el "sí')
    )


def _history_to_messages(items: list[ChatHistoryItem], include_images: bool = True) -> list[dict]:
    """Convert history items to structured API messages, merging consecutive same-role turns.

    When include_images=True (default), items with attached images produce content-block
    messages ([{type: image}, {type: text}]) per the Anthropic multi-modal API.
    Image turns are never merged with adjacent turns.
    """
    result: list[dict] = []
    for item in items:
        role = "user" if item.role == "user" else "assistant"
        if include_images and item.images:
            blocks: list[dict] = [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
                }
                for img in item.images
            ]
            blocks.append({"type": "text", "text": item.text})
            result.append({"role": role, "content": blocks})
        else:
            # Merge consecutive same-role text-only messages
            if result and result[-1]["role"] == role and isinstance(result[-1]["content"], str):
                result[-1]["content"] += "\n" + item.text
            else:
                result.append({"role": role, "content": item.text})
    return result


def _attach_history_images(session: Session, raw_rows: list, items: list[ChatHistoryItem]) -> None:
    """Load FileArtifact image data for user history items (up to _IMAGE_HISTORY_TURNS_MAX turns).

    Mutates `items` in-place by replacing entries that have linked images with
    new ChatHistoryItem instances that carry the base64 data.
    Errors (missing file, DB error) are silently swallowed per-image.
    """
    if session is None:
        return
    from app.chat.file_artifact import PROJECT_ROOT
    from app.memory.models import FileArtifact

    image_turns_included = 0
    for i in range(len(raw_rows) - 1, -1, -1):
        if image_turns_included >= _IMAGE_HISTORY_TURNS_MAX:
            break
        row = raw_rows[i]
        if row.role != "user":
            continue
        row_id = getattr(row, "id", None)
        if row_id is None:
            continue

        try:
            artifacts = session.exec(
                _select(FileArtifact).where(
                    FileArtifact.chat_message_id == row_id,
                    FileArtifact.artifact_type == "image",
                )
            ).all()
        except Exception:
            continue

        if not artifacts:
            continue

        images: list[dict] = []
        for art in artifacts:
            try:
                img_path = PROJECT_ROOT / art.rel_path
                img_bytes = img_path.read_bytes()
                img_b64 = base64.b64encode(img_bytes).decode()
                images.append({"media_type": art.mime_type or "image/jpeg", "data": img_b64})
            except Exception:
                log.warning("history_image_load_failed rel_path=%s", art.rel_path)

        if images:
            items[i] = ChatHistoryItem(role=items[i].role, text=items[i].text, images=images)
            image_turns_included += 1


def _count_total_messages(session_id: str = "") -> int:
    try:
        from app.memory.db import engine
        with engine.connect() as conn:
            if session_id:
                return conn.execute(
                    sa_text("SELECT COUNT(*) FROM chatmessage WHERE session_id = :sid"),
                    {"sid": session_id},
                ).scalar() or 0
            return conn.execute(sa_text("SELECT COUNT(*) FROM chatmessage")).scalar() or 0
    except Exception:
        return 0


def _build_task_context_block(ctx: dict[str, str] | None) -> str:
    if not ctx:
        return ""
    lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items())
    return f"Contexto de tarea activa (datos ya resueltos en este hilo):\n{lines}"


def _affinity_label(v: float) -> str:
    if v >= 0.7:
        return "alta"
    if v >= 0.4:
        return "moderada"
    if v >= 0.15:
        return "baja"
    return "muy baja"


def _trust_avg_label(v: float) -> str:
    if v >= 0.75:
        return "consolidada"
    if v >= 0.55:
        return "establecida"
    if v >= 0.35:
        return "en construcción"
    return "incipiente"


def _familiarity_label(v: float) -> str:
    if v >= 0.5:
        return "muy conocida"
    if v >= 0.2:
        return "conocida"
    if v >= 0.05:
        return "en proceso de conocerse"
    return "primera interacción"


def _build_social_context_block(session: Session, session_id: str) -> str:
    """Return a social relationship context block for user: sessions with an existing profile.

    Returns "" for guest sessions or users with no SocialProfile yet (first contact).
    Read-only — never modifies the DB.
    """
    if not session_id.startswith("user:"):
        return ""
    try:
        user_id = int(session_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return ""
    try:
        row = session.execute(
            sa_text(
                "SELECT id, familiarity, affinity,"
                " trust_honesty, trust_intentions, trust_competence, trust_reliability,"
                " comfort, conflict"
                " FROM socialprofile WHERE user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchone()
    except Exception:
        log.exception("social_context_read_error user_id=%s", user_id)
        return ""
    if row is None:
        return ""
    profile_id, familiarity, affinity, th, ti, tc, tr, comfort, conflict = row
    trust_avg = (th + ti + tc + tr) / 4.0

    # Fetch active narrative reflection (if any)
    reflection_content: str | None = None
    try:
        from app.memory.models import utc_now
        now_str = utc_now().isoformat()
        ref_row = session.execute(
            sa_text(
                "SELECT content FROM socialreflection"
                " WHERE profile_id = :pid"
                " AND superseded_at IS NULL"
                " AND expires_at > :now"
                " ORDER BY created_at DESC LIMIT 1"
            ),
            {"pid": profile_id, "now": now_str},
        ).fetchone()
        if ref_row:
            reflection_content = ref_row[0]
    except Exception:
        log.exception("social_reflection_read_error user_id=%s", user_id)

    lines = [
        "Contexto de relación (uso interno — informa tono y disposición, no citar):",
        f"- Familiaridad: {_familiarity_label(familiarity)}",
        f"- Afinidad: {_affinity_label(affinity)}",
        f"- Confianza: {_trust_avg_label(trust_avg)}",
    ]
    if conflict >= 0.4:
        lines.append(f"- Tensión acumulada: presente (nivel {conflict:.2f})")
    if reflection_content:
        lines.append(f"- Patrón observado: {reflection_content}")
    lines.append(
        "Deja que esto module el tono con el que te expresas; "
        "no menciones esta evaluación explícitamente."
    )
    return "\n".join(lines)


def _build_location_block(session: Session, session_id: str) -> str:
    """Return location context block for prompt injection.

    Returns "" when no location is stored or on any error.
    """
    try:
        from app.settings.settings_service import SettingsService
        from app.chat.location_context import build_location_context, render_location_context
        settings = SettingsService(session).get_location_settings(session_id=session_id)
        return render_location_context(build_location_context(settings))
    except Exception:
        return ""


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
        session_id: str = "",
    ) -> PromptContext:
        recent_history = self._load_history(session=session, limit=history_limit, skip_last=skip_last_turns, attach_images=True)
        planner_history = self._load_history(session=session, limit=planner_history_limit, skip_last=skip_last_turns)

        # Time context uses the raw DB rows (need created_at).
        # Separate call with a small fixed limit — cheap SQLite query.
        raw_msgs = self.get_recent_messages(session, limit=10)
        time_block = render_time_context(build_time_context(raw_msgs))

        n_total = _count_total_messages(session_id)
        memory_ctx = (
            f"Contexto de memoria: estás en el mensaje {n_total} de esta conversación. "
            f"Solo ves los últimos {history_limit} mensajes en el historial de abajo."
        )

        social_block = _build_social_context_block(session, session_id)
        location_block = _build_location_block(session, session_id)

        parts = [time_block, memory_ctx]
        if social_block:
            parts.append(social_block)
        if location_block:
            parts.append(location_block)
        if input_mode == "voice":
            parts.append("[input_mode: voice]")
        if output_mode == "voice":
            parts.append("[output_mode: voice]")
        parts.append(message)
        user_message_with_time = "\n\n".join(parts)

        prior_messages = _history_to_messages(recent_history)
        planner_prior_messages = _history_to_messages(planner_history, include_images=False)

        planner_mem_ctx = _build_planner_memory_ctx(
            n_total=n_total,
            history_limit=history_limit,
            visible_count=len(planner_history),
        )
        task_ctx_block = _build_task_context_block(task_context)
        planner_parts = [planner_mem_ctx]
        if task_ctx_block:
            planner_parts.append(task_ctx_block)
        if social_block:
            planner_parts.append(social_block)
        if location_block:
            planner_parts.append(location_block)
        planner_parts.append(message)
        planner_user_message = "\n\n".join(planner_parts)

        return PromptContext(
            recent_history=recent_history,
            planner_history=planner_history,
            user_message_with_history=user_message_with_time,
            planner_user_message=planner_user_message,
            prior_messages=prior_messages,
            planner_prior_messages=planner_prior_messages,
        )

    def _load_history(self, *, session, limit: int, skip_last: int = 0, attach_images: bool = False) -> list[ChatHistoryItem]:
        raw_rows = [
            row
            for row in self.get_recent_messages(session, limit=limit + skip_last)
            if not (row.role == "sity" and is_operational_guard_message(row.text))
        ]
        if skip_last > 0:
            raw_rows = raw_rows[:-skip_last] if len(raw_rows) > skip_last else []
        items = [ChatHistoryItem(role=row.role, text=row.text) for row in raw_rows]
        if attach_images:
            try:
                _attach_history_images(session, raw_rows, items)
            except Exception:
                pass
        return items

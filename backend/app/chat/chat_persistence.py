"""
chat_persistence.py — database helpers for chat messages and token usage.

Extracted from routes_chat.py. Contains only side-effectful DB operations;
no HTTP, no AI calls, no prompt building.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, func, select

from app.memory.message_metadata import MessageMetadata, build_message_metadata
from app.memory.models import AIUsage, ChatMessage, ChatSession, utc_now

DEFAULT_CHAT_SESSION_ID = "default"


def get_or_create_default_chat_session(session: Session) -> ChatSession:
    chat_session = session.get(ChatSession, DEFAULT_CHAT_SESSION_ID)

    if chat_session:
        return chat_session

    chat_session = ChatSession(id=DEFAULT_CHAT_SESSION_ID)
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    return chat_session


def save_chat_message(
    session: Session,
    *,
    role: str,
    text: str,
    trace_id: Optional[str] = None,
    tone_meta: Optional[str] = None,
    metadata: Optional[MessageMetadata] = None,
    input_mode: str = "text",
    voice_transcript_original: Optional[str] = None,
    edit_distance_pct: Optional[float] = None,
    output_mode: str = "text",
    tts_fragments: Optional[int] = None,
    source_channel: str = "web",
) -> None:
    if metadata is None:
        metadata = build_message_metadata(role=role)

    get_or_create_default_chat_session(session)

    session.add(
        ChatMessage(
            session_id=DEFAULT_CHAT_SESSION_ID,
            role=role,
            text=text,
            trace_id=trace_id,
            tone_meta=tone_meta,
            speaker_id=metadata.speaker_id,
            speaker_label=metadata.speaker_label,
            speaker_source=metadata.speaker_source,
            speaker_confidence=metadata.speaker_confidence,
            identity_evidence_json=metadata.identity_evidence_json,
            dataset_source=metadata.dataset_source,
            dataset_eligible=metadata.dataset_eligible,
            dataset_tags_json=metadata.dataset_tags_json,
            input_mode=input_mode,
            voice_transcript_original=voice_transcript_original,
            edit_distance_pct=edit_distance_pct,
            output_mode=output_mode,
            tts_fragments=tts_fragments,
            source_channel=source_channel,
        )
    )

    chat_session = session.get(ChatSession, DEFAULT_CHAT_SESSION_ID)
    if chat_session:
        chat_session.updated_at = utc_now()
        session.add(chat_session)

    session.commit()


def get_recent_db_messages(session: Session, limit: int = 20) -> list[ChatMessage]:
    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == DEFAULT_CHAT_SESSION_ID)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list(session.exec(statement))
    return list(reversed(rows))


def get_today_token_usage(session: Session) -> int:
    now_local = datetime.now().astimezone()
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(timezone.utc).replace(tzinfo=None)

    result = session.exec(
        select(func.sum(AIUsage.input_tokens + AIUsage.output_tokens)).where(
            AIUsage.created_at >= today_start_utc
        )
    ).one()

    return int(result or 0)

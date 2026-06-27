"""
turn_persistence.py — per-turn message save helper with capture context.

ChatTurnPersistence encapsulates the DatasetCapture metadata that must be
applied to every message saved during a single chat turn. It replaces the
_save_with_capture closure that previously lived inside _chat_message_inner.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Optional

from sqlmodel import Session

from app.chat.chat_persistence import save_chat_message
from app.memory.message_metadata import MessageMetadata
from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService


class ChatTurnPersistence:
    """Wraps save_chat_message with role-specific capture metadata for one turn."""

    def __init__(
        self,
        session: Session,
        capture_ctx: DatasetCaptureContext,
        capture_svc: DatasetCaptureService,
    ) -> None:
        self._session = session
        self._user_metadata = capture_svc.build_user_metadata(capture_ctx)
        self._sity_metadata = capture_svc.build_sity_metadata(capture_ctx)

    def tag_sity_with_model(self, model: str) -> None:
        """If model contains 'sonnet', add sonnet_response tag to sity metadata."""
        if "sonnet" not in (model or "").lower():
            return
        base = self._sity_metadata
        existing: list[str] = json.loads(base.dataset_tags_json) if base.dataset_tags_json else []
        if "sonnet_response" not in existing:
            existing.append("sonnet_response")
        self._sity_metadata = dataclasses.replace(
            base, dataset_tags_json=json.dumps(existing)
        )

    def save(
        self,
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
            metadata = self._sity_metadata if role == "sity" else self._user_metadata
        save_chat_message(
            self._session,
            role=role,
            text=text,
            trace_id=trace_id,
            tone_meta=tone_meta,
            metadata=metadata,
            input_mode=input_mode,
            voice_transcript_original=voice_transcript_original,
            edit_distance_pct=edit_distance_pct,
            output_mode=output_mode,
            tts_fragments=tts_fragments,
            source_channel=source_channel,
        )

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

from app.chat.chat_persistence import DEFAULT_CHAT_SESSION_ID, save_chat_message
from app.memory.message_metadata import MessageMetadata
from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService


def _patch_for_guest(meta: "MessageMetadata", *, is_user: bool) -> "MessageMetadata":
    """Apply guest-session overrides: human_guest source + guest_session tag."""
    existing: list[str] = json.loads(meta.dataset_tags_json) if isinstance(meta.dataset_tags_json, str) else []
    if "guest_session" not in existing:
        existing.append("guest_session")
    return dataclasses.replace(
        meta,
        dataset_source="human_guest",
        dataset_eligible=True,
        speaker_source="human_guest" if is_user else meta.speaker_source,
        dataset_tags_json=json.dumps(existing),
    )


class ChatTurnPersistence:
    """Wraps save_chat_message with role-specific capture metadata for one turn."""

    def __init__(
        self,
        session: Session,
        capture_ctx: DatasetCaptureContext,
        capture_svc: DatasetCaptureService,
        session_id: str = DEFAULT_CHAT_SESSION_ID,
    ) -> None:
        self._session = session
        self._session_id = session_id
        self._user_metadata = capture_svc.build_user_metadata(capture_ctx)
        self._sity_metadata = capture_svc.build_sity_metadata(capture_ctx)
        if session_id.startswith("guest:"):
            if isinstance(self._user_metadata, MessageMetadata):
                self._user_metadata = _patch_for_guest(self._user_metadata, is_user=True)
            if isinstance(self._sity_metadata, MessageMetadata):
                self._sity_metadata = _patch_for_guest(self._sity_metadata, is_user=False)

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

    def mark_direct_order_override(self) -> None:
        """Mark both user and sity messages as non-eligible for this turn."""
        def _patch(meta: "MessageMetadata") -> "MessageMetadata":
            existing: list[str] = json.loads(meta.dataset_tags_json) if meta.dataset_tags_json else []
            if "direct_order_override" not in existing:
                existing.append("direct_order_override")
            return dataclasses.replace(meta, dataset_eligible=False, dataset_tags_json=json.dumps(existing))

        self._user_metadata = _patch(self._user_metadata)
        self._sity_metadata = _patch(self._sity_metadata)

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
    ) -> int:
        if metadata is None:
            metadata = self._sity_metadata if role == "sity" else self._user_metadata
        return save_chat_message(
            self._session,
            session_id=self._session_id,
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

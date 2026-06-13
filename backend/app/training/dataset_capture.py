"""DatasetCaptureContext — per-turn metadata override for dataset collection.

When capture mode is enabled the chat route applies this context to every
ChatMessage saved during that turn.  State is persisted in the Setting table
so it survives backend restarts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.memory.message_metadata import MessageMetadata, build_message_metadata
from app.memory.models import Setting, utc_now

_SETTING_KEY = "dataset_capture"


@dataclass
class DatasetCaptureContext:
    enabled: bool = False
    dataset_source: str = "normal_use"
    speaker_label: Optional[str] = None
    speaker_source: Optional[str] = None
    speaker_confidence: Optional[float] = None
    dataset_eligible: bool = True
    dataset_tags: list[str] = field(default_factory=list)
    updated_at: Optional[str] = None
    demo_start_at: Optional[str] = None


def _ctx_to_dict(ctx: DatasetCaptureContext) -> dict[str, Any]:
    return {
        "enabled": ctx.enabled,
        "dataset_source": ctx.dataset_source,
        "speaker_label": ctx.speaker_label,
        "speaker_source": ctx.speaker_source,
        "speaker_confidence": ctx.speaker_confidence,
        "dataset_eligible": ctx.dataset_eligible,
        "dataset_tags": ctx.dataset_tags,
        "updated_at": ctx.updated_at,
        "demo_start_at": ctx.demo_start_at,
    }


class DatasetCaptureService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self) -> DatasetCaptureContext:
        row = self._session.exec(
            select(Setting).where(Setting.key == _SETTING_KEY)
        ).first()
        if not row:
            return DatasetCaptureContext()
        try:
            raw = json.loads(row.value_json)
            if not isinstance(raw, dict):
                return DatasetCaptureContext()
        except (json.JSONDecodeError, ValueError):
            return DatasetCaptureContext()
        return DatasetCaptureContext(
            enabled=bool(raw.get("enabled", False)),
            dataset_source=raw.get("dataset_source", "normal_use"),
            speaker_label=raw.get("speaker_label"),
            speaker_source=raw.get("speaker_source"),
            speaker_confidence=raw.get("speaker_confidence"),
            dataset_eligible=bool(raw.get("dataset_eligible", True)),
            dataset_tags=list(raw.get("dataset_tags") or []),
            updated_at=raw.get("updated_at"),
            demo_start_at=raw.get("demo_start_at"),
        )

    def save(self, ctx: DatasetCaptureContext) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        data = dict(_ctx_to_dict(ctx))
        data["updated_at"] = now_iso
        value_json = json.dumps(data)
        now_dt = utc_now()
        existing = self._session.exec(
            select(Setting).where(Setting.key == _SETTING_KEY)
        ).first()
        if existing:
            existing.value_json = value_json
            existing.source = "ui"
            existing.updated_at = now_dt
            self._session.add(existing)
        else:
            self._session.add(Setting(
                key=_SETTING_KEY,
                value_json=value_json,
                source="ui",
                created_at=now_dt,
                updated_at=now_dt,
            ))
        self._session.commit()

    def disable(self) -> DatasetCaptureContext:
        ctx = self.get()
        disabled = DatasetCaptureContext(
            enabled=False,
            dataset_source=ctx.dataset_source,
            speaker_label=ctx.speaker_label,
            speaker_source=ctx.speaker_source,
            speaker_confidence=ctx.speaker_confidence,
            dataset_eligible=ctx.dataset_eligible,
            dataset_tags=ctx.dataset_tags,
            demo_start_at=None,
        )
        self.save(disabled)
        return self.get()

    def build_user_metadata(self, ctx: DatasetCaptureContext) -> MessageMetadata:
        if not ctx.enabled:
            return build_message_metadata(role="user")
        tags_json = json.dumps(ctx.dataset_tags) if ctx.dataset_tags else None
        return build_message_metadata(
            role="user",
            speaker_source=ctx.speaker_source,
            speaker_label=ctx.speaker_label,
            speaker_confidence=ctx.speaker_confidence,
            dataset_source=ctx.dataset_source,
            dataset_eligible=ctx.dataset_eligible,
            dataset_tags_json=tags_json,
        )

    def build_sity_metadata(self, ctx: DatasetCaptureContext) -> MessageMetadata:
        if not ctx.enabled:
            return build_message_metadata(role="sity")
        tags_json = json.dumps(ctx.dataset_tags) if ctx.dataset_tags else None
        return build_message_metadata(
            role="sity",
            speaker_source="sity_local",
            dataset_source=ctx.dataset_source,
            dataset_eligible=ctx.dataset_eligible,
            dataset_tags_json=tags_json,
        )

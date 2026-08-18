"""InitiativeSettings — schema and per-session read/write for the 4 initiative toggles.

Stores settings as Setting rows with prefix "initiative.", same pattern as voice/language.
All 4 keys are per-session (session_id scope), with opt-out defaults (all True).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.memory.models import Setting, utc_now


class InitiativeSettings(BaseModel):
    enabled: bool = True
    trigger_conversation_abandoned: bool = True
    trigger_long_inactivity: bool = True
    trigger_open_loop: bool = True


_INITIATIVE_PER_SESSION = (
    "enabled",
    "trigger_conversation_abandoned",
    "trigger_long_inactivity",
    "trigger_open_loop",
)


def get_initiative_settings(
    session: Session,
    session_id: Optional[str] = None,
) -> InitiativeSettings:
    defaults = InitiativeSettings()
    data: dict[str, Any] = {}

    for key in _INITIATIVE_PER_SESSION:
        row = None
        if session_id is not None:
            row = session.exec(
                select(Setting).where(
                    Setting.key == f"initiative.{key}",
                    Setting.session_id == session_id,
                )
            ).first()
        if row is None:
            row = session.exec(
                select(Setting).where(
                    Setting.key == f"initiative.{key}",
                    col(Setting.session_id).is_(None),
                )
            ).first()
        if row is not None:
            data[key] = json.loads(row.value_json)

    return InitiativeSettings(**{**defaults.model_dump(), **data})


def set_initiative_settings(
    session: Session,
    settings: InitiativeSettings,
    session_id: Optional[str] = None,
    source: str = "ui",
) -> InitiativeSettings:
    for key in _INITIATIVE_PER_SESSION:
        _upsert(session, f"initiative.{key}", getattr(settings, key), source, session_id)
    return get_initiative_settings(session, session_id=session_id)


def _upsert(
    session: Session,
    key: str,
    value: Any,
    source: str,
    session_id: Optional[str],
) -> None:
    if session_id is None:
        existing = session.exec(
            select(Setting).where(
                Setting.key == key,
                col(Setting.session_id).is_(None),
            )
        ).first()
    else:
        existing = session.exec(
            select(Setting).where(
                Setting.key == key,
                Setting.session_id == session_id,
            )
        ).first()

    now = utc_now()
    if existing:
        existing.value_json = json.dumps(value)
        existing.source = source
        existing.updated_at = now
        session.add(existing)
    else:
        session.add(
            Setting(
                key=key,
                value_json=json.dumps(value),
                source=source,
                session_id=session_id,
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()

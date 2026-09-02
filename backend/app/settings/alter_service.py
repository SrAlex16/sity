"""AlterService — saved personality presets per user slot.

Each user has 5 fixed slots. A slot is "empty" when no PersonalityAlter row
exists for it; the service synthesizes the empty representation on the fly so
callers always get a list of exactly 5 slots.

copy_alter copies both parameters AND name (slot B becomes an identical clone
of slot A — simple and unambiguous).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlmodel import Session, select

from app.memory.models import PersonalityAlter, utc_now
from app.settings.settings_service import PERSONALITY_KEYS, SettingsService
from app.trace.logger import write_log

_MAX_SLOTS = 5

_EMPTY_SLOT: dict[str, Any] = {"name": None, "parameters": None, "is_empty": True}


class AlterService:
    def __init__(self, session: Session):
        self.session = session
        self._svc = SettingsService(session)

    # ── Public API ────────────────────────────────────────────────────────────

    def list_alters(self, user_id: int) -> list[dict[str, Any]]:
        """Return all 5 slots for a user; empty slots have is_empty=True."""
        rows = {
            row.slot: row
            for row in self.session.exec(
                select(PersonalityAlter).where(PersonalityAlter.user_id == user_id)
            ).all()
        }
        result = []
        for slot in range(1, _MAX_SLOTS + 1):
            row = rows.get(slot)
            if row is None:
                result.append({"slot": slot, **_EMPTY_SLOT})
            else:
                assert row.parameters_json is not None
                result.append({
                    "slot": slot,
                    "name": row.name,
                    "parameters": json.loads(row.parameters_json),
                    "is_empty": False,
                })
        return result

    def save_alter(
        self,
        user_id: int,
        slot: int,
        name: str,
        current_session_id: str,
    ) -> dict[str, Any]:
        """Snapshot the current session personality into the given slot."""
        self._validate_slot(slot)
        params = self._svc.get_personality(session_id=current_session_id)
        if set(params.keys()) != PERSONALITY_KEYS:
            raise RuntimeError("Personality snapshot is incomplete")
        params_json = json.dumps(params)
        existing = self._get_row(user_id, slot)
        now = utc_now()
        if existing is not None:
            existing.name = name
            existing.parameters_json = params_json
            existing.updated_at = now
            self.session.add(existing)
        else:
            self.session.add(PersonalityAlter(
                user_id=user_id,
                slot=slot,
                name=name,
                parameters_json=params_json,
                created_at=now,
                updated_at=now,
            ))
        self.session.commit()
        write_log(level="INFO", module="alters", event="alter_saved",
                  payload={"user_id": user_id, "slot": slot, "name": name})
        return {"slot": slot, "name": name, "parameters": params, "is_empty": False}

    def load_alter(
        self,
        user_id: int,
        slot: int,
        session_id: str,
    ) -> dict[str, float]:
        """Apply saved slot to the session. Returns the resulting personality."""
        self._validate_slot(slot)
        row = self._get_row(user_id, slot)
        if row is None:
            raise ValueError(f"Slot {slot} is empty — nothing to load")
        assert row.parameters_json is not None
        params: dict[str, float] = json.loads(row.parameters_json)
        result = self._svc.set_all_personality(session_id, params)
        write_log(level="INFO", module="alters", event="alter_loaded",
                  payload={"user_id": user_id, "slot": slot, "name": row.name, "session_id": session_id})
        return result

    def rename_alter(self, user_id: int, slot: int, new_name: str) -> None:
        """Rename slot without touching parameters."""
        self._validate_slot(slot)
        row = self._get_row(user_id, slot)
        if row is None:
            raise ValueError(f"Slot {slot} is empty — nothing to rename")
        row.name = new_name
        row.updated_at = utc_now()
        self.session.add(row)
        self.session.commit()
        write_log(level="INFO", module="alters", event="alter_renamed",
                  payload={"user_id": user_id, "slot": slot, "new_name": new_name})

    def clear_alter(self, user_id: int, slot: int) -> None:
        """Delete slot content, returning it to empty state."""
        self._validate_slot(slot)
        row = self._get_row(user_id, slot)
        if row is not None:
            self.session.delete(row)
            self.session.commit()
            write_log(level="INFO", module="alters", event="alter_cleared",
                      payload={"user_id": user_id, "slot": slot})

    def copy_alter(self, user_id: int, from_slot: int, to_slot: int) -> dict[str, Any]:
        """Overwrite to_slot with the full content (name + parameters) of from_slot."""
        self._validate_slot(from_slot)
        self._validate_slot(to_slot)
        src = self._get_row(user_id, from_slot)
        if src is None:
            raise ValueError(f"Source slot {from_slot} is empty — nothing to copy")
        assert src.parameters_json is not None
        params: dict[str, float] = json.loads(src.parameters_json)
        existing = self._get_row(user_id, to_slot)
        now = utc_now()
        if existing is not None:
            existing.name = src.name
            existing.parameters_json = src.parameters_json
            existing.updated_at = now
            self.session.add(existing)
        else:
            self.session.add(PersonalityAlter(
                user_id=user_id,
                slot=to_slot,
                name=src.name,
                parameters_json=src.parameters_json,
                created_at=now,
                updated_at=now,
            ))
        self.session.commit()
        write_log(level="INFO", module="alters", event="alter_copied",
                  payload={"user_id": user_id, "from_slot": from_slot, "to_slot": to_slot, "name": src.name})
        return {"slot": to_slot, "name": src.name, "parameters": params, "is_empty": False}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_row(self, user_id: int, slot: int) -> Optional[PersonalityAlter]:
        return self.session.exec(
            select(PersonalityAlter).where(
                PersonalityAlter.user_id == user_id,
                PersonalityAlter.slot == slot,
            )
        ).first()

    def _validate_slot(self, slot: int) -> None:
        if not 1 <= slot <= _MAX_SLOTS:
            raise ValueError(f"Slot must be 1–{_MAX_SLOTS}, got {slot}")

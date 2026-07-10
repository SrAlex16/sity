"""Persistent task-context state for multi-step planner tasks.

When a tool handler resolves a reusable artifact (a resource URI, a device ID,
an event ID, etc.) during a multi-step task, that value can be stored here so
the planner has it available in subsequent turns without relying on it appearing
within the limited history window.

Storage: SQLite Setting with key "task_context:{session_id}", same pattern as
spotify:previous_context in spotify_tools.py.

Lifecycle:
  - Updated by tool handlers that return task_context in ToolExecutionResult.
  - Cleared by an explicit task_context={} signal or by TTL expiry (default 30 min).
  - Injected into the planner_user_message at the start of each turn.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import Setting, utc_now
from app.trace.logger import write_log


def _key(session_id: str) -> str:
    return f"task_context:{session_id}"


def _ttl_minutes() -> int:
    from app.settings.config_loader import load_default_config
    return int(load_default_config().get("task_context", {}).get("ttl_minutes", 30))


def load_task_context(session_id: str) -> dict[str, str] | None:
    """Return the active task_context dict, or None if absent/expired."""
    ttl = _ttl_minutes()
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _key(session_id))).first()
        if row is None:
            return None
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - updated_at).total_seconds() / 60
        if age_minutes > ttl:
            _delete_row(db, row)
            write_log(
                level="INFO", module="core", event="task_context_cleared",
                payload={"session_id": session_id, "reason": "ttl_expired",
                         "age_minutes": round(age_minutes, 1)},
            )
            return None
        ctx: dict[str, str] = json.loads(row.value_json)
        return ctx if ctx else None


def save_task_context(
    session_id: str,
    updates: dict[str, str],
    *,
    trace_id: str = "",
) -> None:
    """Merge `updates` into the existing task_context for this session."""
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _key(session_id))).first()
        now = utc_now()
        if row:
            existing: dict[str, str] = json.loads(row.value_json)
            existing.update(updates)
            row.value_json = json.dumps(existing)
            row.updated_at = now
            db.add(row)
        else:
            db.add(Setting(
                key=_key(session_id),
                value_json=json.dumps(updates),
                source="task_context",
                created_at=now,
                updated_at=now,
            ))
        db.commit()

    write_log(
        level="INFO", module="core", event="task_context_updated",
        trace_id=trace_id,
        payload={"session_id": session_id, "keys": sorted(updates.keys())},
    )


def clear_task_context(
    session_id: str,
    *,
    reason: str = "explicit_close",
    trace_id: str = "",
) -> None:
    """Delete the task_context Setting for this session."""
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _key(session_id))).first()
        if row:
            _delete_row(db, row)

    write_log(
        level="INFO", module="core", event="task_context_cleared",
        trace_id=trace_id,
        payload={"session_id": session_id, "reason": reason},
    )


def _delete_row(db: Session, row: Setting) -> None:
    db.delete(row)
    db.commit()

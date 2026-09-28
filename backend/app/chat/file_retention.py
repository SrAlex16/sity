"""file_retention.py — periodic cleanup of expired FileArtifact rows and their files on disk.

Deletion rules (evaluated per row):
  - is_permanent=True → never deleted
  - expires_at IS NOT NULL → delete when expires_at < now()
  - expires_at IS NULL     → delete when created_at < (now - older_than_days) [backward compat]

The retention loop runs every hour (asyncio task → run_in_executor → Session).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import FileArtifact
from app.trace.logger import write_log

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_RETENTION_DAYS = 7
_INTERVAL_HOURS = 1


def _naive(dt: datetime) -> datetime:
    return dt if dt.tzinfo is None else dt.replace(tzinfo=None)


def delete_old_file_artifacts(db: Session, *, older_than_days: int = _RETENTION_DAYS) -> dict:
    """Delete expired FileArtifact rows and their on-disk files.

    Respects is_permanent flag and per-file expires_at when set.
    Idempotent: missing files on disk are silently skipped.
    Returns {"ok": bool, "deleted": int, "errors": list[str]}.
    """
    older_than_days = max(1, min(int(older_than_days), 365))
    now = _naive(datetime.now(timezone.utc))
    cutoff = now - timedelta(days=older_than_days)

    rows = db.exec(select(FileArtifact)).all()
    to_delete: list[FileArtifact] = []
    for row in rows:
        if row.is_permanent:
            continue
        if row.expires_at is not None:
            if _naive(row.expires_at) < now:
                to_delete.append(row)
        elif row.created_at is not None and _naive(row.created_at) < cutoff:
            to_delete.append(row)

    deleted = 0
    errors: list[str] = []

    for row in to_delete:
        try:
            path = (PROJECT_ROOT / row.rel_path).resolve()
            if path.exists() and path.is_file():
                path.unlink()
        except Exception as exc:
            errors.append(f"disk:{row.id}: {exc}")
        db.delete(row)
        deleted += 1

    if deleted:
        try:
            db.commit()
        except Exception as exc:
            errors.append(f"commit: {exc}")

    payload: dict = {"older_than_days": older_than_days, "deleted_count": deleted}
    if errors:
        payload["errors"] = errors

    write_log(
        level="INFO" if not errors else "WARN",
        module="file_retention",
        event="file_artifacts_cleaned",
        payload=payload,
    )
    return {"ok": not errors, "deleted": deleted, "errors": errors}


def _run_retention_sync() -> None:
    try:
        with Session(engine) as db:
            delete_old_file_artifacts(db)
    except Exception as exc:
        write_log(
            level="ERROR",
            module="file_retention",
            event="file_retention_error",
            payload={"error": str(exc)},
        )


async def file_retention_loop() -> None:
    """Async loop started from main.py on_startup. Runs every hour."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(_INTERVAL_HOURS * 3600)
        await loop.run_in_executor(None, _run_retention_sync)


def start_file_retention_loop(loop: asyncio.AbstractEventLoop) -> None:
    loop.create_task(file_retention_loop())
    write_log(
        level="INFO",
        module="file_retention",
        event="file_retention_started",
        payload={"interval_hours": _INTERVAL_HOURS, "retention_days": _RETENTION_DAYS},
    )

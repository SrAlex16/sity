"""file_retention.py — periodic cleanup of old FileArtifact rows and their files on disk.

Fixed retention: 7 days (same convention as ElevenLabs cleanup and captures).
Not admin-configurable for now — this is a simple default that fits the use case.
If a configurable policy is needed later, follow the audio_cleanup_days pattern.

The retention loop runs every 6 hours (same pattern as initiative/runner.py):
  asyncio task → run_in_executor → _run_retention_sync → Session → delete_old_file_artifacts
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
_INTERVAL_HOURS = 6


def delete_old_file_artifacts(db: Session, *, older_than_days: int = _RETENTION_DAYS) -> dict:
    """Delete FileArtifact rows and their files on disk older than `older_than_days` days.

    Idempotent: missing files on disk are silently skipped.
    Returns {"ok": bool, "deleted": int, "errors": list[str]}.
    """
    older_than_days = max(1, min(int(older_than_days), 365))
    # SQLite stores datetimes as naive strings — compare with naive UTC cutoff.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).replace(tzinfo=None)

    rows = db.exec(select(FileArtifact)).all()
    to_delete = [
        row for row in rows
        if row.created_at is not None
        and (row.created_at if row.created_at.tzinfo is None else row.created_at.replace(tzinfo=None)) < cutoff
    ]

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
    """Async loop started from main.py on_startup. Runs every 6 hours."""
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

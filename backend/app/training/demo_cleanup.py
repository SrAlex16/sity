"""Demo session cleanup: export raw messages to JSONL then hard-delete from DB.

Call order is guaranteed: export must succeed before any deletion is attempted.
FTS5 index is rebuilt after deletion for consistency.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_DEMO_DIR = Path(__file__).resolve().parents[3] / "datasets" / "demo_sessions"


@dataclass
class DemoCleanupResult:
    exported_count: int
    deleted_count: int
    export_path: str
    error: str | None = None


def run_demo_cleanup(
    demo_start_at_iso: str,
    *,
    demo_dir: Path | None = None,
) -> DemoCleanupResult:
    """Export all messages from demo_start_at to now, then delete them.

    Opens its own DB session so it is safe to call before the route handler
    commits its own transaction.  Deletion is skipped if export writes 0 rows.
    """
    from app.memory.db import engine
    from app.memory.models import ChatMessage
    from app.memory.search import rebuild_fts
    from sqlmodel import Session, col, select

    if demo_dir is None:
        demo_dir = _DEFAULT_DEMO_DIR

    try:
        start_dt = datetime.fromisoformat(demo_start_at_iso)
    except ValueError as exc:
        return DemoCleanupResult(
            exported_count=0, deleted_count=0, export_path="",
            error=f"Invalid demo_start_at: {exc}",
        )

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)

    end_dt = datetime.now(timezone.utc)
    ts = end_dt.strftime("%Y%m%d_%H%M%S")
    out_path = demo_dir / f"demo_{ts}.jsonl"

    with Session(engine) as session:
        messages = list(session.exec(
            select(ChatMessage)
            .where(ChatMessage.created_at >= start_dt)
            .where(ChatMessage.created_at <= end_dt)
            .order_by(col(ChatMessage.id))
        ))

        if not messages:
            log.info("demo_cleanup: no messages in [%s, %s]", start_dt.isoformat(), end_dt.isoformat())
            return DemoCleanupResult(exported_count=0, deleted_count=0, export_path=str(out_path))

        # Step 1: export — must succeed before deletion
        try:
            written = _write_jsonl(messages, out_path)
        except Exception as exc:
            log.error("demo_cleanup: export failed, skipping delete: %s", exc)
            return DemoCleanupResult(
                exported_count=0, deleted_count=0, export_path=str(out_path),
                error=f"Export failed: {exc}",
            )

        if written == 0:
            log.warning("demo_cleanup: export wrote 0 messages, skipping delete")
            return DemoCleanupResult(
                exported_count=0, deleted_count=0, export_path=str(out_path),
                error="Export wrote 0 messages",
            )

        # Step 2: delete (FTS delete trigger fires per-row automatically)
        try:
            for msg in messages:
                session.delete(msg)
            session.commit()
            deleted_count = len(messages)
        except Exception as exc:
            log.error("demo_cleanup: delete failed: %s", exc)
            return DemoCleanupResult(
                exported_count=written, deleted_count=0, export_path=str(out_path),
                error=f"Delete failed: {exc}",
            )

    # Step 3: rebuild FTS5 for full consistency after bulk delete
    rebuild_fts()

    log.info(
        "demo_cleanup: done — exported=%d deleted=%d path=%s",
        written, deleted_count, out_path,
    )
    return DemoCleanupResult(
        exported_count=written,
        deleted_count=deleted_count,
        export_path=str(out_path),
    )


def _write_jsonl(messages: list[Any], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for msg in messages:
            record = {
                "id":                  msg.id,
                "session_id":          msg.session_id,
                "role":                msg.role,
                "text":                msg.text or "",
                "created_at":          msg.created_at.isoformat() if msg.created_at else None,
                "trace_id":            msg.trace_id,
                "dataset_source":      msg.dataset_source,
                "dataset_eligible":    msg.dataset_eligible,
                "dataset_tags_json":   msg.dataset_tags_json,
                "speaker_label":       msg.speaker_label,
                "speaker_source":      msg.speaker_source,
                "speaker_confidence":  msg.speaker_confidence,
                "tone_meta":           msg.tone_meta,
            }
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
            written += 1
    return written

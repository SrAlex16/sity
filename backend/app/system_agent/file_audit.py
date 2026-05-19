from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/home/alex/projects/sity")
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "file_backups"
AUDIT_LOG_PATH = DATA_DIR / "file_audit.jsonl"


def utc_now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_path_slug(path: Path) -> str:
    text = str(path)
    text = text.replace("/", "__")
    text = text.replace("\\", "__")
    text = text.replace(":", "_")
    return text.strip("_") or "unknown"


def create_file_backup(
    path: Path,
    *,
    action: str,
    pending_action_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {
            "created": False,
            "reason": "source_missing_or_not_file",
            "backup_path": None,
        }

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    backup_name = (
        f"{utc_now_slug()}__{action}__{safe_path_slug(path)}"
    )

    if pending_action_id:
        backup_name += f"__{pending_action_id}"

    backup_name += ".bak"

    backup_path = BACKUP_DIR / backup_name

    shutil.copy2(path, backup_path)

    return {
        "created": True,
        "backup_path": str(backup_path),
        "source_path": str(path),
        "size_bytes": backup_path.stat().st_size,
    }


def append_file_audit_event(event: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        file.write("\n")


def list_file_audit_events(limit: int = 10) -> dict[str, Any]:
    try:
        if limit <= 0:
            limit = 10

        limit = min(limit, 50)

        if not AUDIT_LOG_PATH.exists():
            return {
                "ok": True,
                "events": [],
                "count": 0,
                "audit_log_path": str(AUDIT_LOG_PATH),
            }

        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        selected_lines = lines[-limit:]

        events: list[dict[str, Any]] = []

        for line in selected_lines:
            if not line.strip():
                continue

            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({
                    "ok": False,
                    "error": "audit_log_line_invalid_json",
                    "raw": line[:500],
                })

        return {
            "ok": True,
            "events": events,
            "count": len(events),
            "audit_log_path": str(AUDIT_LOG_PATH),
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error leyendo audit log de archivos: {exc}",
        }

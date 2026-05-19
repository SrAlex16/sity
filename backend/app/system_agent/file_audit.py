from __future__ import annotations

import json
import os
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


def _resolve_backup_path(backup_path_value: str) -> Path:
    backup_path = Path(backup_path_value).expanduser()

    if not backup_path.is_absolute():
        # Use only the filename to avoid double-nesting when a relative subpath is given
        backup_path = BACKUP_DIR / backup_path.name

    backup_path = backup_path.resolve()
    backup_root = BACKUP_DIR.resolve()

    if backup_path != backup_root and backup_root not in backup_path.parents:
        raise ValueError(f"Backup fuera del directorio permitido: {backup_path}")

    return backup_path


def find_audit_event_by_backup_path(backup_path_value: str) -> dict[str, Any] | None:
    try:
        backup_path = str(_resolve_backup_path(backup_path_value))

        if not AUDIT_LOG_PATH.exists():
            return None

        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()

        for line in reversed(lines):
            if not line.strip():
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            backup = event.get("backup") or {}
            if backup.get("backup_path") == backup_path:
                return event

        return None

    except Exception:
        return None


def rollback_file_change(
    *,
    backup_path: str,
    pending_action_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    try:
        resolved_backup_path = _resolve_backup_path(backup_path)

        if not resolved_backup_path.exists():
            return {
                "ok": False,
                "error": f"No existe el backup: {resolved_backup_path}",
            }

        if not resolved_backup_path.is_file():
            return {
                "ok": False,
                "error": f"El backup no es un archivo: {resolved_backup_path}",
            }

        source_event = find_audit_event_by_backup_path(str(resolved_backup_path))

        if not source_event:
            return {
                "ok": False,
                "error": "No se encontró un evento de auditoría asociado a ese backup.",
                "backup_path": str(resolved_backup_path),
            }

        target_path_value = source_event.get("path")
        if not target_path_value:
            return {
                "ok": False,
                "error": "El evento de auditoría no tiene ruta objetivo.",
                "backup_path": str(resolved_backup_path),
            }

        target_path = Path(str(target_path_value)).resolve()

        if not target_path.exists():
            return {
                "ok": False,
                "error": f"El archivo objetivo ya no existe: {target_path}",
                "backup_path": str(resolved_backup_path),
            }

        if not target_path.is_file():
            return {
                "ok": False,
                "error": f"La ruta objetivo no es un archivo: {target_path}",
                "backup_path": str(resolved_backup_path),
            }

        current_backup = create_file_backup(
            target_path,
            action="rollback_file_change_current_state",
            pending_action_id=pending_action_id,
            trace_id=trace_id,
        )

        previous_size = target_path.stat().st_size
        backup_size = resolved_backup_path.stat().st_size

        shutil.copy2(resolved_backup_path, target_path)

        append_file_audit_event({
            "action": "rollback_file_change",
            "path": str(target_path),
            "pending_action_id": pending_action_id,
            "trace_id": trace_id,
            "restored_from_backup_path": str(resolved_backup_path),
            "source_event": {
                "timestamp": source_event.get("timestamp"),
                "action": source_event.get("action"),
                "pending_action_id": source_event.get("pending_action_id"),
                "trace_id": source_event.get("trace_id"),
            },
            "previous_size_bytes": previous_size,
            "bytes_written": backup_size,
            "backup": current_backup,
            "status": "ok",
        })

        return {
            "ok": True,
            "path": str(target_path),
            "restored_from_backup_path": str(resolved_backup_path),
            "previous_size_bytes": previous_size,
            "bytes_written": backup_size,
            "backup": current_backup,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": f"Error haciendo rollback: {exc}",
        }

from __future__ import annotations

from typing import Any

from app.senses.retention import clean_old_captures, get_capture_storage_summary


def execute_capture_retention_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "clean_old_captures":
        return clean_old_captures(
            older_than_days=int(payload.get("older_than_days", 7)),
            max_files_per_type=int(payload.get("max_files_per_type", 100)),
            dry_run=bool(payload.get("dry_run", False)),
        )

    if action == "get_capture_storage_summary":
        return get_capture_storage_summary()

    return {
        "ok": False,
        "error": f"Unsupported capture retention action: {action}",
    }

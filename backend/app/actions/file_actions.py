from __future__ import annotations

from typing import Any

from app.system_agent.file_access import (
    apply_text_patch,
    list_directory,
    preview_text_patch,
    read_file,
    write_file,
)
from app.system_agent.file_audit import (
    find_latest_reversible_file_change,
    list_file_audit_events,
    rollback_file_change,
)


def execute_file_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "read_file":
        return read_file(str(payload.get("path", "")))

    if action == "list_directory":
        return list_directory(str(payload.get("path", "")))

    if action == "write_file":
        return write_file(
            path_value=str(payload.get("path", "")),
            content=str(payload.get("content", "")),
            create_parent_dirs=bool(payload.get("create_parent_dirs", False)),
            pending_action_id=payload.get("pending_action_id"),
            trace_id=payload.get("trace_id"),
        )

    if action == "preview_text_patch":
        return preview_text_patch(
            str(payload.get("path", "")),
            str(payload.get("old_text", "")),
            str(payload.get("new_text", "")),
        )

    if action == "apply_text_patch":
        return apply_text_patch(
            str(payload.get("path", "")),
            str(payload.get("old_text", "")),
            str(payload.get("new_text", "")),
            pending_action_id=payload.get("pending_action_id"),
            trace_id=payload.get("trace_id"),
        )

    if action == "list_file_changes":
        return list_file_audit_events(limit=int(payload.get("limit", 10)))

    if action == "find_latest_reversible_file_change":
        return find_latest_reversible_file_change(
            include_rollbacks=bool(payload.get("include_rollbacks", False)),
        )

    if action == "rollback_file_change":
        return rollback_file_change(
            backup_path=str(payload.get("backup_path", "")),
            pending_action_id=payload.get("pending_action_id"),
            trace_id=payload.get("trace_id"),
        )

    return {
        "ok": False,
        "error": f"Unsupported file action: {action}",
    }

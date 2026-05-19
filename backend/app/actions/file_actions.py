from __future__ import annotations

from typing import Any

from app.system_agent.file_access import list_directory, read_file, write_file


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
        )

    return {
        "ok": False,
        "error": f"Unsupported file action: {action}",
    }

import json
from pathlib import Path
from typing import Any, Optional

from app.trace.logger import LOG_DIR


def _list_log_files() -> list[Path]:
    if not LOG_DIR.exists():
        return []

    files = list(LOG_DIR.glob("app-*.jsonl")) + list(LOG_DIR.glob("audit-*.jsonl"))
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def _read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if not path.exists():
        return events

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue

            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(value, dict):
                events.append(value)

    return events


def get_recent_events(limit: int = 100) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for file_path in _list_log_files():
        events.extend(_read_jsonl_file(file_path))

    events.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return events[:limit]


def get_last_trace_id() -> Optional[str]:
    for event in get_recent_events(limit=200):
        trace_id = event.get("trace_id")
        if trace_id:
            return str(trace_id)

    return None


def get_events_by_trace_id(trace_id: str, limit: int = 200) -> list[dict[str, Any]]:
    events = [
        event
        for event in get_recent_events(limit=1000)
        if event.get("trace_id") == trace_id
    ]

    events.sort(key=lambda item: item.get("timestamp", ""))
    return events[:limit]

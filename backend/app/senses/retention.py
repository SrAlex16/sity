from __future__ import annotations

import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURES_ROOT = PROJECT_ROOT / "captures"

CAPTURE_DIRS = {
    "camera": CAPTURES_ROOT / "camera",
    "audio": CAPTURES_ROOT / "audio",
}

ALLOWED_SUFFIXES = {
    "camera": {".jpg", ".jpeg", ".png"},
    "audio": {".wav", ".mp3", ".ogg", ".m4a"},
}


def _safe_capture_files(kind: str) -> list[Path]:
    if kind not in CAPTURE_DIRS:
        return []

    root = CAPTURE_DIRS[kind].resolve()
    allowed_suffixes = ALLOWED_SUFFIXES[kind]

    if not root.exists():
        return []

    files: list[Path] = []

    for path in root.iterdir():
        resolved = path.resolve()

        if not resolved.is_file():
            continue

        if root not in resolved.parents:
            continue

        if resolved.suffix.lower() not in allowed_suffixes:
            continue

        files.append(resolved)

    return files


def clean_old_captures(
    *,
    older_than_days: int = 7,
    max_files_per_type: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    older_than_days = max(1, min(int(older_than_days), 365))
    max_files_per_type = max(1, min(int(max_files_per_type), 10000))

    now = time.time()
    cutoff = now - older_than_days * 24 * 60 * 60

    deleted: list[str] = []
    kept: list[str] = []
    errors: list[str] = []

    for kind in CAPTURE_DIRS:
        files = _safe_capture_files(kind)

        files_by_mtime_oldest_first = sorted(
            files,
            key=lambda item: item.stat().st_mtime,
        )

        files_by_mtime_newest_first = list(reversed(files_by_mtime_oldest_first))

        keep_by_count = set(files_by_mtime_newest_first[:max_files_per_type])

        for path in files_by_mtime_oldest_first:
            should_delete_by_age = path.stat().st_mtime < cutoff
            should_delete_by_count = path not in keep_by_count

            if should_delete_by_age or should_delete_by_count:
                try:
                    if not dry_run:
                        path.unlink()
                    deleted.append(str(path))
                except Exception as exc:
                    errors.append(f"{path}: {exc}")
            else:
                kept.append(str(path))

    return {
        "ok": len(errors) == 0,
        "dry_run": dry_run,
        "older_than_days": older_than_days,
        "max_files_per_type": max_files_per_type,
        "deleted_count": len(deleted),
        "kept_count": len(kept),
        "deleted": deleted,
        "errors": errors,
    }


def get_capture_storage_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "ok": True,
        "types": {},
        "total_files": 0,
        "total_bytes": 0,
    }

    for kind in CAPTURE_DIRS:
        files = _safe_capture_files(kind)
        total_bytes = sum(path.stat().st_size for path in files)

        summary["types"][kind] = {
            "files": len(files),
            "bytes": total_bytes,
            "directory": str(CAPTURE_DIRS[kind]),
        }

        summary["total_files"] += len(files)
        summary["total_bytes"] += total_bytes

    return summary

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:12]}"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_file(kind: str) -> Path:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return LOG_DIR / f"{kind}-{date}.jsonl"


def write_log(
    *,
    level: str,
    module: str,
    event: str,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    audit: bool = False,
) -> None:
    record = {
        "timestamp": utc_iso(),
        "level": level,
        "module": module,
        "event": event,
        "trace_id": trace_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "payload": payload or {},
    }

    file_path = _log_file("audit" if audit or level == "AUDIT" else "app")

    with file_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def purge_old_logs(retention_days: int = 14) -> int:
    """Delete .jsonl log files older than retention_days. Returns count of deleted files."""
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for f in LOG_DIR.glob("*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted

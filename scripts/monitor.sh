#!/usr/bin/env bash
# Real-time monitoring panel for Sity backend logs.
# Usage: ./scripts/monitor.sh [--errors-only]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export _SITY_PROJECT_ROOT="$PROJECT_ROOT"

exec python3 - "$@" << 'PYEOF'
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────────────────────
RED    = "\033[31m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

LEVEL_COLOUR = {
    "ERROR": RED,
    "WARN":  YELLOW,
    "INFO":  GREEN,
    "AUDIT": CYAN,
}

ERRORS_ONLY = "--errors-only" in sys.argv

# ── Log directory ─────────────────────────────────────────────────────────────
_project_root = Path(os.environ.get("_SITY_PROJECT_ROOT", "."))
LOG_DIR = Path(os.environ.get("SITY_LOG_DIR", str(_project_root / "data" / "logs")))

# ── Events that are interesting even at INFO level ────────────────────────────
_INTERESTING_EVENTS = {
    "user_message_received",
    "ai_call_completed",
    "ai_call_failed",
    "user_registered",
    "user_login",
    "bug_report_submitted",
    "sse_subscriber_connected",
    "sse_subscriber_disconnected",
    "turn_superseded",
    "structural_refusal_generated",
    "model_upgrade_accepted",
    "model_upgrade_rejected",
}


def _detail(rec: dict) -> str:
    """Extract a short human-readable detail string from a log record."""
    event   = rec.get("event", "")
    payload = rec.get("payload") or {}
    sid     = rec.get("session_id") or payload.get("session_id") or ""
    sid_s   = sid[:8] if sid else ""

    if event == "user_message_received":
        return f"len={payload.get('message_length', '?')}  session={sid_s}"
    if event in ("ai_call_completed", "ai_call_failed"):
        ms = payload.get("latency_ms")
        ms_s = f"{ms}ms" if ms is not None else ""
        return f"{payload.get('model', '?')}  {ms_s}  session={sid_s}"
    if event in ("user_registered", "user_login"):
        return f"user_id={payload.get('user_id', '?')}"
    if event == "bug_report_submitted":
        return f"severity={payload.get('severity', '?')}  role={payload.get('role', '?')}  id={payload.get('report_id', '?')}"
    if event == "sse_subscriber_connected":
        return f"session={sid_s}  subscribers={payload.get('subscriber_count', '?')}"
    if event == "sse_subscriber_disconnected":
        return f"session={sid_s}"
    if event == "turn_superseded":
        return f"session={sid_s}"
    if event == "structural_refusal_generated":
        return f"session={sid_s}"
    if event in ("model_upgrade_accepted", "model_upgrade_rejected"):
        return f"session={sid_s}  model={payload.get('model', '?')}"

    # Fallback: show first 100 chars of payload
    raw = json.dumps(payload, ensure_ascii=False)
    return raw[:100] + ("…" if len(raw) > 100 else "")


def _format(rec: dict) -> str | None:
    """Return a formatted line for the record, or None if it should be skipped."""
    level = rec.get("level", "INFO").upper()
    event = rec.get("event", "")
    module = rec.get("module", "")

    is_error_or_warn = level in ("ERROR", "WARN")
    is_interesting   = level == "AUDIT" or event in _INTERESTING_EVENTS

    if ERRORS_ONLY and not is_error_or_warn:
        return None
    if not ERRORS_ONLY and not is_error_or_warn and not is_interesting:
        return None

    # Parse UTC timestamp → local HH:MM:SS
    ts_raw = rec.get("timestamp", "")
    try:
        dt_utc = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        hms = dt_utc.astimezone().strftime("%H:%M:%S")
    except Exception:
        hms = ts_raw[11:19] if len(ts_raw) >= 19 else "??:??:??"

    colour = LEVEL_COLOUR.get(level, "")
    level_s = f"{colour}{BOLD}{level:<5}{RESET}"
    mod_event = f"{DIM}{module}{RESET}.{event}" if module else event
    detail = _detail(rec)

    return f"[{hms}] {level_s}  {mod_event}  {detail}"


def _today_files() -> tuple[Path, Path]:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return LOG_DIR / f"app-{date}.jsonl", LOG_DIR / f"audit-{date}.jsonl"


def _wait_for_file(path: Path) -> None:
    if not path.exists():
        print(f"{DIM}[monitor] waiting for {path.name}…{RESET}", flush=True)
        while not path.exists():
            time.sleep(1)


class FileTailer:
    """Tail a single JSONL file, yielding new lines."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None
        self._inode = None

    def _open(self) -> None:
        self._fh = self.path.open("r", encoding="utf-8", errors="replace")
        self._fh.seek(0, 2)  # jump to end
        self._inode = self.path.stat().st_ino

    def _rotated(self) -> bool:
        try:
            return self.path.stat().st_ino != self._inode
        except FileNotFoundError:
            return True

    def lines(self) -> list[str]:
        if self._fh is None:
            if not self.path.exists():
                return []
            self._open()
            return []

        if self._rotated():
            self._fh.close()
            if self.path.exists():
                self._open()
            else:
                self._fh = None
            return []

        out = []
        while True:
            line = self._fh.readline()
            if not line:
                break
            line = line.strip()
            if line:
                out.append(line)
        return out


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    mode = "errors-only" if ERRORS_ONLY else "all events"
    print(
        f"{CYAN}{BOLD}Sity monitor{RESET}  {DIM}({mode}){RESET}  "
        f"{DIM}log dir: {LOG_DIR}{RESET}",
        flush=True,
    )
    print(f"{DIM}{'─' * 72}{RESET}", flush=True)

    current_date = datetime.now(timezone.utc).date()
    app_path, audit_path = _today_files()

    # Wait for at least the app log to exist
    _wait_for_file(app_path)

    app_tailer   = FileTailer(app_path)
    audit_tailer = FileTailer(audit_path)

    try:
        while True:
            # Rotate tailers at midnight
            new_date = datetime.now(timezone.utc).date()
            if new_date != current_date:
                current_date = new_date
                app_path, audit_path = _today_files()
                app_tailer   = FileTailer(app_path)
                audit_tailer = FileTailer(audit_path)
                print(
                    f"\n{DIM}[monitor] new log files for {new_date}{RESET}",
                    flush=True,
                )

            for raw in app_tailer.lines() + audit_tailer.lines():
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                line = _format(rec)
                if line:
                    print(line, flush=True)

            time.sleep(0.15)

    except KeyboardInterrupt:
        print(f"\n{DIM}[monitor] stopped{RESET}")


if __name__ == "__main__":
    main()
PYEOF

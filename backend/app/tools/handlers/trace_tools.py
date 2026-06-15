"""Handler for read_own_trace tool.

Reads today's app log (with yesterday as fallback) and aggregates per-turn
summaries from the JSONL events, grouped by trace_id.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_LOG_DIR = _PROJECT_ROOT / "data" / "logs"
_MAX_N_RECENT = 10


def _log_path(date_str: str, log_dir: Path) -> Path:
    return log_dir / f"app-{date_str}.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return records


def _group_by_trace(records: list[dict]) -> dict[str, list[dict]]:
    by_trace: dict[str, list[dict]] = {}
    for r in records:
        tid = r.get("trace_id")
        if not tid:
            continue
        by_trace.setdefault(tid, []).append(r)
    return by_trace


def _extract_search_query(tool_call: dict) -> str | None:
    preview = tool_call.get("input_summary", {}).get("preview", "")
    if not preview:
        return None
    try:
        return str(json.loads(preview).get("query", "")) or None
    except (json.JSONDecodeError, TypeError):
        return None


def _summarize_trace(trace_id: str, events: list[dict]) -> dict[str, Any]:
    summary: dict[str, Any] = {"trace_id": trace_id}

    first_ts: str | None = None
    user_message_length: int | None = None
    history_count: int | None = None
    input_mode: str | None = None
    output_mode: str | None = None
    tool_call_names: list[str] = []
    memory_search_query: str | None = None
    total_input = 0
    total_output = 0
    tts_fragments: int | None = None

    for ev in events:
        if first_ts is None and ev.get("timestamp"):
            first_ts = ev["timestamp"]

        event = ev.get("event", "")
        payload: dict = ev.get("payload") or {}

        if event == "user_message_received":
            user_message_length = payload.get("message_length")

        elif event == "history_injected":
            history_count = payload.get("history_count")

        elif event == "voice_input":
            input_mode = payload.get("input_mode")

        elif event == "tts_decision":
            output_mode = "voice" if payload.get("should_synth") else "text"

        elif event == "ai_response_received":
            for tc in payload.get("tool_calls") or []:
                name = tc.get("name")
                if name:
                    tool_call_names.append(name)
                    if name == "search_conversation_history" and memory_search_query is None:
                        memory_search_query = _extract_search_query(tc)

        elif event == "ai_call_completed":
            total_input += int(payload.get("input_tokens") or 0)
            total_output += int(payload.get("output_tokens") or 0)

        elif event == "tts_attached":
            tts_fragments = payload.get("fragments")

    if first_ts:
        summary["timestamp"] = first_ts
    if user_message_length is not None:
        summary["user_message_length"] = user_message_length
    if history_count is not None:
        summary["history_count"] = history_count
    if input_mode:
        summary["input_mode"] = input_mode
    if output_mode:
        summary["output_mode"] = output_mode

    if tool_call_names:
        summary["tool_calls"] = list(dict.fromkeys(tool_call_names))
    memory_hit = "search_conversation_history" in tool_call_names
    summary["memory_search_performed"] = memory_hit
    if memory_hit and memory_search_query:
        summary["memory_search_query"] = memory_search_query

    if total_input or total_output:
        summary["tokens"] = {"input": total_input, "output": total_output}

    if tts_fragments is not None:
        summary["tts_fragments"] = tts_fragments

    return summary


def read_own_trace(
    trace_id: str | None = None,
    n_recent: int = 1,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Aggregate turn summaries from today's app log (yesterday as fallback)."""
    _dir = log_dir or _DEFAULT_LOG_DIR
    n_recent = max(1, min(n_recent, _MAX_N_RECENT))

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    records = _read_jsonl(_log_path(yesterday_str, _dir)) + _read_jsonl(_log_path(today_str, _dir))
    by_trace = _group_by_trace(records)

    if trace_id is not None:
        if trace_id not in by_trace:
            return {"error": f"trace_id '{trace_id}' not found in today's or yesterday's logs"}
        return _summarize_trace(trace_id, by_trace[trace_id])

    # Determine insertion order (most recent last in records → reverse for recency)
    seen: set[str] = set()
    ordered: list[str] = []
    for r in reversed(records):
        tid = r.get("trace_id")
        if tid and tid not in seen:
            seen.add(tid)
            ordered.append(tid)

    recent = ordered[:n_recent]
    if not recent:
        return {"error": "No turns found in today's or yesterday's logs"}

    summaries = [_summarize_trace(tid, by_trace[tid]) for tid in recent]
    if len(summaries) == 1:
        return summaries[0]
    return {"turns": summaries, "count": len(summaries)}


@tool_handler("read_own_trace")
def handle_read_own_trace(ctx: ToolContext) -> ToolExecutionResult:
    trace_id = ctx.tool_input.get("trace_id") or None
    n_recent = int(ctx.tool_input.get("n_recent", 1))

    result = read_own_trace(trace_id=trace_id, n_recent=n_recent)

    if "error" in result:
        msg = result["error"]
        return ToolExecutionResult(
            tool_name=ctx.tool_name,
            ok=False,
            message=msg,
            updated_parameters=[],
            raw_result={"success": False, "text": f"Error: {msg}"},
        )

    text = json.dumps(result, ensure_ascii=False, indent=2)
    return ToolExecutionResult(
        tool_name=ctx.tool_name,
        ok=True,
        message="Traza(s) leída(s).",
        updated_parameters=[],
        raw_result={"success": True, "text": text},
    )

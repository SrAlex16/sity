"""Tests for trace_tools.read_own_trace and related toolset restriction."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.tools.handlers.trace_tools import read_own_trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now_utc().strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (_now_utc() - timedelta(days=1)).strftime("%Y-%m-%d")


def _record(event: str, trace_id: str, payload: dict, ts: str | None = None) -> dict:
    return {
        "timestamp": ts or "2026-06-16T10:00:00+00:00",
        "level": "INFO",
        "module": "chat",
        "event": event,
        "trace_id": trace_id,
        "session_id": None,
        "turn_id": None,
        "payload": payload,
    }


def _minimal_turn(trace_id: str, ts: str = "2026-06-16T10:00:00+00:00") -> list[dict]:
    return [
        _record("user_message_received", trace_id, {"message_length": 20, "history_items": 0}, ts),
        _record("history_injected", trace_id,
                {"history_limit": 10, "history_count": 4, "planner_history_count": 4}, ts),
        _record("routing_decision", trace_id,
                {"provider_mode": "cloud_chat", "activated_domains": [],
                 "reasons": [], "local_ai_enabled": False, "reason": "x"}, ts),
        _record("ai_response_received", trace_id,
                {"text_length": 50, "tool_calls_count": 0, "tool_calls": []}, ts),
        _record("ai_call_completed", trace_id,
                {"provider": "anthropic", "model": "claude-haiku-4-5",
                 "latency_ms": 1200, "input_tokens": 5000, "output_tokens": 150,
                 "fallback_used": False, "error_type": None,
                 "daily_used_tokens": 5000, "daily_ratio": 0.005}, ts),
    ]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# Parsing and aggregation
# ---------------------------------------------------------------------------

def test_returns_most_recent_turn_by_default(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    turn1 = _minimal_turn("trc_aaa", ts="2026-06-16T10:00:00+00:00")
    turn2 = _minimal_turn("trc_bbb", ts="2026-06-16T11:00:00+00:00")
    _write_jsonl(logfile, turn1 + turn2)

    result = read_own_trace(log_dir=log_dir)
    assert result["trace_id"] == "trc_bbb"


def test_n_recent_returns_n_summaries(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    records: list[dict] = []
    for i, tid in enumerate(["trc_a", "trc_b", "trc_c", "trc_d"]):
        records += _minimal_turn(tid, ts=f"2026-06-16T{10 + i}:00:00+00:00")
    _write_jsonl(logfile, records)

    result = read_own_trace(n_recent=3, log_dir=log_dir)
    assert result["count"] == 3
    tids = [t["trace_id"] for t in result["turns"]]
    assert tids[0] == "trc_d"
    assert tids[1] == "trc_c"
    assert tids[2] == "trc_b"


def test_trace_id_lookup_finds_correct_trace(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    _write_jsonl(logfile,
                 _minimal_turn("trc_target", "2026-06-16T10:00:00+00:00") +
                 _minimal_turn("trc_other", "2026-06-16T11:00:00+00:00"))

    result = read_own_trace(trace_id="trc_target", log_dir=log_dir)
    assert result["trace_id"] == "trc_target"
    assert result["history_count"] == 4
    assert result["tokens"] == {"input": 5000, "output": 150}


def test_missing_trace_id_returns_error_dict(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    _write_jsonl(logfile, _minimal_turn("trc_exists"))

    result = read_own_trace(trace_id="trc_nope", log_dir=log_dir)
    assert "error" in result
    assert "trc_nope" in result["error"]


def test_no_log_file_returns_error_dict(log_dir: Path) -> None:
    result = read_own_trace(log_dir=log_dir)
    assert "error" in result


def test_n_recent_capped_at_10(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    records: list[dict] = []
    for i in range(15):
        records += _minimal_turn(f"trc_{i:02d}")
    _write_jsonl(logfile, records)

    result = read_own_trace(n_recent=20, log_dir=log_dir)
    count = result.get("count", 1)  # single result has no "count"
    assert count <= 10


def test_yesterday_fallback(log_dir: Path) -> None:
    _write_jsonl(log_dir / f"app-{_yesterday()}.jsonl", _minimal_turn("trc_old"))
    _write_jsonl(log_dir / f"app-{_today()}.jsonl", _minimal_turn("trc_new"))

    result = read_own_trace(trace_id="trc_old", log_dir=log_dir)
    assert result["trace_id"] == "trc_old"


# ---------------------------------------------------------------------------
# Memory search detection
# ---------------------------------------------------------------------------

def test_memory_search_detected(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    query_preview = json.dumps({"query": "último archivo creado", "limit": 5})
    records = _minimal_turn("trc_mem")
    for r in records:
        if r["event"] == "ai_response_received":
            r["payload"]["tool_calls_count"] = 1
            r["payload"]["tool_calls"] = [{
                "id": "toolu_xyz",
                "name": "search_conversation_history",
                "input_summary": {
                    "type": "dict", "keys": ["query", "limit"],
                    "length": 40, "redacted": False,
                    "preview": query_preview,
                },
            }]
    _write_jsonl(logfile, records)

    result = read_own_trace(trace_id="trc_mem", log_dir=log_dir)
    assert result["memory_search_performed"] is True
    assert result["memory_search_query"] == "último archivo creado"
    assert "search_conversation_history" in result["tool_calls"]


def test_no_tool_calls_no_memory_search(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    _write_jsonl(logfile, _minimal_turn("trc_plain"))

    result = read_own_trace(trace_id="trc_plain", log_dir=log_dir)
    assert result["memory_search_performed"] is False
    assert "tool_calls" not in result


# ---------------------------------------------------------------------------
# TTS and output_mode
# ---------------------------------------------------------------------------

def test_tts_fragments_and_voice_output_mode(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    records = _minimal_turn("trc_tts")
    records.append(_record("tts_decision", "trc_tts",
                           {"voice_response_mode": "always", "input_mode": "text",
                            "should_synth": True}))
    records.append(_record("tts_attached", "trc_tts",
                           {"fragments": 2, "total_chars": 300}))
    _write_jsonl(logfile, records)

    result = read_own_trace(trace_id="trc_tts", log_dir=log_dir)
    assert result["output_mode"] == "voice"
    assert result["tts_fragments"] == 2


def test_tts_not_synth_gives_text_output_mode(log_dir: Path) -> None:
    logfile = log_dir / f"app-{_today()}.jsonl"
    records = _minimal_turn("trc_text")
    records.append(_record("tts_decision", "trc_text",
                           {"voice_response_mode": "never", "input_mode": "text",
                            "should_synth": False}))
    _write_jsonl(logfile, records)

    result = read_own_trace(trace_id="trc_text", log_dir=log_dir)
    assert result["output_mode"] == "text"
    assert "tts_fragments" not in result


# ---------------------------------------------------------------------------
# Toolset restriction — read_own_trace NOT in default toolset
# ---------------------------------------------------------------------------

def test_read_own_trace_not_in_base_toolset() -> None:
    from app.cortex.tool_schemas import BASE_TOOLSET
    names = {t["name"] for t in BASE_TOOLSET}
    assert "read_own_trace" not in names


def test_read_own_trace_not_in_default_message_toolset() -> None:
    from app.chat.toolset_selector import select_toolset_for_message
    tools = select_toolset_for_message("dime qué hiciste en el último turno")
    names = {t["name"] for t in tools}
    assert "read_own_trace" not in names


def test_read_own_trace_schema_exists() -> None:
    from app.cortex.tool_schemas import READ_OWN_TRACE_TOOL, TRACE_TOOLSET
    assert READ_OWN_TRACE_TOOL["name"] == "read_own_trace"
    assert any(t["name"] == "read_own_trace" for t in TRACE_TOOLSET)

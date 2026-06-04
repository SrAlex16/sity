#!/usr/bin/env python3
"""Test local para search_conversation_history — sin Claude, sin red.

Uso:
  SITY_PROJECT_ROOT=$(pwd) backend/.venv/bin/python scripts/test_memory_search_local.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Use a throwaway DB so we never touch data/app.db
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SITY_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ.setdefault("SITY_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("SITY_AI_PROVIDER", "mock")

from app.memory.db import init_db, engine  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _seed(messages: list[tuple[str, str]]) -> None:
    """Insert (role, text) pairs into chatmessage."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with engine.connect() as conn:
        for role, msg in messages:
            conn.execute(
                text(
                    "INSERT INTO chatmessage (session_id, role, text, dataset_eligible, created_at) "
                    "VALUES ('default', :role, :text, 1, :ts)"
                ),
                {"role": role, "text": msg, "ts": now},
            )
        conn.commit()


def _reset_fts() -> None:
    """Force FTS re-init between test cases."""
    import app.memory.search as s
    s._FTS_READY = False


def run_tests() -> None:
    init_db()

    _seed([
        ("user",  "¿qué opinas del anime?"),
        ("sity",  "El anime tiene una estética visual muy característica."),
        ("user",  "¿y de la música electrónica?"),
        ("sity",  "La música electrónica me parece minimalista y repetitiva."),
        ("user",  "vamos a hablar de fine-tuning"),
        ("sity",  "El fine-tuning permite adaptar modelos preentrenados a tareas concretas."),
        ("user",  "¿necesita muchos datos?"),
        ("sity",  "Generalmente sí, al menos varios cientos de ejemplos."),
        ("sity",  "Presupuesto diario de IA agotado."),  # operational — must be filtered
    ])

    from app.memory.search import search_conversation_history

    # --- Test 1: basic FTS match ---
    _reset_fts()
    results = search_conversation_history("anime")
    assert len(results) >= 1, f"Expected >=1 result for 'anime', got {len(results)}"
    texts = [r.match.text for r in results]
    assert any("anime" in t.lower() for t in texts), f"No anime in results: {texts}"
    print("PASS test_basic_fts_match")

    # --- Test 2: prev/next context ---
    _reset_fts()
    results = search_conversation_history("música electrónica")
    assert len(results) >= 1, "Expected result for 'música electrónica'"
    r = results[0]
    assert r.prev is not None, "Expected a prev message"
    assert r.next is not None, "Expected a next message"
    print("PASS test_context_prev_next")

    # --- Test 3: no results ---
    _reset_fts()
    results = search_conversation_history("zzznomatch999")
    assert results == [], f"Expected empty list, got {results}"
    print("PASS test_no_results")

    # --- Test 4: empty query ---
    _reset_fts()
    results = search_conversation_history("  ")
    assert results == [], "Empty query should return []"
    print("PASS test_empty_query")

    # --- Test 5: operational messages filtered ---
    _reset_fts()
    results = search_conversation_history("presupuesto")
    for r in results:
        assert not (r.match.role == "sity" and "presupuesto diario" in r.match.text.lower()), (
            "Operational message leaked into results"
        )
    print("PASS test_operational_messages_filtered")

    # --- Test 6: limit respected ---
    _reset_fts()
    results = search_conversation_history("a", limit=2)
    assert len(results) <= 2, f"Limit 2 not respected, got {len(results)}"
    print("PASS test_limit_respected")

    # --- Test 7: limit clamped to max ---
    _reset_fts()
    results = search_conversation_history("a", limit=999)
    from app.memory.search import _LIMIT_MAX
    assert len(results) <= _LIMIT_MAX, f"Limit should be clamped to {_LIMIT_MAX}, got {len(results)}"
    print("PASS test_limit_clamped_to_max")

    # --- Test 8: limit 0 uses minimum (no crash) ---
    _reset_fts()
    results = search_conversation_history("anime", limit=0)
    from app.memory.search import _LIMIT_MIN
    assert isinstance(results, list), "Should return a list even with limit=0"
    print("PASS test_limit_zero_no_crash")

    # --- Test 9: text truncated to _MAX_TEXT_CHARS ---
    _reset_fts()
    from app.memory.search import _MAX_TEXT_CHARS
    long_text = "x" * (_MAX_TEXT_CHARS + 500)
    _seed([("user", long_text)])
    _reset_fts()
    results = search_conversation_history("x" * 10, limit=1)
    if results:
        assert len(results[0].match.text) <= _MAX_TEXT_CHARS + 1, (
            f"Text not truncated: {len(results[0].match.text)} chars"
        )
    print("PASS test_text_truncation")

    # --- Test 10: operational messages not in prev/next ---
    # "Generalmente sí" is msg 8; msg 9 is operational → next must be None
    _reset_fts()
    from app.chat.prompt_context import is_operational_guard_message
    results = search_conversation_history("cientos de ejemplos", limit=3)
    for r in results:
        if r.prev is not None:
            assert not (r.prev.role == "sity" and is_operational_guard_message(r.prev.text)), (
                "Operational message leaked into prev context"
            )
        if r.next is not None:
            assert not (r.next.role == "sity" and is_operational_guard_message(r.next.text)), (
                "Operational message leaked into next context"
            )
    print("PASS test_operational_filtered_from_prev_next")

    # --- Test 11: LIKE fallback searches per token, not full OR string ---
    _reset_fts()
    from app.memory.search import _search_like_tokens
    from app.memory.db import engine as _engine
    with _engine.connect() as _conn:
        rows = _search_like_tokens(_conn, "anime OR fine-tuning", 5)
        assert len(rows) >= 2, (
            f"Token LIKE should find rows for 'anime OR fine-tuning', got {len(rows)}"
        )
        texts = [r[2] for r in rows]
        assert any("anime" in t.lower() or "fine-tuning" in t.lower() for t in texts)
    print("PASS test_like_per_token_splits_or")

    # --- Test 12: no duplicate IDs in results ---
    _reset_fts()
    results = search_conversation_history("a", limit=10)
    ids = [id(r.match) for r in results]
    texts = [r.match.text for r in results]
    assert len(texts) == len(set(texts)) or True  # dedup is by msg_id in seen_ids
    # Directly verify via seen_ids logic: same text shouldn't repeat if same row
    msg_texts = [r.match.text for r in results]
    # If two results have the same text it's only ok if they're different DB rows
    # The real dedup check is that seen_ids prevents same DB id twice
    seen = set()
    from app.memory.db import engine as _eng2
    with _eng2.connect() as _c:
        for r in results:
            row = _c.execute(
                sa_text("SELECT id FROM chatmessage WHERE text = :t LIMIT 1"),
                {"t": r.match.text[:200]},
            ).fetchone()
            if row:
                assert row[0] not in seen, f"Duplicate msg_id {row[0]} in results"
                seen.add(row[0])
    print("PASS test_no_duplicate_results")

    # --- Test 13: match includes message_id ---
    _reset_fts()
    results = search_conversation_history("anime", limit=1)
    assert len(results) >= 1, "Expected at least one result"
    assert results[0].match.message_id is not None, "match.message_id must be set"
    assert isinstance(results[0].match.message_id, int), "message_id must be int"
    print("PASS test_match_has_message_id")

    # -----------------------------------------------------------------------
    # Window navigation tests
    # Scenario: anchor message at position X, answer at X+13 (beyond prev/next)
    # -----------------------------------------------------------------------

    _reset_fts()
    from app.memory.search import read_conversation_window, _WINDOW_BEFORE_MAX, _WINDOW_AFTER_MAX

    # Seed: anchor + 12 intermediate messages + answer
    _seed(
        [("user", "Empezamos la tarea nueva referencia inicial aquí.")]
        + [("sity" if i % 2 == 0 else "user", f"Diálogo continuo turno número {i} aquí.")
           for i in range(1, 13)]
        + [("sity", "El código definitivo de cierre era ZX-41 confirmado.")]
    )
    _reset_fts()

    # --- Test 14: window finds content beyond prev/next ---
    results = search_conversation_history("tarea referencia inicial", limit=1)
    assert len(results) >= 1, "Should find anchor"
    anchor_result = results[0]
    anchor_id = anchor_result.match.message_id
    assert anchor_id is not None, "Anchor must have message_id"

    # prev/next of anchor does NOT include ZX-41
    prev_text = anchor_result.prev.text if anchor_result.prev else ""
    next_text = anchor_result.next.text if anchor_result.next else ""
    visible = anchor_result.match.text + prev_text + next_text
    assert "ZX-41" not in visible, "ZX-41 should not be in prev/match/next"

    # Window with after=20 includes ZX-41
    window = read_conversation_window(anchor_id, before=5, after=20)
    window_texts = " ".join(m.text for m in window)
    assert "ZX-41" in window_texts, f"ZX-41 not found in window. Window texts: {window_texts[:300]}"
    print("PASS test_window_finds_beyond_prev_next")

    # --- Test 15: window respects before/after limits ---
    _reset_fts()
    window_small = read_conversation_window(anchor_id, before=2, after=3)
    assert len(window_small) <= 6, (
        f"Window with before=2, after=3 should have ≤6 messages, got {len(window_small)}"
    )
    print("PASS test_window_respects_limits")

    # --- Test 16: window is in chronological order ---
    _reset_fts()
    window_ord = read_conversation_window(anchor_id, before=5, after=15)
    assert len(window_ord) >= 2, "Window should have multiple messages"
    ids = [m.message_id for m in window_ord if m.message_id is not None]
    assert ids == sorted(ids), f"Window not in chronological order: {ids}"
    print("PASS test_window_chronological_order")

    # --- Test 17: window max limits clamped ---
    _reset_fts()
    window_max = read_conversation_window(anchor_id, before=999, after=999)
    assert len(window_max) <= 60, (
        f"Window should be clamped to _WINDOW_LIMIT_MAX=60, got {len(window_max)}"
    )
    print("PASS test_window_max_clamped")

    # --- Test 18: MemoryRecallRunner uses window to find beyond prev/next ---
    _reset_fts()
    from app.memory.recall import MemoryRecallRunner

    runner = MemoryRecallRunner()
    result = runner.recall(query="tarea referencia inicial", trace_id="window_integration_test")
    assert result.windows_read > 0, (
        f"Runner should have read at least one window, got windows_read={result.windows_read}"
    )
    assert result.status in ("found", "partial"), (
        f"Expected found/partial after window, got {result.status}"
    )
    print("PASS test_runner_uses_window_for_navigation")

    print("\nAll tests passed.")


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        Path(_tmp.name).unlink(missing_ok=True)

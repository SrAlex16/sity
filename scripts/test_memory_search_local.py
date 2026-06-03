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

    print("\nAll tests passed.")


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        Path(_tmp.name).unlink(missing_ok=True)

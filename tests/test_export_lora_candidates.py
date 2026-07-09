"""Tests for iter_raw_pairs() in scripts/export_sity_lora_candidates.py.

Covers: dataset_eligible=0 filtering, dataset_source exclusion, and
normal pair extraction — using a temporary SQLite DB so no app state is touched.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

# iter_raw_pairs lives in scripts/, not a package, so import via path.
import importlib.util
import sys

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_sity_lora_candidates.py"


@pytest.fixture(scope="module")
def iter_raw_pairs():
    spec = importlib.util.spec_from_file_location("export_lora", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # Register before exec so dataclass __module__ lookups resolve correctly.
    sys.modules["export_lora"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.iter_raw_pairs


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Create a minimal chatmessage table in a temp DB."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE chatmessage (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            text TEXT,
            trace_id TEXT,
            created_at TEXT,
            dataset_source TEXT,
            dataset_eligible INTEGER DEFAULT 1
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _insert(db: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(db)
    for r in rows:
        conn.execute(
            "INSERT INTO chatmessage (id, session_id, role, text, trace_id, created_at, dataset_source, dataset_eligible) "
            "VALUES (:id, :session_id, :role, :text, :trace_id, :created_at, :dataset_source, :dataset_eligible)",
            {
                "id": r["id"],
                "session_id": r.get("session_id", "default"),
                "role": r["role"],
                "text": r.get("text", ""),
                "trace_id": r.get("trace_id", ""),
                "created_at": r.get("created_at", "2026-01-01"),
                "dataset_source": r.get("dataset_source"),
                "dataset_eligible": r.get("dataset_eligible", 1),
            },
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_normal_pair_extracted(iter_raw_pairs, tmp_db):
    _insert(tmp_db, [
        {"id": 1, "role": "user", "text": "Hola"},
        {"id": 2, "role": "sity", "text": "Hola tú"},
    ])
    pairs = list(iter_raw_pairs(tmp_db, exclude_sources=set()))
    assert len(pairs) == 1
    assert pairs[0].user_text == "Hola"
    assert pairs[0].sity_text == "Hola tú"


def test_dataset_eligible_false_on_sity_excludes_pair(iter_raw_pairs, tmp_db):
    """A pair where the sity message has dataset_eligible=0 must be skipped."""
    _insert(tmp_db, [
        {"id": 1, "role": "user", "text": "Pregunta"},
        {"id": 2, "role": "sity", "text": "No he podido contactar con Claude.", "dataset_eligible": 0},
    ])
    pairs = list(iter_raw_pairs(tmp_db, exclude_sources=set()))
    assert pairs == []


def test_dataset_eligible_false_on_user_excludes_pair(iter_raw_pairs, tmp_db):
    """A pair where the user message has dataset_eligible=0 must be skipped."""
    _insert(tmp_db, [
        {"id": 1, "role": "user", "text": "Pregunta", "dataset_eligible": 0},
        {"id": 2, "role": "sity", "text": "Respuesta"},
    ])
    pairs = list(iter_raw_pairs(tmp_db, exclude_sources=set()))
    assert pairs == []


def test_dataset_eligible_mixed(iter_raw_pairs, tmp_db):
    """Only the eligible pair is returned when mixed pairs are present."""
    _insert(tmp_db, [
        {"id": 1, "role": "user", "text": "Buena"},
        {"id": 2, "role": "sity", "text": "Respuesta buena"},
        {"id": 3, "role": "user", "text": "Mala"},
        {"id": 4, "role": "sity", "text": "Error guardado", "dataset_eligible": 0},
    ])
    pairs = list(iter_raw_pairs(tmp_db, exclude_sources=set()))
    assert len(pairs) == 1
    assert pairs[0].sity_text == "Respuesta buena"


def test_exclude_source_still_works(iter_raw_pairs, tmp_db):
    _insert(tmp_db, [
        {"id": 1, "role": "user", "text": "Demo", "dataset_source": "demo_session"},
        {"id": 2, "role": "sity", "text": "Demo resp", "dataset_source": "demo_session"},
    ])
    pairs = list(iter_raw_pairs(tmp_db))  # default excludes demo_session
    assert pairs == []

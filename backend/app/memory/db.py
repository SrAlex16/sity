import os
from pathlib import Path
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine

from app.trace.logger import write_log


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "app.db"

# Allow test suites (and other callers) to redirect the DB to a separate file
# so tests never pollute the development data/app.db.
# Usage: SITY_DB_URL=sqlite:////tmp/sity_pytest_test.db
_DB_URL: str = os.environ.get("SITY_DB_URL") or f"sqlite:///{DB_PATH}"

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    _DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def _configure_sqlite() -> None:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=5000"))
        conn.commit()


def _migrate_chatmessage() -> None:
    """Add metadata columns to chatmessage if absent (idempotent ALTER TABLE)."""
    new_columns = [
        ("speaker_id",                  "TEXT"),
        ("speaker_label",               "TEXT"),
        ("speaker_source",              "TEXT"),
        ("speaker_confidence",          "REAL"),
        ("identity_evidence_json",      "TEXT"),
        ("dataset_source",              "TEXT"),
        ("dataset_eligible",            "INTEGER NOT NULL DEFAULT 1"),
        ("dataset_tags_json",           "TEXT"),
        ("input_mode",                  "TEXT NOT NULL DEFAULT 'text'"),
        ("voice_transcript_original",   "TEXT"),
        ("edit_distance_pct",           "REAL"),
        ("output_mode",                 "TEXT NOT NULL DEFAULT 'text'"),
        ("tts_fragments",               "INTEGER"),
        ("audio_filename",              "TEXT"),
        ("source_channel",              "TEXT NOT NULL DEFAULT 'web'"),
    ]
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(chatmessage)"))
        existing = {row[1] for row in result.fetchall()}
        if not existing:
            return  # table not yet created; create_all handles the full schema
        added: list[str] = []
        for col_name, col_type in new_columns:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE chatmessage ADD COLUMN {col_name} {col_type}"))
                added.append(col_name)
        conn.commit()
    if added:
        write_log(level="INFO", module="memory", event="db_migration_applied",
                  payload={"added_columns": added})


def init_db() -> None:
    import app.memory.models as _models  # noqa: F401 — registers tables in SQLModel.metadata
    try:
        _configure_sqlite()
        SQLModel.metadata.create_all(engine)
        _migrate_chatmessage()
    except Exception as exc:
        write_log(level="WARN", module="memory", event="db_initialized",
                  payload={"ok": False, "reason": str(exc)[:200]})
        raise
    write_log(level="INFO", module="memory", event="db_initialized", payload={"ok": True})


def get_session():
    with Session(engine) as session:
        yield session

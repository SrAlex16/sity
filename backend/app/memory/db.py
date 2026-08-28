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
    connect_args={"check_same_thread": False, "timeout": 10},
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


def _migrate_user() -> None:
    """Add display_name column to user table if absent (idempotent ALTER TABLE)."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(user)"))
        existing = {row[1] for row in result.fetchall()}
        if not existing:
            return
        if "display_name" not in existing:
            conn.execute(text("ALTER TABLE user ADD COLUMN display_name TEXT"))
            conn.commit()
            write_log(level="INFO", module="memory", event="db_migration_applied",
                      payload={"added_columns": ["display_name"], "table": "user"})


def _migrate_setting() -> None:
    """Convert Setting from (key UNIQUE) to (key, session_id UNIQUE) composite key.

    SQLite cannot DROP or ALTER constraints, so we rebuild the table.
    All existing rows (global personality/voice) get session_id=NULL (global fallback).
    This migration is idempotent: if session_id already exists the function returns early.
    """
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(setting)"))
        cols = {row[1] for row in result.fetchall()}
        if not cols:
            return  # table not yet created; create_all handles full schema
        if "session_id" in cols:
            return  # already migrated

        conn.execute(text("""
            CREATE TABLE setting_new (
                id      INTEGER PRIMARY KEY,
                key     TEXT    NOT NULL,
                value_json TEXT NOT NULL,
                source  TEXT    NOT NULL DEFAULT 'default',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                session_id TEXT DEFAULT NULL,
                CONSTRAINT uq_setting_key_session UNIQUE (key, session_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO setting_new (id, key, value_json, source, created_at, updated_at, session_id)
            SELECT id, key, value_json, source, created_at, updated_at, NULL
            FROM setting
        """))
        conn.execute(text("DROP TABLE setting"))
        conn.execute(text("ALTER TABLE setting_new RENAME TO setting"))
        conn.execute(text("CREATE INDEX ix_setting_key ON setting (key)"))
        conn.execute(text("CREATE INDEX ix_setting_session_id ON setting (session_id)"))
        conn.commit()

    write_log(level="INFO", module="memory", event="db_migration_applied",
              payload={"table": "setting", "added_columns": ["session_id"],
                       "constraint_change": "key_unique → (key, session_id)_composite"})


def _migrate_userachievement() -> None:
    """Ensure userachievement table exists. create_all handles new deployments.

    No column-level migration needed — entirely new table added in v0.9.
    """
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(userachievement)"))
        if not result.fetchall():
            return  # not yet created; create_all handles full schema
    # Table exists — nothing to migrate


def _migrate_social_reflection() -> None:
    """Ensure socialreflection table and its profile_id index exist.

    create_all handles the table itself for new deployments. This function
    is a no-op if the table was already created; it only logs on first creation.
    No column-level migration needed — this is an entirely new table.
    """
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(socialreflection)"))
        cols = {row[1] for row in result.fetchall()}
        if not cols:
            return  # table not yet created; create_all handles the full schema
    # Table exists — nothing to migrate


def _verify_encryption_key(session: Session) -> None:
    """Fail fast at startup if SITY_ENCRYPTION_KEY cannot decrypt existing UserIntegration rows.

    Catches key rotation or misconfiguration before any user request fails with a
    cryptic error. Skips the check when the table is empty (first deploy, no rows yet).
    """
    from sqlmodel import select
    from app.memory.models import UserIntegration
    from app.auth.encryption import decrypt_str

    row = session.exec(select(UserIntegration)).first()
    if row is None:
        return
    try:
        decrypt_str(row.encrypted_credentials)
    except ValueError as exc:
        raise RuntimeError(
            "SITY_ENCRYPTION_KEY no coincide con los datos cifrados existentes en "
            "UserIntegration — revisa el .env. El backend no puede arrancar con una "
            "clave incorrecta o rotada."
        ) from exc


def init_db() -> None:
    import app.memory.models as _models  # noqa: F401 — registers tables in SQLModel.metadata
    try:
        _configure_sqlite()
        SQLModel.metadata.create_all(engine)
        _migrate_chatmessage()
        _migrate_user()
        _migrate_setting()
        _migrate_social_reflection()
        _migrate_userachievement()
        # Set up FTS5 at startup so worker threads never contend on first-time setup.
        from app.memory.search import _setup_fts
        _setup_fts()
        with Session(engine) as session:
            _verify_encryption_key(session)
    except Exception as exc:
        write_log(level="WARN", module="memory", event="db_initialized",
                  payload={"ok": False, "reason": str(exc)[:200]})
        raise
    write_log(level="INFO", module="memory", event="db_initialized", payload={"ok": True})


def get_session():
    with Session(engine) as session:
        yield session

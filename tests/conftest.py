from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("SITY_PROJECT_ROOT", str(ROOT))
os.environ.setdefault("SITY_AI_PROVIDER", "mock")

# Redirect the DB to a pytest-local file so tests NEVER write to data/app.db.
# Must be set before app.memory.db is imported for the first time (module-level
# import creates the engine singleton immediately from SITY_DB_URL or the
# hardcoded fallback path).
_TEST_DB_PATH = ROOT / "tests" / ".pytest_test.db"
os.environ.setdefault("SITY_DB_URL", f"sqlite:///{_TEST_DB_PATH}")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def init_database() -> None:
    """Initialize the test SQLite DB once per session (idempotent).

    Safety net: asserts that we are NOT connected to data/app.db so a
    misconfigured environment fails loudly instead of silently polluting
    the development database.
    """
    from app.memory.db import engine, init_db  # imported here so env is already set

    assert "data/app.db" not in str(engine.url), (
        f"BUG: pytest is connected to the production database: {engine.url!r}. "
        "SITY_DB_URL must be set before app.memory.db is imported. "
        "Check that conftest.py runs before any test module imports app.memory.db."
    )
    init_db()


@pytest.fixture
def db_session():
    """Open a DB session against the test database.

    Expires all pending actions before each test so tool-confirmation tests
    start from a clean slate without interfering with each other.
    """
    from sqlmodel import Session, select
    from app.memory.db import engine
    from app.memory.models import PendingAction

    with Session(engine) as session:
        for action in session.exec(
            select(PendingAction).where(PendingAction.status == "pending")
        ):
            action.status = "expired"
            session.add(action)
        session.commit()
        yield session

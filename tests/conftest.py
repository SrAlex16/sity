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

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def init_database() -> None:
    """Initialize the SQLite DB once per session (idempotent)."""
    from app.memory.db import init_db
    init_db()


@pytest.fixture
def db_session():
    """Open a DB session and expire all pending actions before the test."""
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

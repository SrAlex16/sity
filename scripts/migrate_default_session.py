#!/usr/bin/env python3
"""Migrate session_id="default" rows to real user session IDs.

Run ONCE after deploying Fase 2.  Idempotent: safe to re-run if interrupted.

Strategy:
  - ChatMessage / ChatSession rows with session_id="default" belong to the
    first Admin (the only user that could have been chatting before Fase 2).
  - Migration target: session_id="user:{admin_id}"
  - Rows that already have a real session_id are left untouched.

Usage (from project root, with the backend venv active):
    python scripts/migrate_default_session.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os
os.environ.setdefault("SITY_PROJECT_ROOT", str(ROOT))

from sqlmodel import Session, col, select, text

from app.memory.db import engine, init_db
from app.memory.models import ChatMessage, ChatSession, User


def _find_admin(session: Session) -> User | None:
    return session.exec(select(User).where(User.role == "admin")).first()


def migrate(dry_run: bool = False) -> None:
    init_db()

    with Session(engine) as session:
        admin = _find_admin(session)
        if admin is None:
            print("No admin user found — nothing to migrate.")
            return

        assert admin.id is not None
        target_session_id = f"user:{admin.id}"
        print(f"Admin: id={admin.id}, email={admin.email}")
        print(f"Migrating session_id='default' → '{target_session_id}'")

        # Count rows to migrate
        msg_count = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == "default")
        ).all()
        print(f"ChatMessage rows to migrate: {len(msg_count)}")

        chat_sessions = session.exec(
            select(ChatSession).where(ChatSession.id == "default")
        ).all()
        print(f"ChatSession rows to migrate: {len(chat_sessions)}")

        if dry_run:
            print("Dry run — no changes written.")
            return

        # Ensure target ChatSession exists
        target_cs = session.get(ChatSession, target_session_id)
        if target_cs is None:
            # Copy metadata from "default" if it exists
            src_cs = session.get(ChatSession, "default")
            target_cs = ChatSession(
                id=target_session_id,
                updated_at=src_cs.updated_at if src_cs else None,
            )
            session.add(target_cs)
            session.flush()
            print(f"Created ChatSession '{target_session_id}'")

        # Migrate ChatMessage rows
        migrated = 0
        for msg in msg_count:
            msg.session_id = target_session_id
            session.add(msg)
            migrated += 1

        # Delete old "default" ChatSession (after messages are moved)
        for cs in chat_sessions:
            session.delete(cs)

        session.commit()
        print(f"Migrated {migrated} ChatMessage rows.")
        print(f"Deleted {len(chat_sessions)} 'default' ChatSession row(s).")
        print("Migration complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)

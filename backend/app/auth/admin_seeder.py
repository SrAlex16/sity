"""Seed the single Admin account at startup from env vars.

Set SITY_ADMIN_EMAIL + SITY_ADMIN_PASSWORD in .env or environment.
If either var is missing, no admin is seeded (safe — the system works
without one, and access can be added later by setting the vars and
restarting).

The seed is idempotent: if an admin row already exists it is never
touched. There is intentionally no mechanism to promote a regular User
to Admin or to create a second Admin row — Admin is a single fixed
identity (Alex).
"""

import os

from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import User
from app.auth.hashing import hash_password
from app.trace.logger import write_log


def seed_admin() -> None:
    email = os.environ.get("SITY_ADMIN_EMAIL", "").strip()
    password = os.environ.get("SITY_ADMIN_PASSWORD", "").strip()

    if not email or not password:
        return

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.role == "admin")).first()
        if existing:
            # Backfill display_name for existing admin installs that predate the field.
            if existing.display_name is None:
                existing.display_name = "Alex"
                session.add(existing)
                session.commit()
            return

        admin = User(
            email=email,
            password_hash=hash_password(password),
            role="admin",
            display_name="Alex",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)

    write_log(
        level="AUDIT",
        module="auth",
        event="admin_seeded",
        payload={"user_id": admin.id},
        audit=True,
    )

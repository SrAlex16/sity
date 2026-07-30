"""Shared test utilities — not pytest fixtures, just plain functions."""
from __future__ import annotations

import json
from typing import Any


def make_admin_token() -> str:
    """Return a JWT for a test admin user, creating the DB row if needed."""
    from sqlmodel import Session, select
    from app.memory.db import engine
    from app.memory.models import User
    from app.auth.hashing import hash_password
    from app.auth.jwt_utils import create_token

    _ADMIN_EMAIL = "_pytest_admin@sity-test.invalid"
    with Session(engine) as session:
        admin = session.exec(select(User).where(User.email == _ADMIN_EMAIL)).first()
        if not admin:
            admin = User(
                email=_ADMIN_EMAIL,
                password_hash=hash_password("AdminTest1"),
                role="admin",
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)
        return create_token(admin.id, "admin")


def make_user_token() -> str:
    """Return a JWT for a throw-away regular user (non-admin)."""
    import uuid
    from sqlmodel import Session
    from app.memory.db import engine
    from app.memory.models import User
    from app.auth.hashing import hash_password
    from app.auth.jwt_utils import create_token

    email = f"_pytest_user_{uuid.uuid4().hex[:8]}@sity-test.invalid"
    with Session(engine) as session:
        user = User(
            email=email,
            password_hash=hash_password("UserTest1"),
            role="user",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return create_token(user.id, "user")


def chat_post_and_drain(client: Any, message: str, **kwargs: Any) -> dict[str, Any]:
    """POST /chat/message (202) then drain /chat/stream until done.

    Returns the response-data dict from the 'response' SSE event,
    or {} if no response event was emitted (e.g. error path).
    """
    resp = client.post("/chat/message", json={"message": message, **kwargs})
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    turn_id = resp.json()["turn_id"]
    return drain_chat_stream(client, turn_id)


def drain_chat_stream(client: Any, turn_id: str) -> dict[str, Any]:
    """Drain /chat/stream/{turn_id} and return the response-data dict."""
    final: dict[str, Any] = {}
    with client.stream("GET", f"/chat/stream/{turn_id}") as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev: dict[str, Any] = json.loads(line[6:])
            except Exception:
                continue
            if ev.get("type") == "response":
                final = ev.get("data") or {}
            if ev.get("type") in ("done", "error", "cancelled"):
                break
    return final

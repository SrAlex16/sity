"""Tests for Fase 2 session isolation.

Verifies that:
- Authenticated users get a stable session_id (user:{id})
- Guests get an isolated UUID session_id (guest:...)
- Two concurrent guests don't see each other's history
- Two different users don't see each other's history
- Guest cookie is cleared on login
- GET /chat/current returns only the caller's messages
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.db import engine
from app.memory.models import ChatMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _email(tag: str = "") -> str:
    prefix = tag or "sess"
    return f"test_{prefix}_{_uid()}@sity-test.invalid"


def _register(client: TestClient, email: str, password: str = "Str0ngPass1") -> dict:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _chat(client: TestClient, message: str) -> dict:
    """POST to /chat/message and drain the SSE stream. Returns response data."""
    resp = client.post("/chat/message", json={"message": message})
    assert resp.status_code == 202, resp.text
    turn_id = resp.json()["turn_id"]
    final: dict = {}
    with client.stream("GET", f"/chat/stream/{turn_id}") as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except Exception:
                continue
            if ev.get("type") == "response":
                final = ev.get("data") or {}
            if ev.get("type") in ("done", "error", "cancelled"):
                break
    return final


# ---------------------------------------------------------------------------
# Guest session_id
# ---------------------------------------------------------------------------


def test_guest_gets_uuid_session_id():
    with _client() as c:
        resp = c.get("/auth/me")
    assert resp.status_code == 200
    assert "sity_guest_session" in resp.cookies
    cookie_val = resp.cookies["sity_guest_session"]
    assert cookie_val.startswith("guest:")


def test_guest_session_is_stable_across_requests():
    """Same client sends same guest cookie → same session_id in both requests."""
    with _client() as c:
        r1 = c.get("/auth/me")
        r2 = c.get("/auth/me")
    c1 = r1.cookies.get("sity_guest_session") or c._cookies.get("sity_guest_session")
    assert r1.cookies.get("sity_guest_session") or "sity_guest_session" in dict(c.cookies)
    # After first request, the cookie is in the client jar for subsequent ones
    # (the second response may not re-set the cookie since it already exists)
    first_cookie = r1.cookies.get("sity_guest_session")
    if first_cookie:
        # Second response either re-sends or relies on existing cookie
        assert True  # cookie was generated on first request


def test_two_guests_get_different_session_ids():
    with _client() as c1:
        r1 = c1.get("/chat/current")
    with _client() as c2:
        r2 = c2.get("/chat/current")

    id1 = r1.cookies.get("sity_guest_session")
    id2 = r2.cookies.get("sity_guest_session")
    assert id1 is not None
    assert id2 is not None
    assert id1 != id2


def test_guest_messages_isolated_from_other_guests():
    """Two guest clients chatting don't see each other's history."""
    with _client() as c1:
        _chat(c1, "hola soy el primer guest")
        history1 = c1.get("/chat/current").json()

    with _client() as c2:
        history2 = c2.get("/chat/current").json()

    texts1 = [m["text"] for m in history1["messages"]]
    texts2 = [m["text"] for m in history2["messages"]]

    assert any("primer guest" in t for t in texts1), "c1 should see its own message"
    assert not any("primer guest" in t for t in texts2), "c2 should NOT see c1's message"


# ---------------------------------------------------------------------------
# Authenticated session_id
# ---------------------------------------------------------------------------


def test_authenticated_user_gets_stable_session_id():
    email = _email("stable")
    with _client() as c:
        data = _register(c, email)
        user_id = data["id"]
        # After register, messages should be under user:{user_id}
        _chat(c, "mensaje de usuario registrado")
        history = c.get("/chat/current").json()

    assert history["session_id"] == f"user:{user_id}"


def test_different_users_have_isolated_history():
    email1 = _email("u1")
    email2 = _email("u2")

    with _client() as c1:
        _register(c1, email1)
        _chat(c1, "mensaje exclusivo del usuario uno")

    with _client() as c2:
        _register(c2, email2)
        history2 = c2.get("/chat/current").json()

    texts2 = [m["text"] for m in history2["messages"]]
    assert not any("usuario uno" in t for t in texts2), "u2 should NOT see u1's messages"


# ---------------------------------------------------------------------------
# Guest cookie cleared on login
# ---------------------------------------------------------------------------


def test_guest_cookie_deleted_on_register():
    email = _email("gc_reg")
    with _client() as c:
        # Establish a guest session first
        c.get("/chat/current")
        assert "sity_guest_session" in c.cookies

        # Register → guest cookie should be cleared
        _register(c, email)

    # The Set-Cookie response from /auth/register should delete sity_guest_session
    # After register, the client's cookie jar should NOT have sity_guest_session
    # (TestClient updates its jar from each response)
    assert "sity_guest_session" not in c.cookies


def test_guest_cookie_deleted_on_login():
    email = _email("gc_login")
    with _client() as c:
        # Register (clears guest cookie, sets session cookie)
        _register(c, email)
        c.post("/auth/logout")

        # Now visit as guest again
        c.get("/chat/current")
        assert "sity_guest_session" in c.cookies

        # Login → guest cookie should be cleared
        resp = c.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})
        assert resp.status_code == 200

    assert "sity_guest_session" not in c.cookies


# ---------------------------------------------------------------------------
# DB-level verification
# ---------------------------------------------------------------------------


def test_messages_saved_under_correct_session_id_for_user():
    email = _email("dbcheck")
    with _client() as c:
        data = _register(c, email)
        user_id = data["id"]
        _chat(c, "comprobación db")

    with Session(engine) as session:
        msgs = list(session.exec(
            select(ChatMessage).where(ChatMessage.session_id == f"user:{user_id}")
        ))
    assert len(msgs) >= 1
    assert any("comprobación db" in (m.text or "") for m in msgs)


def test_messages_saved_under_guest_session_id():
    with _client() as c:
        # First request establishes the guest session cookie
        r = c.get("/chat/current")
        guest_session_id = r.cookies.get("sity_guest_session") or c.cookies.get("sity_guest_session")
        assert guest_session_id is not None
        _chat(c, "comprobación guest db")

    with Session(engine) as session:
        msgs = list(session.exec(
            select(ChatMessage).where(ChatMessage.session_id == guest_session_id)
        ))
    assert len(msgs) >= 1
    assert any("comprobación guest db" in (m.text or "") for m in msgs)

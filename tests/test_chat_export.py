"""Tests for GET /chat/export."""
from __future__ import annotations

import json
import uuid as _uuid_mod

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.memory.db import engine
from app.memory.models import ChatMessage


def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _register_and_login(client: TestClient) -> tuple[str, int]:
    email = f"exp_{_uid()}@sity-test.invalid"
    resp = client.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    return resp.cookies["sity_session"], resp.json()["id"]


def _insert_messages(session_id: str, count: int = 3) -> list[str]:
    texts = [f"Mensaje {i}" for i in range(count)]
    with Session(engine) as db:
        for i, text in enumerate(texts):
            role = "user" if i % 2 == 0 else "assistant"
            db.add(ChatMessage(session_id=session_id, role=role, text=text, trace_id=f"tr_{_uid()}"))
        db.commit()
    return texts


# ---------------------------------------------------------------------------
# GET /chat/export — happy path
# ---------------------------------------------------------------------------

class TestChatExport:
    def test_returns_200_with_json_attachment(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)

        resp = client.get("/chat/export", cookies={"sity_session": cookie})

        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        assert 'attachment' in resp.headers.get("content-disposition", "")
        assert "sity-conversacion.json" in resp.headers.get("content-disposition", "")

    def test_body_is_valid_json_with_expected_keys(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)

        resp = client.get("/chat/export", cookies={"sity_session": cookie})

        data = resp.json()
        assert "exported_at" in data
        assert "session_id" in data
        assert "messages" in data
        assert isinstance(data["messages"], list)

    def test_messages_include_inserted_rows(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        texts = _insert_messages(session_id, count=3)

        resp = client.get("/chat/export", cookies={"sity_session": cookie})

        data = resp.json()
        exported_texts = [m["text"] for m in data["messages"]]
        for text in texts:
            assert text in exported_texts

    def test_message_items_have_role_text_created_at(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        _insert_messages(session_id, count=2)

        resp = client.get("/chat/export", cookies={"sity_session": cookie})

        for msg in resp.json()["messages"]:
            assert "role" in msg
            assert "text" in msg
            assert "created_at" in msg

    def test_empty_history_returns_empty_list(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, _ = _register_and_login(client)

        resp = client.get("/chat/export", cookies={"sity_session": cookie})

        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    # ---------------------------------------------------------------------------
    # Access control
    # ---------------------------------------------------------------------------

    def test_guest_returns_401(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/chat/export")
        assert resp.status_code == 401

    def test_session_id_matches_user(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)

        resp = client.get("/chat/export", cookies={"sity_session": cookie})

        assert resp.json()["session_id"] == f"user:{user_id}"

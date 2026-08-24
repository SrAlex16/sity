"""Tests for the shared conversation feature.

Coverage:
- POST /chat/share: happy path returns share_id + url + expires_at
- POST /chat/share: guest gets 401
- GET /shared/{id}: returns snapshot with filtered fields (role, text, created_at only)
- GET /shared/{id}: snapshot is immutable — new messages after sharing are NOT included
- GET /shared/{id}: expired link returns 410
- GET /shared/{id}: revoked link returns 410
- GET /shared/{id}: max_views limit respected
- GET /shared/{id}: no sensitive metadata (session_id, tone_meta, speaker_id, etc.)
- DELETE /chat/share/{id}: owner can revoke; link stops working immediately
- DELETE /chat/share/{id}: non-owner gets 404
- DELETE /chat/share/{id}: guest gets 401
- GET /chat/share: returns own links only (isolation)
- GET /chat/share: guest gets 401
- GET /chat/share: includes revoked links with is_active=False
- GET /chat/share: includes expired links with is_active=False
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.memory.db import engine
from app.memory.models import ChatMessage, SharedConversation, utc_now


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import uuid as _uuid_mod


def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _email() -> str:
    return f"share_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register_and_login(client: TestClient) -> tuple[str, int]:
    resp = client.post("/auth/register", json={"email": _email(), "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies["sity_session"]
    return cookie, resp.json()["id"]


def _add_messages(session_id: str, pairs: list[tuple[str, str]]) -> None:
    """Insert ChatMessage rows directly into the test DB."""
    with Session(engine) as db:
        for role, text in pairs:
            db.add(ChatMessage(session_id=session_id, role=role, text=text))
        db.commit()


# ---------------------------------------------------------------------------
# POST /chat/share
# ---------------------------------------------------------------------------

class TestCreateShare:
    def test_happy_path_returns_share_id_and_url(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        _add_messages(session_id, [("user", "Hola"), ("sity", "Hola, ¿qué tal?")])

        resp = client.post("/chat/share", cookies={"sity_session": cookie})

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "share_id" in body
        assert "url" in body
        assert "/shared/" in body["url"]
        assert body["share_id"] in body["url"]
        assert "expires_at" in body

    def test_guest_gets_401(self) -> None:
        client = _client()
        resp = client.post("/chat/share")
        assert resp.status_code == 401

    def test_empty_conversation_allowed(self) -> None:
        client = _client()
        cookie, _ = _register_and_login(client)
        resp = client.post("/chat/share", cookies={"sity_session": cookie})
        assert resp.status_code == 201
        body = resp.json()
        # Retrieve the share — should return 0 messages, not error
        share_id = body["share_id"]
        get_resp = client.get(f"/shared/{share_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["messages"] == []


# ---------------------------------------------------------------------------
# GET /shared/{share_id}
# ---------------------------------------------------------------------------

class TestGetShared:
    def _create_share(self, client: TestClient, cookie: str) -> str:
        resp = client.post("/chat/share", cookies={"sity_session": cookie})
        assert resp.status_code == 201, resp.text
        return resp.json()["share_id"]

    def test_returns_snapshot_with_role_text_created_at(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        _add_messages(session_id, [("user", "Uno"), ("sity", "Dos")])

        share_id = self._create_share(client, cookie)
        resp = client.get(f"/shared/{share_id}")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        messages = body["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["text"] == "Uno"
        assert "created_at" in messages[0]

    def test_snapshot_immutable_new_messages_not_included(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        _add_messages(session_id, [("user", "Antes")])

        share_id = self._create_share(client, cookie)

        # Add more messages AFTER sharing
        _add_messages(session_id, [("sity", "Después")])

        resp = client.get(f"/shared/{share_id}")
        assert resp.status_code == 200
        texts = [m["text"] for m in resp.json()["messages"]]
        assert "Antes" in texts
        assert "Después" not in texts

    def test_expired_link_returns_410(self) -> None:
        share_id = _uuid_mod.uuid4().hex
        past = utc_now() - timedelta(seconds=1)
        with Session(engine) as db:
            db.add(SharedConversation(
                id=share_id,
                session_id="user:999",
                snapshot_json="[]",
                expires_at=past,
            ))
            db.commit()

        client = _client()
        resp = client.get(f"/shared/{share_id}")
        assert resp.status_code == 410

    def test_revoked_link_returns_410(self) -> None:
        share_id = _uuid_mod.uuid4().hex
        future = utc_now() + timedelta(days=7)
        with Session(engine) as db:
            db.add(SharedConversation(
                id=share_id,
                session_id="user:999",
                snapshot_json="[]",
                expires_at=future,
                revoked_at=utc_now(),
            ))
            db.commit()

        client = _client()
        resp = client.get(f"/shared/{share_id}")
        assert resp.status_code == 410

    def test_max_views_limit_respected(self) -> None:
        share_id = _uuid_mod.uuid4().hex
        future = utc_now() + timedelta(days=7)
        with Session(engine) as db:
            db.add(SharedConversation(
                id=share_id,
                session_id="user:999",
                snapshot_json='[{"role":"user","text":"test","created_at":"2026-01-01T00:00:00+00:00"}]',
                expires_at=future,
                max_views=2,
                view_count=0,
            ))
            db.commit()

        client = _client()
        # First two views succeed
        assert client.get(f"/shared/{share_id}").status_code == 200
        assert client.get(f"/shared/{share_id}").status_code == 200
        # Third view exceeds max_views
        assert client.get(f"/shared/{share_id}").status_code == 410

    def test_view_count_increments(self) -> None:
        share_id = _uuid_mod.uuid4().hex
        future = utc_now() + timedelta(days=7)
        with Session(engine) as db:
            db.add(SharedConversation(
                id=share_id,
                session_id="user:999",
                snapshot_json="[]",
                expires_at=future,
            ))
            db.commit()

        client = _client()
        client.get(f"/shared/{share_id}")
        client.get(f"/shared/{share_id}")

        with Session(engine) as db:
            row = db.get(SharedConversation, share_id)
            assert row.view_count == 2

    def test_no_sensitive_metadata_in_response(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        _add_messages(session_id, [("user", "Secreto")])

        share_id = self._create_share(client, cookie)
        resp = client.get(f"/shared/{share_id}")

        body_str = json.dumps(resp.json())
        assert session_id not in body_str
        assert "speaker_id" not in body_str
        assert "tone_meta" not in body_str
        assert "identity_evidence" not in body_str
        assert "dataset_source" not in body_str

    def test_nonexistent_share_id_returns_410(self) -> None:
        client = _client()
        resp = client.get("/shared/00000000000000000000000000000000")
        assert resp.status_code == 410


# ---------------------------------------------------------------------------
# DELETE /chat/share/{share_id}
# ---------------------------------------------------------------------------

class TestRevokeShare:
    def _create_share(self, client: TestClient, cookie: str) -> str:
        resp = client.post("/chat/share", cookies={"sity_session": cookie})
        assert resp.status_code == 201
        return resp.json()["share_id"]

    def test_owner_can_revoke_and_link_stops_working(self) -> None:
        client = _client()
        cookie, _ = _register_and_login(client)

        share_id = self._create_share(client, cookie)

        # Link works before revocation
        assert client.get(f"/shared/{share_id}").status_code == 200

        revoke_resp = client.delete(
            f"/chat/share/{share_id}", cookies={"sity_session": cookie}
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["ok"] is True

        # Link no longer works after revocation
        assert client.get(f"/shared/{share_id}").status_code == 410

    def test_non_owner_gets_404(self) -> None:
        client = _client()
        cookie_owner, _ = _register_and_login(client)
        cookie_other, _ = _register_and_login(client)

        share_id = self._create_share(client, cookie_owner)

        resp = client.delete(
            f"/chat/share/{share_id}", cookies={"sity_session": cookie_other}
        )
        assert resp.status_code == 404

    def test_guest_gets_401(self) -> None:
        client = _client()
        resp = client.delete("/chat/share/doesnotmatter")
        assert resp.status_code == 401

    def test_revoke_twice_is_idempotent(self) -> None:
        client = _client()
        cookie, _ = _register_and_login(client)
        share_id = self._create_share(client, cookie)

        client.delete(f"/chat/share/{share_id}", cookies={"sity_session": cookie})
        resp2 = client.delete(f"/chat/share/{share_id}", cookies={"sity_session": cookie})
        assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# GET /chat/share — list all shares for authenticated user
# ---------------------------------------------------------------------------

class TestListShares:
    def _create_share(self, client: TestClient, cookie: str) -> str:
        resp = client.post("/chat/share", cookies={"sity_session": cookie})
        assert resp.status_code == 201
        return resp.json()["share_id"]

    def test_returns_own_links_with_correct_fields(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        _add_messages(session_id, [("user", "Hola"), ("sity", "¿Qué tal?")])

        share_id = self._create_share(client, cookie)

        resp = client.get("/chat/share", cookies={"sity_session": cookie})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["shares"]) == 1
        item = body["shares"][0]
        assert item["share_id"] == share_id
        assert "url" in item and share_id in item["url"]
        assert "created_at" in item
        assert "expires_at" in item
        assert "view_count" in item
        assert item["is_active"] is True
        assert item["revoked_at"] is None

    def test_isolation_other_user_not_visible(self) -> None:
        client = _client()
        cookie_a, user_id_a = _register_and_login(client)
        cookie_b, user_id_b = _register_and_login(client)
        _add_messages(f"user:{user_id_a}", [("user", "A")])
        _add_messages(f"user:{user_id_b}", [("user", "B")])

        self._create_share(client, cookie_a)
        self._create_share(client, cookie_b)

        resp_a = client.get("/chat/share", cookies={"sity_session": cookie_a})
        shares_a = resp_a.json()["shares"]
        resp_b = client.get("/chat/share", cookies={"sity_session": cookie_b})
        shares_b = resp_b.json()["shares"]

        ids_a = {s["share_id"] for s in shares_a}
        ids_b = {s["share_id"] for s in shares_b}
        assert ids_a.isdisjoint(ids_b), "Users must never see each other's links"

    def test_guest_gets_401(self) -> None:
        client = _client()
        resp = client.get("/chat/share")
        assert resp.status_code == 401

    def test_revoked_link_listed_as_inactive(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        _add_messages(f"user:{user_id}", [("user", "Hola")])

        share_id = self._create_share(client, cookie)
        client.delete(f"/chat/share/{share_id}", cookies={"sity_session": cookie})

        resp = client.get("/chat/share", cookies={"sity_session": cookie})
        item = next(s for s in resp.json()["shares"] if s["share_id"] == share_id)
        assert item["is_active"] is False
        assert item["revoked_at"] is not None

    def test_expired_link_listed_as_inactive(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        _add_messages(f"user:{user_id}", [("user", "Hola")])

        share_id = self._create_share(client, cookie)

        # Back-date expires_at in DB to simulate expiry.
        with Session(engine) as db:
            sc = db.get(SharedConversation, share_id)
            sc.expires_at = utc_now() - timedelta(seconds=1)
            db.add(sc)
            db.commit()

        resp = client.get("/chat/share", cookies={"sity_session": cookie})
        item = next(s for s in resp.json()["shares"] if s["share_id"] == share_id)
        assert item["is_active"] is False

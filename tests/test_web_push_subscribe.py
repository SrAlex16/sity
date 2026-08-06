"""Tests for Web Push subscription endpoints (Paso 1 — infraestructura base).

Coverage:
- GET /notifications/vapid-public-key: returns public key from env
- GET /notifications/vapid-public-key: 503 when VAPID_PUBLIC_KEY not set
- POST /notifications/subscribe: authenticated user creates PushSubscription
- POST /notifications/subscribe: same endpoint is updated (idempotent upsert)
- POST /notifications/subscribe: guest gets 401
- POST /notifications/subscribe: inactive subscription is reactivated on re-subscribe
- DELETE /notifications/subscribe: marks subscription inactive (is_active=False)
- DELETE /notifications/subscribe: idempotent — 204 even if endpoint not found
- DELETE /notifications/subscribe: guest gets 401
- DELETE /notifications/subscribe: only deactivates matching session's subscription
"""
from __future__ import annotations

import os
import uuid as _uuid_mod
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.db import engine
from app.memory.models import PushSubscription


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _email() -> str:
    return f"push_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register_and_login(client: TestClient) -> tuple[str, int]:
    resp = client.post("/auth/register", json={"email": _email(), "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies["sity_session"]
    return cookie, resp.json()["id"]


def _sub_body(suffix: str = "") -> dict:
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/test-endpoint-{suffix or _uid()}",
        "keys": {
            "p256dh": "BNbdab_test_p256dh_key_base64url==",
            "auth": "test_auth_secret==",
        },
    }


def _active_subs(session_id: str) -> list[PushSubscription]:
    with Session(engine) as db:
        return list(db.exec(
            select(PushSubscription).where(
                PushSubscription.session_id == session_id,
                PushSubscription.is_active == True,  # noqa: E712
            )
        ).all())


# ---------------------------------------------------------------------------
# GET /notifications/vapid-public-key
# ---------------------------------------------------------------------------

class TestVapidPublicKey:
    def test_returns_public_key(self) -> None:
        client = _client()
        resp = client.get("/notifications/vapid-public-key")
        assert resp.status_code == 200
        body = resp.json()
        assert "public_key" in body
        assert body["public_key"] == os.environ["VAPID_PUBLIC_KEY"]

    def test_503_when_key_not_configured(self) -> None:
        client = _client()
        with patch.dict(os.environ, {"VAPID_PUBLIC_KEY": ""}):
            resp = client.get("/notifications/vapid-public-key")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /notifications/subscribe
# ---------------------------------------------------------------------------

class TestSubscribe:
    def test_authenticated_user_creates_subscription(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        body = _sub_body()

        resp = client.post(
            "/notifications/subscribe",
            json=body,
            cookies={"sity_session": cookie},
        )

        assert resp.status_code == 201, resp.text
        subs = _active_subs(session_id)
        assert len(subs) == 1
        assert subs[0].endpoint == body["endpoint"]
        assert subs[0].p256dh == body["keys"]["p256dh"]
        assert subs[0].auth == body["keys"]["auth"]

    def test_same_endpoint_is_updated_not_duplicated(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        endpoint = f"https://fcm.googleapis.com/fcm/send/fixed-{_uid()}"

        body_v1 = {"endpoint": endpoint, "keys": {"p256dh": "old_key==", "auth": "old_auth=="}}
        body_v2 = {"endpoint": endpoint, "keys": {"p256dh": "new_key==", "auth": "new_auth=="}}

        client.post("/notifications/subscribe", json=body_v1, cookies={"sity_session": cookie})
        resp = client.post("/notifications/subscribe", json=body_v2, cookies={"sity_session": cookie})

        assert resp.status_code == 201
        subs = _active_subs(session_id)
        # Exactly one active subscription for this endpoint
        matching = [s for s in subs if s.endpoint == endpoint]
        assert len(matching) == 1
        assert matching[0].p256dh == "new_key=="
        assert matching[0].auth == "new_auth=="

    def test_guest_gets_401(self) -> None:
        client = _client()
        resp = client.post("/notifications/subscribe", json=_sub_body())
        assert resp.status_code == 401

    def test_reactivates_previously_inactive_subscription(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        endpoint = f"https://fcm.googleapis.com/fcm/send/reactivate-{_uid()}"

        # Subscribe, then manually mark as inactive (simulates 410 Gone from push service)
        client.post(
            "/notifications/subscribe",
            json={"endpoint": endpoint, "keys": {"p256dh": "k==", "auth": "a=="}},
            cookies={"sity_session": cookie},
        )
        with Session(engine) as db:
            sub = db.exec(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            ).first()
            assert sub is not None
            sub.is_active = False
            db.add(sub)
            db.commit()

        # Re-subscribe with same endpoint → should reactivate
        resp = client.post(
            "/notifications/subscribe",
            json={"endpoint": endpoint, "keys": {"p256dh": "new_k==", "auth": "new_a=="}},
            cookies={"sity_session": cookie},
        )
        assert resp.status_code == 201
        subs = _active_subs(session_id)
        matching = [s for s in subs if s.endpoint == endpoint]
        assert len(matching) == 1
        assert matching[0].is_active is True


# ---------------------------------------------------------------------------
# DELETE /notifications/subscribe
# ---------------------------------------------------------------------------

class TestUnsubscribe:
    def test_marks_subscription_inactive(self) -> None:
        client = _client()
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        endpoint = f"https://fcm.googleapis.com/fcm/send/unsub-{_uid()}"

        client.post(
            "/notifications/subscribe",
            json={"endpoint": endpoint, "keys": {"p256dh": "k==", "auth": "a=="}},
            cookies={"sity_session": cookie},
        )
        assert len(_active_subs(session_id)) == 1

        resp = client.request(
            "DELETE",
            "/notifications/subscribe",
            json={"endpoint": endpoint},
            cookies={"sity_session": cookie},
        )

        assert resp.status_code == 204
        assert len(_active_subs(session_id)) == 0

    def test_idempotent_when_endpoint_not_found(self) -> None:
        client = _client()
        cookie, _ = _register_and_login(client)

        resp = client.request(
            "DELETE",
            "/notifications/subscribe",
            json={"endpoint": "https://fcm.googleapis.com/fcm/send/nonexistent"},
            cookies={"sity_session": cookie},
        )
        assert resp.status_code == 204

    def test_guest_gets_401(self) -> None:
        client = _client()
        resp = client.request(
            "DELETE",
            "/notifications/subscribe",
            json={"endpoint": "https://fcm.googleapis.com/fcm/send/anything"},
        )
        assert resp.status_code == 401

    def test_only_deactivates_own_session_subscription(self) -> None:
        client = _client()
        cookie_a, user_id_a = _register_and_login(client)
        cookie_b, user_id_b = _register_and_login(client)
        session_a = f"user:{user_id_a}"
        endpoint = f"https://fcm.googleapis.com/fcm/send/isolation-{_uid()}"

        # Both users subscribe with the same endpoint (edge case — different sessions)
        client.post(
            "/notifications/subscribe",
            json={"endpoint": endpoint, "keys": {"p256dh": "k==", "auth": "a=="}},
            cookies={"sity_session": cookie_a},
        )
        client.post(
            "/notifications/subscribe",
            json={"endpoint": endpoint, "keys": {"p256dh": "k==", "auth": "a=="}},
            cookies={"sity_session": cookie_b},
        )

        # User B unsubscribes — should NOT affect user A's subscription
        client.request(
            "DELETE",
            "/notifications/subscribe",
            json={"endpoint": endpoint},
            cookies={"sity_session": cookie_b},
        )

        subs_a = _active_subs(session_a)
        assert len(subs_a) == 1, "User A's subscription should still be active"

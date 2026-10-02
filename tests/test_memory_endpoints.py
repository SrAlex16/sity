"""Tests for /memory endpoints.

Coverage:
  GET  /memory/semantic-facts  — guest → 401, user → 200 paginado
  GET  /memory/episodes        — guest → 401, user → 200 paginado
  GET  /memory/self-beliefs    — user → 403, admin → 200
  DELETE /memory/semantic-facts/{id} — own → 200, other user's → 404
  DELETE /memory/episodes/{id}       — own → 200, other user's → 404
  DELETE /memory/semantic-facts/batch — only deletes caller's records
  DELETE /memory/episodes/batch       — only deletes caller's records
  DELETE /memory/self-beliefs/{id}    — admin → 200, user → 403
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.db import engine
from app.memory.models import (
    Episode,
    SemanticFact,
    SelfBelief,
    SelfModel,
    User,
    utc_now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _email(tag: str = "") -> str:
    prefix = tag or "user"
    return f"test_mem_{prefix}_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register_and_login(client: TestClient, email: str, password: str = "Str0ngPass1") -> None:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if user and not user.is_verified:
            user.is_verified = True
            session.add(user)
            session.commit()
    client.post("/auth/login", json={"email": email, "password": password})


def _get_user_id(email: str) -> int:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        assert user is not None
        return user.id  # type: ignore[return-value]


def _make_admin(email: str) -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        assert user is not None
        user.role = "admin"
        session.add(user)
        session.commit()


def _insert_fact(user_id: int, proposition: str = "Le gusta el café", confidence: float = 0.8) -> int:
    with Session(engine) as session:
        fact = SemanticFact(
            user_id=user_id,
            proposition=proposition,
            confidence=confidence,
            is_active=True,
            stability="normal",
            inference_type="explicit",
            created_at=utc_now(),
        )
        session.add(fact)
        session.commit()
        session.refresh(fact)
        return fact.id  # type: ignore[return-value]


def _insert_episode(user_id: int, summary: str = "Conversación importante") -> int:
    with Session(engine) as session:
        ep = Episode(
            user_id=user_id,
            summary=summary,
            salience_total=0.7,
            occurred_at=utc_now(),
            created_at=utc_now(),
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)
        return ep.id  # type: ignore[return-value]


def _get_or_create_self_model_id() -> int:
    with Session(engine) as session:
        sm = session.exec(select(SelfModel)).first()
        if not sm:
            sm = SelfModel()
            session.add(sm)
            session.commit()
            session.refresh(sm)
        return sm.id  # type: ignore[return-value]


def _insert_self_belief(proposition: str = "Soy curiosa") -> int:
    sm_id = _get_or_create_self_model_id()
    with Session(engine) as session:
        belief = SelfBelief(
            self_model_id=sm_id,
            proposition=proposition,
            confidence=0.6,
            source="metacognition",
            is_active=True,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(belief)
        session.commit()
        session.refresh(belief)
        return belief.id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# SemanticFacts — GET
# ---------------------------------------------------------------------------


class TestListSemanticFacts:
    def test_guest_returns_401(self) -> None:
        client = _client()
        resp = client.get("/memory/semantic-facts")
        assert resp.status_code == 401

    def test_user_returns_200_with_pagination(self) -> None:
        client = _client()
        email = _email("sf_list")
        _register_and_login(client, email)
        uid = _get_user_id(email)
        _insert_fact(uid, "Hecho de prueba", 0.9)

        resp = client.get("/memory/semantic-facts?page=1&per_page=20")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert data["total"] >= 1
        # Verify our inserted fact appears
        propositions = [i["proposition"] for i in data["items"]]
        assert "Hecho de prueba" in propositions

    def test_only_own_facts_returned(self) -> None:
        client_a = _client()
        client_b = _client()
        email_a = _email("sf_own_a")
        email_b = _email("sf_own_b")
        _register_and_login(client_a, email_a)
        _register_and_login(client_b, email_b)
        uid_a = _get_user_id(email_a)
        uid_b = _get_user_id(email_b)

        _insert_fact(uid_a, f"Hecho de A {_uid()}")
        _insert_fact(uid_b, f"Hecho de B {_uid()}")

        resp_a = client_a.get("/memory/semantic-facts")
        ids_a = {i["id"] for i in resp_a.json()["items"]}
        resp_b = client_b.get("/memory/semantic-facts")
        ids_b = {i["id"] for i in resp_b.json()["items"]}
        assert ids_a.isdisjoint(ids_b), "Users should not see each other's facts"

    def test_pagination_per_page(self) -> None:
        client = _client()
        email = _email("sf_pag")
        _register_and_login(client, email)
        uid = _get_user_id(email)
        for i in range(5):
            _insert_fact(uid, f"Hecho paginación {i} {_uid()}")

        resp = client.get("/memory/semantic-facts?page=1&per_page=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["per_page"] == 2

    def test_inactive_facts_excluded(self) -> None:
        client = _client()
        email = _email("sf_inactive")
        _register_and_login(client, email)
        uid = _get_user_id(email)
        tag = _uid()
        with Session(engine) as session:
            fact = SemanticFact(
                user_id=uid,
                proposition=f"Hecho inactivo {tag}",
                confidence=0.9,
                is_active=False,
                stability="normal",
                inference_type="explicit",
                created_at=utc_now(),
            )
            session.add(fact)
            session.commit()

        resp = client.get("/memory/semantic-facts")
        assert resp.status_code == 200
        propositions = [i["proposition"] for i in resp.json()["items"]]
        assert not any(f"inactivo {tag}" in p for p in propositions)


# ---------------------------------------------------------------------------
# Episodes — GET
# ---------------------------------------------------------------------------


class TestListEpisodes:
    def test_guest_returns_401(self) -> None:
        client = _client()
        resp = client.get("/memory/episodes")
        assert resp.status_code == 401

    def test_user_returns_200_with_pagination(self) -> None:
        client = _client()
        email = _email("ep_list")
        _register_and_login(client, email)
        uid = _get_user_id(email)
        _insert_episode(uid, "Episodio de prueba")

        resp = client.get("/memory/episodes")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1
        summaries = [i["summary"] for i in data["items"]]
        assert "Episodio de prueba" in summaries

    def test_only_own_episodes_returned(self) -> None:
        client_a = _client()
        client_b = _client()
        email_a = _email("ep_own_a")
        email_b = _email("ep_own_b")
        _register_and_login(client_a, email_a)
        _register_and_login(client_b, email_b)
        uid_a = _get_user_id(email_a)
        uid_b = _get_user_id(email_b)

        _insert_episode(uid_a, f"Episodio A {_uid()}")
        _insert_episode(uid_b, f"Episodio B {_uid()}")

        ids_a = {i["id"] for i in client_a.get("/memory/episodes").json()["items"]}
        ids_b = {i["id"] for i in client_b.get("/memory/episodes").json()["items"]}
        assert ids_a.isdisjoint(ids_b)


# ---------------------------------------------------------------------------
# SelfBeliefs — GET
# ---------------------------------------------------------------------------


class TestListSelfBeliefs:
    def test_guest_returns_403(self) -> None:
        client = _client()
        resp = client.get("/memory/self-beliefs")
        assert resp.status_code == 403

    def test_user_returns_403(self) -> None:
        client = _client()
        email = _email("sb_user")
        _register_and_login(client, email)
        resp = client.get("/memory/self-beliefs")
        assert resp.status_code == 403

    def test_admin_returns_200(self) -> None:
        client = _client()
        email = _email("sb_admin")
        _register_and_login(client, email)
        _make_admin(email)
        # Re-login to pick up new role
        client.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})

        _insert_self_belief(f"Creencia de prueba {_uid()}")

        resp = client.get("/memory/self-beliefs")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert all("proposition" in i for i in data["items"])
        assert all("confidence" in i for i in data["items"])
        assert all("source" in i for i in data["items"])


# ---------------------------------------------------------------------------
# SemanticFacts — DELETE
# ---------------------------------------------------------------------------


class TestDeleteSemanticFact:
    def test_delete_own_fact(self) -> None:
        client = _client()
        email = _email("sf_del")
        _register_and_login(client, email)
        uid = _get_user_id(email)
        fid = _insert_fact(uid, f"Para borrar {_uid()}")

        resp = client.delete(f"/memory/semantic-facts/{fid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        with Session(engine) as session:
            assert session.get(SemanticFact, fid) is None

    def test_delete_other_users_fact_returns_404(self) -> None:
        client_a = _client()
        client_b = _client()
        email_a = _email("sf_del_a")
        email_b = _email("sf_del_b")
        _register_and_login(client_a, email_a)
        _register_and_login(client_b, email_b)
        uid_a = _get_user_id(email_a)
        fid = _insert_fact(uid_a, f"Hecho de A {_uid()}")

        resp = client_b.delete(f"/memory/semantic-facts/{fid}")
        assert resp.status_code == 404

        with Session(engine) as session:
            assert session.get(SemanticFact, fid) is not None

    def test_guest_delete_returns_401(self) -> None:
        client = _client()
        uid_placeholder = 1
        fid = _insert_fact(uid_placeholder, f"Hecho guest {_uid()}")
        resp = client.delete(f"/memory/semantic-facts/{fid}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Episodes — DELETE
# ---------------------------------------------------------------------------


class TestDeleteEpisode:
    def test_delete_own_episode(self) -> None:
        client = _client()
        email = _email("ep_del")
        _register_and_login(client, email)
        uid = _get_user_id(email)
        eid = _insert_episode(uid, f"Para borrar {_uid()}")

        resp = client.delete(f"/memory/episodes/{eid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        with Session(engine) as session:
            assert session.get(Episode, eid) is None

    def test_delete_other_users_episode_returns_404(self) -> None:
        client_a = _client()
        client_b = _client()
        email_a = _email("ep_del_a")
        email_b = _email("ep_del_b")
        _register_and_login(client_a, email_a)
        _register_and_login(client_b, email_b)
        uid_a = _get_user_id(email_a)
        eid = _insert_episode(uid_a, f"Episodio de A {_uid()}")

        resp = client_b.delete(f"/memory/episodes/{eid}")
        assert resp.status_code == 404

        with Session(engine) as session:
            assert session.get(Episode, eid) is not None


# ---------------------------------------------------------------------------
# Batch DELETE — SemanticFacts
# ---------------------------------------------------------------------------


class TestBatchDeleteSemanticFacts:
    def test_batch_only_deletes_own_records(self) -> None:
        client_a = _client()
        client_b = _client()
        email_a = _email("sf_batch_a")
        email_b = _email("sf_batch_b")
        _register_and_login(client_a, email_a)
        _register_and_login(client_b, email_b)
        uid_a = _get_user_id(email_a)
        uid_b = _get_user_id(email_b)

        fid_a = _insert_fact(uid_a, f"Hecho A {_uid()}")
        fid_b = _insert_fact(uid_b, f"Hecho B {_uid()}")

        # client_a tries to delete both ids
        resp = client_a.request(
            "DELETE",
            "/memory/semantic-facts/batch",
            json={"ids": [fid_a, fid_b]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        with Session(engine) as session:
            assert session.get(SemanticFact, fid_a) is None
            assert session.get(SemanticFact, fid_b) is not None

    def test_batch_empty_ids(self) -> None:
        client = _client()
        email = _email("sf_batch_empty")
        _register_and_login(client, email)
        resp = client.request("DELETE", "/memory/semantic-facts/batch", json={"ids": []})
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# Batch DELETE — Episodes
# ---------------------------------------------------------------------------


class TestBatchDeleteEpisodes:
    def test_batch_only_deletes_own_records(self) -> None:
        client_a = _client()
        client_b = _client()
        email_a = _email("ep_batch_a")
        email_b = _email("ep_batch_b")
        _register_and_login(client_a, email_a)
        _register_and_login(client_b, email_b)
        uid_a = _get_user_id(email_a)
        uid_b = _get_user_id(email_b)

        eid_a = _insert_episode(uid_a, f"Episodio A {_uid()}")
        eid_b = _insert_episode(uid_b, f"Episodio B {_uid()}")

        resp = client_a.request(
            "DELETE",
            "/memory/episodes/batch",
            json={"ids": [eid_a, eid_b]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        with Session(engine) as session:
            assert session.get(Episode, eid_a) is None
            assert session.get(Episode, eid_b) is not None


# ---------------------------------------------------------------------------
# SelfBeliefs — DELETE (admin only)
# ---------------------------------------------------------------------------


class TestDeleteSelfBelief:
    def test_user_cannot_delete_self_belief(self) -> None:
        client = _client()
        email = _email("sb_del_user")
        _register_and_login(client, email)
        bid = _insert_self_belief(f"Creencia {_uid()}")

        resp = client.delete(f"/memory/self-beliefs/{bid}")
        assert resp.status_code == 403

    def test_admin_can_delete_self_belief(self) -> None:
        client = _client()
        email = _email("sb_del_admin")
        _register_and_login(client, email)
        _make_admin(email)
        client.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})

        bid = _insert_self_belief(f"Creencia para borrar {_uid()}")
        resp = client.delete(f"/memory/self-beliefs/{bid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        with Session(engine) as session:
            assert session.get(SelfBelief, bid) is None

    def test_admin_batch_delete_self_beliefs(self) -> None:
        client = _client()
        email = _email("sb_batch_admin")
        _register_and_login(client, email)
        _make_admin(email)
        client.post("/auth/login", json={"email": email, "password": "Str0ngPass1"})

        bid1 = _insert_self_belief(f"Creencia batch 1 {_uid()}")
        bid2 = _insert_self_belief(f"Creencia batch 2 {_uid()}")

        resp = client.request(
            "DELETE",
            "/memory/self-beliefs/batch",
            json={"ids": [bid1, bid2]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

        with Session(engine) as session:
            assert session.get(SelfBelief, bid1) is None
            assert session.get(SelfBelief, bid2) is None

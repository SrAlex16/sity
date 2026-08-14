"""Tests for Alter endpoints — Paso 2 (HTTP layer).

These tests verify that endpoints wire correctly to AlterService,
enforce auth (Guest → 401), and return the right status codes.
They do NOT duplicate the 23 service-layer tests in test_alters.py.

Coverage:
  - Guest rejected (401) on all alter endpoints
  - List returns 5 empty slots
  - Save → slot appears in list with correct name
  - Load succeeds; load empty slot → 400
  - Rename changes name; rename empty slot → 400
  - Delete empties slot (204)
  - Copy success; copy from empty slot → 400
  - Slot out of range → 422 (FastAPI Path validation)
  - Two users cannot see each other's alters (implicit user_id isolation)
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _email() -> str:
    return f"alter_{uuid.uuid4().hex[:8]}@sity-test.invalid"


def _register(client: TestClient) -> str:
    resp = client.post("/auth/register", json={"email": _email(), "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies.get("sity_session")
    assert cookie
    return cookie


def _auth(cookie: str) -> dict:
    return {"sity_session": cookie}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def test_guest_list_alters_401() -> None:
    with _client() as c:
        r = c.get("/settings/alters")
    assert r.status_code == 401


def test_guest_save_alter_401() -> None:
    with _client() as c:
        r = c.post("/settings/alters/1/save", json={"name": "X"})
    assert r.status_code == 401


def test_guest_load_alter_401() -> None:
    with _client() as c:
        r = c.post("/settings/alters/1/load")
    assert r.status_code == 401


def test_guest_rename_alter_401() -> None:
    with _client() as c:
        r = c.patch("/settings/alters/1/rename", json={"name": "X"})
    assert r.status_code == 401


def test_guest_delete_alter_401() -> None:
    with _client() as c:
        r = c.delete("/settings/alters/1")
    assert r.status_code == 401


def test_guest_copy_alter_401() -> None:
    with _client() as c:
        r = c.post("/settings/alters/1/copy/2")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /settings/alters
# ---------------------------------------------------------------------------

def test_list_alters_returns_5_empty_slots() -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.get("/settings/alters", cookies=_auth(cookie))
    assert r.status_code == 200
    slots = r.json()
    assert len(slots) == 5
    for i, slot in enumerate(slots, start=1):
        assert slot["slot"] == i
        assert slot["is_empty"] is True
        assert slot["name"] is None
        assert slot["parameters"] is None


# ---------------------------------------------------------------------------
# POST /settings/alters/{slot}/save
# ---------------------------------------------------------------------------

def test_save_alter_returns_slot_with_name() -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.post("/settings/alters/2/save", json={"name": "Modo noche"},
                   cookies=_auth(cookie))
    assert r.status_code == 200
    body = r.json()
    assert body["slot"] == 2
    assert body["name"] == "Modo noche"
    assert body["is_empty"] is False
    assert len(body["parameters"]) == 15


def test_save_alter_appears_in_list() -> None:
    with _client() as c:
        cookie = _register(c)
        c.post("/settings/alters/3/save", json={"name": "Trabajo"}, cookies=_auth(cookie))
        slots = c.get("/settings/alters", cookies=_auth(cookie)).json()
    assert slots[2]["slot"] == 3
    assert slots[2]["name"] == "Trabajo"
    assert slots[2]["is_empty"] is False
    for i in [0, 1, 3, 4]:
        assert slots[i]["is_empty"] is True


# ---------------------------------------------------------------------------
# POST /settings/alters/{slot}/load
# ---------------------------------------------------------------------------

def test_load_alter_empty_slot_returns_400() -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.post("/settings/alters/4/load", cookies=_auth(cookie))
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_load_alter_success() -> None:
    with _client() as c:
        cookie = _register(c)
        # Adjust one parameter, then save
        c.post("/settings/personality/adjust",
               json={"parameter": "sarcasm_level", "operation": "set_absolute", "amount": 0.88},
               cookies=_auth(cookie))
        c.post("/settings/alters/1/save", json={"name": "Sarcástica"}, cookies=_auth(cookie))

        # Reset personality to defaults, then load the alter
        c.post("/settings/personality/reset", cookies=_auth(cookie))
        r = c.post("/settings/alters/1/load", cookies=_auth(cookie))

    assert r.status_code == 200
    body = r.json()
    assert "personality" in body
    assert body["personality"]["sarcasm_level"] == pytest.approx(0.88, abs=1e-4)


# ---------------------------------------------------------------------------
# PATCH /settings/alters/{slot}/rename
# ---------------------------------------------------------------------------

def test_rename_alter_success() -> None:
    with _client() as c:
        cookie = _register(c)
        c.post("/settings/alters/2/save", json={"name": "Original"}, cookies=_auth(cookie))
        r = c.patch("/settings/alters/2/rename", json={"name": "Actualizado"},
                    cookies=_auth(cookie))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_rename_alter_empty_slot_returns_400() -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.patch("/settings/alters/5/rename", json={"name": "X"}, cookies=_auth(cookie))
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_rename_shows_new_name_in_list() -> None:
    with _client() as c:
        cookie = _register(c)
        c.post("/settings/alters/1/save", json={"name": "Antes"}, cookies=_auth(cookie))
        c.patch("/settings/alters/1/rename", json={"name": "Después"}, cookies=_auth(cookie))
        slots = c.get("/settings/alters", cookies=_auth(cookie)).json()
    assert slots[0]["name"] == "Después"


# ---------------------------------------------------------------------------
# DELETE /settings/alters/{slot}
# ---------------------------------------------------------------------------

def test_delete_alter_returns_204() -> None:
    with _client() as c:
        cookie = _register(c)
        c.post("/settings/alters/3/save", json={"name": "Borrar"}, cookies=_auth(cookie))
        r = c.delete("/settings/alters/3", cookies=_auth(cookie))
    assert r.status_code == 204


def test_delete_alter_slot_appears_empty_after() -> None:
    with _client() as c:
        cookie = _register(c)
        c.post("/settings/alters/2/save", json={"name": "Temporal"}, cookies=_auth(cookie))
        c.delete("/settings/alters/2", cookies=_auth(cookie))
        slots = c.get("/settings/alters", cookies=_auth(cookie)).json()
    assert slots[1]["is_empty"] is True


def test_delete_already_empty_slot_returns_204() -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.delete("/settings/alters/5", cookies=_auth(cookie))
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# POST /settings/alters/{from_slot}/copy/{to_slot}
# ---------------------------------------------------------------------------

def test_copy_alter_success() -> None:
    with _client() as c:
        cookie = _register(c)
        c.post("/settings/alters/1/save", json={"name": "Original"}, cookies=_auth(cookie))
        r = c.post("/settings/alters/1/copy/4", cookies=_auth(cookie))
    assert r.status_code == 200
    body = r.json()
    assert body["slot"] == 4
    assert body["name"] == "Original"
    assert body["is_empty"] is False


def test_copy_alter_from_empty_returns_400() -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.post("/settings/alters/3/copy/5", cookies=_auth(cookie))
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Path validation (FastAPI rejects out-of-range slots with 422)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot", [0, 6])
def test_slot_out_of_range_returns_422(slot: int) -> None:
    with _client() as c:
        cookie = _register(c)
        r = c.post(f"/settings/alters/{slot}/save", json={"name": "X"}, cookies=_auth(cookie))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# User isolation — two users cannot see each other's alters
# ---------------------------------------------------------------------------

def test_two_users_see_isolated_alters() -> None:
    with _client() as c:
        cookie_a = _register(c)
        cookie_b = _register(c)

        c.post("/settings/alters/1/save", json={"name": "User-A-Slot1"}, cookies=_auth(cookie_a))
        c.post("/settings/alters/1/save", json={"name": "User-B-Slot1"}, cookies=_auth(cookie_b))

        slots_a = c.get("/settings/alters", cookies=_auth(cookie_a)).json()
        slots_b = c.get("/settings/alters", cookies=_auth(cookie_b)).json()

    assert slots_a[0]["name"] == "User-A-Slot1"
    assert slots_b[0]["name"] == "User-B-Slot1"
    # User B has only slot 1 filled
    for i in range(1, 5):
        assert slots_b[i]["is_empty"] is True

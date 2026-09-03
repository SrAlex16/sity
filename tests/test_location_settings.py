"""Tests for GET/PUT /settings/location and location_context rendering.

Coverage:
  - Default values are empty strings
  - PUT saves city + source and returns them
  - Per-session isolation: two users don't cross-contaminate
  - Guest users are rejected (401)
  - Invalid source value is rejected (422)
  - render_location_context: no city → empty string
  - render_location_context: city present → block with city
  - render_location_context: source=denied → denial block
  - render_location_context: source=auto/browser/manual behave like city present
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _email() -> str:
    return f"loc_{str(uuid.uuid4())[:8]}@sity-test.invalid"


def _register(client: TestClient) -> str:
    resp = client.post("/auth/register", json={"email": _email(), "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies.get("sity_session")
    assert cookie
    return cookie


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

def test_default_location_is_empty() -> None:
    with _client() as c:
        cookie = _register(c)
        resp = c.get("/settings/location", cookies={"sity_session": cookie})
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == ""
    assert data["source"] == ""


def test_put_location_manual_persists() -> None:
    with _client() as c:
        cookie = _register(c)
        put = c.put(
            "/settings/location",
            json={"city": "Madrid", "source": "manual"},
            cookies={"sity_session": cookie},
        )
        assert put.status_code == 200
        assert put.json()["city"] == "Madrid"
        assert put.json()["source"] == "manual"

        get = c.get("/settings/location", cookies={"sity_session": cookie})
    assert get.status_code == 200
    assert get.json()["city"] == "Madrid"
    assert get.json()["source"] == "manual"


def test_put_location_browser_source() -> None:
    with _client() as c:
        cookie = _register(c)
        put = c.put(
            "/settings/location",
            json={"city": "Barcelona", "source": "browser"},
            cookies={"sity_session": cookie},
        )
    assert put.status_code == 200
    assert put.json()["source"] == "browser"


def test_put_location_denied_source() -> None:
    with _client() as c:
        cookie = _register(c)
        put = c.put(
            "/settings/location",
            json={"city": "", "source": "denied"},
            cookies={"sity_session": cookie},
        )
    assert put.status_code == 200
    assert put.json()["source"] == "denied"
    assert put.json()["city"] == ""


def test_put_location_can_be_cleared() -> None:
    with _client() as c:
        cookie = _register(c)
        c.put("/settings/location", json={"city": "Valencia", "source": "manual"}, cookies={"sity_session": cookie})
        clear = c.put("/settings/location", json={"city": "", "source": ""}, cookies={"sity_session": cookie})
    assert clear.json()["city"] == ""
    assert clear.json()["source"] == ""


def test_location_session_isolation() -> None:
    with _client() as c:
        cookie_a = _register(c)
        cookie_b = _register(c)
        c.put("/settings/location", json={"city": "Sevilla", "source": "manual"}, cookies={"sity_session": cookie_a})
        c.put("/settings/location", json={"city": "Tokyo", "source": "browser"}, cookies={"sity_session": cookie_b})
        resp_a = c.get("/settings/location", cookies={"sity_session": cookie_a})
        resp_b = c.get("/settings/location", cookies={"sity_session": cookie_b})
    assert resp_a.json()["city"] == "Sevilla"
    assert resp_b.json()["city"] == "Tokyo"


def test_location_guest_rejected() -> None:
    with _client() as c:
        resp = c.get("/settings/location")
    assert resp.status_code == 401


def test_location_put_guest_rejected() -> None:
    with _client() as c:
        resp = c.put("/settings/location", json={"city": "Madrid", "source": "manual"})
    assert resp.status_code == 401


def test_location_invalid_source_rejected() -> None:
    with _client() as c:
        cookie = _register(c)
        resp = c.put(
            "/settings/location",
            json={"city": "Madrid", "source": "invalid_source"},
            cookies={"sity_session": cookie},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# location_context pure function tests
# ---------------------------------------------------------------------------

def test_render_no_location_returns_empty():
    from app.chat.location_context import build_location_context, render_location_context
    from app.settings.schemas import LocationSettings
    snapshot = build_location_context(LocationSettings())
    assert render_location_context(snapshot) == ""


def test_render_city_present_contains_city():
    from app.chat.location_context import build_location_context, render_location_context
    from app.settings.schemas import LocationSettings
    snapshot = build_location_context(LocationSettings(city="Madrid", source="manual"))
    block = render_location_context(snapshot)
    assert "Madrid" in block
    assert block.startswith("[Ubicación del usuario:")


def test_render_denied_returns_denial_block():
    from app.chat.location_context import build_location_context, render_location_context
    from app.settings.schemas import LocationSettings
    snapshot = build_location_context(LocationSettings(city="", source="denied"))
    block = render_location_context(snapshot)
    assert "denegado" in block.lower()
    assert "Madrid" not in block


def test_render_browser_source_shows_city():
    from app.chat.location_context import build_location_context, render_location_context
    from app.settings.schemas import LocationSettings
    snapshot = build_location_context(LocationSettings(city="Barcelona", source="browser"))
    block = render_location_context(snapshot)
    assert "Barcelona" in block


def test_render_auto_source_shows_city():
    from app.chat.location_context import build_location_context, render_location_context
    from app.settings.schemas import LocationSettings
    snapshot = build_location_context(LocationSettings(city="Valencia", source="auto"))
    block = render_location_context(snapshot)
    assert "Valencia" in block

"""Tests for GET/PUT /settings/language (Sistema 2 — Sity conversation language).

Coverage:
  - Default value is "auto"
  - PUT saves and returns the new value
  - Per-session isolation: two users with different overrides don't cross-contaminate
  - Guest users are rejected (401)
  - Unknown language code is rejected (422)
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _email() -> str:
    return f"lang_{str(uuid.uuid4())[:8]}@sity-test.invalid"


def _register(client: TestClient) -> str:
    """Register a fresh user, return sity_session cookie."""
    resp = client.post("/auth/register", json={"email": _email(), "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies.get("sity_session")
    assert cookie
    return cookie


def test_default_language_is_auto() -> None:
    with _client() as c:
        cookie = _register(c)
        resp = c.get("/settings/language", cookies={"sity_session": cookie})
    assert resp.status_code == 200
    assert resp.json()["language_override"] == "auto"


def test_put_language_persists() -> None:
    with _client() as c:
        cookie = _register(c)
        put = c.put(
            "/settings/language",
            json={"language_override": "en-US"},
            cookies={"sity_session": cookie},
        )
        assert put.status_code == 200
        assert put.json()["language_override"] == "en-US"

        get = c.get("/settings/language", cookies={"sity_session": cookie})
    assert get.status_code == 200
    assert get.json()["language_override"] == "en-US"


def test_language_session_isolation() -> None:
    with _client() as c:
        cookie_a = _register(c)
        cookie_b = _register(c)

        c.put("/settings/language", json={"language_override": "ja"}, cookies={"sity_session": cookie_a})
        c.put("/settings/language", json={"language_override": "fr-FR"}, cookies={"sity_session": cookie_b})

        resp_a = c.get("/settings/language", cookies={"sity_session": cookie_a})
        resp_b = c.get("/settings/language", cookies={"sity_session": cookie_b})

    assert resp_a.json()["language_override"] == "ja"
    assert resp_b.json()["language_override"] == "fr-FR"


def test_language_guest_rejected() -> None:
    with _client() as c:
        resp = c.get("/settings/language")
    assert resp.status_code == 401


def test_language_put_guest_rejected() -> None:
    with _client() as c:
        resp = c.put("/settings/language", json={"language_override": "en-US"})
    assert resp.status_code == 401


def test_language_put_unsupported_code_rejected() -> None:
    with _client() as c:
        cookie = _register(c)
        resp = c.put(
            "/settings/language",
            json={"language_override": "xx-XX"},
            cookies={"sity_session": cookie},
        )
    assert resp.status_code == 422


def test_all_supported_codes_accepted() -> None:
    supported = ["auto", "es-ES", "es-419", "en-US", "en-GB", "ja", "fr-FR", "de-DE", "pt-BR", "it-IT"]
    with _client() as c:
        cookie = _register(c)
        for code in supported:
            resp = c.put(
                "/settings/language",
                json={"language_override": code},
                cookies={"sity_session": cookie},
            )
            assert resp.status_code == 200, f"Code {code!r} rejected: {resp.text}"
            assert resp.json()["language_override"] == code

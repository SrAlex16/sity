"""Tests for GET/PUT /settings/verbosity and GET/PUT /settings/values.

Coverage:
  Verbosity:
  - Default verbosity is 0.60 for a fresh user
  - PUT verbosity persists and GET returns updated value
  - Two users have isolated verbosity (per-session)
  - Guest user is rejected (401)
  - Value out of range (>1.0) is rejected (422)

  SityValues:
  - GET returns default values for any authenticated user
  - Admin can PUT and values persist
  - Non-admin (user role) gets 403 on PUT
  - Guest is rejected (401) on GET
  - Value out of range is rejected (422)
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import make_admin_token, make_user_token

_SITY_VALUES_DEFAULTS = {
    "value_autonomy":    0.80,
    "value_honesty":     0.75,
    "value_helpfulness": 0.72,
    "value_curiosity":   0.66,
    "value_fairness":    0.80,
    "value_loyalty":     0.50,
}


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register(client: TestClient) -> str:
    email = f"vv_{uuid.uuid4().hex[:8]}@sity-test.invalid"
    resp = client.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies.get("sity_session")
    assert cookie
    return cookie


# ---------------------------------------------------------------------------
# Verbosity
# ---------------------------------------------------------------------------

class TestVerbosityEndpoints:

    def test_default_verbosity_is_060(self) -> None:
        with _client() as c:
            cookie = _register(c)
            resp = c.get("/settings/verbosity", cookies={"sity_session": cookie})
        assert resp.status_code == 200
        assert resp.json()["verbosity"] == pytest.approx(0.60)

    def test_put_verbosity_persists(self) -> None:
        with _client() as c:
            cookie = _register(c)
            put = c.put(
                "/settings/verbosity",
                json={"verbosity": 0.80},
                cookies={"sity_session": cookie},
            )
            assert put.status_code == 200
            assert put.json()["verbosity"] == pytest.approx(0.80)

            get = c.get("/settings/verbosity", cookies={"sity_session": cookie})
        assert get.status_code == 200
        assert get.json()["verbosity"] == pytest.approx(0.80)

    def test_verbosity_per_session_isolated(self) -> None:
        with _client() as c:
            cookie_a = _register(c)
            cookie_b = _register(c)
            c.put("/settings/verbosity", json={"verbosity": 0.90}, cookies={"sity_session": cookie_a})
            resp_b = c.get("/settings/verbosity", cookies={"sity_session": cookie_b})
        assert resp_b.json()["verbosity"] == pytest.approx(0.60)

    def test_verbosity_guest_rejected(self) -> None:
        with _client() as c:
            resp = c.get("/settings/verbosity")
        assert resp.status_code == 401

    def test_verbosity_put_guest_rejected(self) -> None:
        with _client() as c:
            resp = c.put("/settings/verbosity", json={"verbosity": 0.5})
        assert resp.status_code == 401

    def test_verbosity_out_of_range_rejected(self) -> None:
        with _client() as c:
            cookie = _register(c)
            resp = c.put(
                "/settings/verbosity",
                json={"verbosity": 1.5},
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 422

    def test_verbosity_put_boundary_values(self) -> None:
        with _client() as c:
            cookie = _register(c)
            for val in (0.0, 1.0):
                resp = c.put(
                    "/settings/verbosity",
                    json={"verbosity": val},
                    cookies={"sity_session": cookie},
                )
                assert resp.status_code == 200
                assert resp.json()["verbosity"] == pytest.approx(val)


# ---------------------------------------------------------------------------
# SityValues
# ---------------------------------------------------------------------------

class TestSityValuesEndpoints:

    def test_get_values_returns_defaults_for_user(self) -> None:
        token = make_user_token()
        with _client() as c:
            resp = c.get("/settings/values", cookies={"sity_session": token})
        assert resp.status_code == 200
        data = resp.json()
        for key, expected in _SITY_VALUES_DEFAULTS.items():
            assert data[key] == pytest.approx(expected, abs=0.01), f"{key} mismatch"

    def test_get_values_guest_rejected(self) -> None:
        with _client() as c:
            resp = c.get("/settings/values")
        assert resp.status_code == 401

    def test_put_values_admin_persists(self) -> None:
        admin_token = make_admin_token()
        with _client() as c:
            payload = {
                "value_autonomy":    0.70,
                "value_honesty":     0.70,
                "value_helpfulness": 0.70,
                "value_curiosity":   0.70,
                "value_fairness":    0.70,
                "value_loyalty":     0.70,
            }
            put = c.put(
                "/settings/values",
                json=payload,
                cookies={"sity_session": admin_token},
            )
            assert put.status_code == 200
            assert put.json()["value_autonomy"] == pytest.approx(0.70)

            get = c.get("/settings/values", cookies={"sity_session": admin_token})
            assert get.status_code == 200
            assert get.json()["value_autonomy"] == pytest.approx(0.70)

            # Restore defaults so other tests are not affected
            c.put(
                "/settings/values",
                json=_SITY_VALUES_DEFAULTS,
                cookies={"sity_session": admin_token},
            )

    def test_put_values_non_admin_rejected(self) -> None:
        user_token = make_user_token()
        payload = {
            "value_autonomy":    0.50,
            "value_honesty":     0.50,
            "value_helpfulness": 0.50,
            "value_curiosity":   0.50,
            "value_fairness":    0.50,
            "value_loyalty":     0.50,
        }
        with _client() as c:
            resp = c.put(
                "/settings/values",
                json=payload,
                cookies={"sity_session": user_token},
            )
        assert resp.status_code == 403

    def test_put_values_guest_rejected(self) -> None:
        payload = {k: 0.5 for k in _SITY_VALUES_DEFAULTS}
        with _client() as c:
            resp = c.put("/settings/values", json=payload)
        assert resp.status_code == 403

    def test_put_values_out_of_range_rejected(self) -> None:
        admin_token = make_admin_token()
        payload = {**_SITY_VALUES_DEFAULTS, "value_autonomy": 1.5}
        with _client() as c:
            resp = c.put(
                "/settings/values",
                json=payload,
                cookies={"sity_session": admin_token},
            )
        assert resp.status_code == 422


"""Tests for OAuth integration endpoints (Fase 6).

Coverage:
  - connect: returns auth_url with correctly signed state; 401 for guest; 404 for unknown provider
  - callback (valid state): upserts encrypted credentials, redirects to settings page
  - callback (expired state): returns actionable HTML ("caducó", "Ajustes"), not a generic 400
  - callback (invalid / tampered state): rejected with 400
  - callback (state user_id ≠ session user_id): rejected with 403
  - callback (provider denial): returns descriptive HTML
  - disconnect: sets is_active=False, preserves the DB row; 404 if not connected; 401 for guest
  HTTP calls to Google/Spotify are always mocked — never hit real APIs.
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes_integrations import _make_state, _STATE_MAX_AGE_SECS
from app.auth.encryption import decrypt_str
from app.main import app
from app.memory.db import engine
from app.memory.models import UserIntegration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import uuid


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _email() -> str:
    return f"integ_{_uid()}@sity-test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register_and_login(client: TestClient) -> tuple[str, int]:
    """Register a fresh user, return (sity_session cookie, user_id)."""
    resp = client.post(
        "/auth/register",
        json={"email": _email(), "password": "Str0ngPass1"},
    )
    assert resp.status_code == 201, resp.text
    cookie = resp.cookies.get("sity_session")
    assert cookie
    return cookie, resp.json()["id"]


_FAKE_GOOGLE_CREDS = json.dumps({
    "token": "ya29.fake",
    "refresh_token": "1//fake",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id.apps.googleusercontent.com",
    "client_secret": "fake-google-secret",
    "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
})
_FAKE_GOOGLE_SCOPES = "https://www.googleapis.com/auth/gmail.readonly"

_FAKE_SPOTIFY_SCOPES = "user-read-currently-playing"


def _fake_spotify_creds() -> str:
    return json.dumps({
        "access_token": "BQD_fake",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "AQD_fake",
        "scope": _FAKE_SPOTIFY_SCOPES,
        "expires_at": time.time() + 3600,
    })


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

class TestConnect:
    def test_google_returns_auth_url_with_state(self):
        with _client() as c:
            cookie, _ = _register_and_login(c)
            resp = c.get(
                "/auth/integrations/google/connect",
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_url" in data
        assert "accounts.google.com" in data["auth_url"]
        assert "state=" in data["auth_url"]

    def test_spotify_returns_auth_url(self):
        with _client() as c:
            cookie, _ = _register_and_login(c)
            resp = c.get(
                "/auth/integrations/spotify/connect",
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 200
        assert "accounts.spotify.com" in resp.json()["auth_url"]

    def test_guest_gets_401(self):
        with _client() as c:
            resp = c.get("/auth/integrations/google/connect")
        assert resp.status_code == 401

    def test_unknown_provider_gets_404(self):
        with _client() as c:
            cookie, _ = _register_and_login(c)
            resp = c.get(
                "/auth/integrations/unknown_prov/connect",
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# callback
# ---------------------------------------------------------------------------

class TestCallback:
    def test_valid_state_upserts_credentials_and_redirects(self):
        """Happy path: valid state triggers upsert of encrypted credentials in DB."""
        with _client() as c:
            cookie, user_id = _register_and_login(c)
            state = _make_state(user_id, "google")

            with patch(
                "app.api.routes_integrations._google_exchange_code",
                return_value=(_FAKE_GOOGLE_CREDS, _FAKE_GOOGLE_SCOPES),
            ):
                resp = c.get(
                    "/auth/integrations/google/callback",
                    params={"code": "auth_code_fake", "state": state},
                    cookies={"sity_session": cookie},
                    follow_redirects=False,
                )

        assert resp.status_code == 302
        assert "connected=google" in resp.headers["location"]

        with Session(engine) as session:
            row = session.exec(
                select(UserIntegration)
                .where(UserIntegration.user_id == user_id)
                .where(UserIntegration.provider == "google")
            ).first()

        assert row is not None
        assert row.is_active is True
        # Stored value must be ciphertext, not plaintext
        assert row.encrypted_credentials != _FAKE_GOOGLE_CREDS
        # And must decrypt back to the original JSON
        assert decrypt_str(row.encrypted_credentials) == _FAKE_GOOGLE_CREDS

    def test_expired_state_shows_actionable_html(self):
        """Expired state → HTML with 'caducó' and pointer to Ajustes, not a generic error."""
        with _client() as c:
            cookie, user_id = _register_and_login(c)

            # Build a state whose timestamp is already past the expiry window.
            # Patch time.time() inside routes_integrations so _make_state uses
            # an old timestamp; the callback will then see it as expired.
            past_ts = int(time.time()) - (_STATE_MAX_AGE_SECS + 10)
            with patch("app.api.routes_integrations.time") as mock_time:
                mock_time.time.return_value = past_ts
                state = _make_state(user_id, "google")

            # No patch here: real time.time() makes the state appear 610+ s old
            resp = c.get(
                "/auth/integrations/google/callback",
                params={"code": "fake_code", "state": state},
                cookies={"sity_session": cookie},
            )

        assert resp.status_code == 400
        assert "text/html" in resp.headers["content-type"]
        body = resp.text
        assert "caducó" in body
        assert "Ajustes" in body

    def test_tampered_state_rejected_400(self):
        """Structurally invalid or HMAC-forged state is rejected with 400."""
        with _client() as c:
            cookie, _ = _register_and_login(c)
            resp = c.get(
                "/auth/integrations/google/callback",
                params={"code": "fake_code", "state": "tampered!not-valid-base64"},
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 400

    def test_state_user_mismatch_rejected_403(self):
        """State issued to user A cannot be completed by user B (defense in depth)."""
        with _client() as c:
            cookie_a, user_id_a = _register_and_login(c)
            cookie_b, _ = _register_and_login(c)

            state_for_a = _make_state(user_id_a, "google")

            resp = c.get(
                "/auth/integrations/google/callback",
                params={"code": "fake_code", "state": state_for_a},
                cookies={"sity_session": cookie_b},
            )
        assert resp.status_code == 403

    def test_provider_denial_shows_html(self):
        """Provider sends error=access_denied → descriptive HTML, not a JSON error."""
        with _client() as c:
            cookie, _ = _register_and_login(c)
            resp = c.get(
                "/auth/integrations/google/callback",
                params={"error": "access_denied"},
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 400
        assert "text/html" in resp.headers["content-type"]

    def test_guest_gets_401(self):
        with _client() as c:
            resp = c.get(
                "/auth/integrations/google/callback",
                params={"code": "fake", "state": "fake"},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    def _connect_spotify(self, client: TestClient, cookie: str, user_id: int) -> None:
        """Helper: connect Spotify for a user (mocked token exchange)."""
        state = _make_state(user_id, "spotify")
        with patch(
            "app.api.routes_integrations._spotify_exchange_code",
            return_value=(_fake_spotify_creds(), _FAKE_SPOTIFY_SCOPES),
        ):
            resp = client.get(
                "/auth/integrations/spotify/callback",
                params={"code": "auth_code_fake", "state": state},
                cookies={"sity_session": cookie},
                follow_redirects=False,
            )
        assert resp.status_code == 302

    def test_sets_is_active_false_preserves_row(self):
        """Soft-disconnect flips is_active=False but the DB row is not deleted."""
        with _client() as c:
            cookie, user_id = _register_and_login(c)
            self._connect_spotify(c, cookie, user_id)

            resp = c.delete(
                "/auth/integrations/spotify",
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        with Session(engine) as session:
            row = session.exec(
                select(UserIntegration)
                .where(UserIntegration.user_id == user_id)
                .where(UserIntegration.provider == "spotify")
            ).first()

        assert row is not None, "Row must be preserved (soft-delete, not hard-delete)"
        assert row.is_active is False

    def test_not_connected_gets_404(self):
        """Disconnecting a provider that was never connected raises 404."""
        with _client() as c:
            cookie, _ = _register_and_login(c)
            resp = c.delete(
                "/auth/integrations/google",
                cookies={"sity_session": cookie},
            )
        assert resp.status_code == 404

    def test_guest_gets_401(self):
        with _client() as c:
            resp = c.delete("/auth/integrations/google")
        assert resp.status_code == 401

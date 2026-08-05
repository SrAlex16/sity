"""Tests for per-user credential resolution (Fase 6, Paso 4).

Verifies that _resolve_google_creds and _resolve_spotify_token:
  - Load user-specific credentials from UserIntegration when available
  - Fall back to the global token for Admin (no UserIntegration row)
  - Return None when neither user nor global has credentials
  - Isolate credentials between different users (no cross-contamination)
  - Refresh expired tokens and persist the update to the DB (not to disk)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.encryption import decrypt_str, encrypt_str
from app.memory.models import UserIntegration
from app.tools.registry import ToolContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_ctx(tool_name: str, *, session_id: str = "default", db_session=None) -> ToolContext:
    executor = MagicMock()
    executor.session_id = session_id
    executor.session = db_session or MagicMock()
    return ToolContext(
        tool_name=tool_name,
        tool_input={},
        trace_id="test-per-user",
        executor=executor,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# _resolve_google_creds
# ---------------------------------------------------------------------------

class TestResolveGoogleCreds:
    def test_returns_user_specific_creds_when_available(self):
        from app.tools.handlers.google_tools import _resolve_google_creds
        fake_creds = MagicMock()
        ctx = _make_ctx("gmail_search", session_id="user:42")

        with patch("app.tools.handlers.google_tools.load_user_credentials", return_value=fake_creds):
            result = _resolve_google_creds(ctx)

        assert result is fake_creds

    def test_falls_back_to_global_when_no_user_integration(self):
        from app.tools.handlers.google_tools import _resolve_google_creds
        global_creds = MagicMock()
        ctx = _make_ctx("gmail_search", session_id="user:99")

        with patch("app.tools.handlers.google_tools.load_user_credentials", return_value=None):
            with patch("app.tools.handlers.google_tools.load_credentials", return_value=global_creds):
                result = _resolve_google_creds(ctx)

        assert result is global_creds

    def test_returns_none_when_neither_user_nor_global(self):
        from app.tools.handlers.google_tools import _resolve_google_creds
        ctx = _make_ctx("gmail_search", session_id="user:1")

        with patch("app.tools.handlers.google_tools.load_user_credentials", return_value=None):
            with patch("app.tools.handlers.google_tools.load_credentials", return_value=None):
                result = _resolve_google_creds(ctx)

        assert result is None

    def test_credential_isolation_between_users(self):
        from app.tools.handlers.google_tools import _resolve_google_creds
        creds_1 = MagicMock()
        creds_2 = MagicMock()

        def fake_load(user_id, session):
            if user_id == 1:
                return creds_1
            if user_id == 2:
                return creds_2
            return None

        ctx_1 = _make_ctx("gmail_search", session_id="user:1")
        ctx_2 = _make_ctx("gmail_search", session_id="user:2")

        with patch("app.tools.handlers.google_tools.load_user_credentials", side_effect=fake_load):
            result_1 = _resolve_google_creds(ctx_1)
            result_2 = _resolve_google_creds(ctx_2)

        assert result_1 is creds_1
        assert result_2 is creds_2
        assert result_1 is not result_2

    def test_non_user_session_skips_db_lookup_uses_global(self):
        from app.tools.handlers.google_tools import _resolve_google_creds
        global_creds = MagicMock()
        ctx = _make_ctx("gmail_search", session_id="default")

        with patch("app.tools.handlers.google_tools.load_user_credentials") as mock_load:
            with patch("app.tools.handlers.google_tools.load_credentials", return_value=global_creds):
                result = _resolve_google_creds(ctx)

        mock_load.assert_not_called()
        assert result is global_creds

    def test_user_not_connected_handler_returns_clear_message(self):
        from app.tools.handlers.google_tools import handle_gmail_search
        ctx = _make_ctx("gmail_search", session_id="user:42")

        with patch("app.tools.handlers.google_tools.load_user_credentials", return_value=None):
            with patch("app.tools.handlers.google_tools.load_credentials", return_value=None):
                result = handle_gmail_search(ctx)

        assert result.ok is False
        assert "conectado" in result.message.lower()
        assert "/auth/integrations/google/connect" in result.message


# ---------------------------------------------------------------------------
# _resolve_spotify_token
# ---------------------------------------------------------------------------

class TestResolveSpotifyToken:
    def test_returns_user_specific_token_when_available(self):
        from app.tools.handlers.spotify_tools import _resolve_spotify_token
        fake_token = {"access_token": "user_token_abc"}
        ctx = _make_ctx("spotify_now_playing", session_id="user:7")

        with patch("app.tools.handlers.spotify_tools.load_user_credentials", return_value=fake_token):
            result = _resolve_spotify_token(ctx)

        assert result is fake_token

    def test_falls_back_to_global_when_no_user_integration(self):
        from app.tools.handlers.spotify_tools import _resolve_spotify_token
        global_token = {"access_token": "global_token"}
        ctx = _make_ctx("spotify_now_playing", session_id="user:99")

        with patch("app.tools.handlers.spotify_tools.load_user_credentials", return_value=None):
            with patch("app.tools.handlers.spotify_tools.load_credentials", return_value=global_token):
                result = _resolve_spotify_token(ctx)

        assert result is global_token

    def test_returns_none_when_neither_user_nor_global(self):
        from app.tools.handlers.spotify_tools import _resolve_spotify_token
        ctx = _make_ctx("spotify_now_playing", session_id="user:1")

        with patch("app.tools.handlers.spotify_tools.load_user_credentials", return_value=None):
            with patch("app.tools.handlers.spotify_tools.load_credentials", return_value=None):
                result = _resolve_spotify_token(ctx)

        assert result is None

    def test_credential_isolation_between_users(self):
        from app.tools.handlers.spotify_tools import _resolve_spotify_token
        token_1 = {"access_token": "token_user_1"}
        token_2 = {"access_token": "token_user_2"}

        def fake_load(user_id, session):
            if user_id == 1:
                return token_1
            if user_id == 2:
                return token_2
            return None

        ctx_1 = _make_ctx("spotify_now_playing", session_id="user:1")
        ctx_2 = _make_ctx("spotify_now_playing", session_id="user:2")

        with patch("app.tools.handlers.spotify_tools.load_user_credentials", side_effect=fake_load):
            result_1 = _resolve_spotify_token(ctx_1)
            result_2 = _resolve_spotify_token(ctx_2)

        assert result_1 is token_1
        assert result_2 is token_2
        assert result_1 is not result_2

    def test_non_user_session_skips_db_lookup_uses_global(self):
        from app.tools.handlers.spotify_tools import _resolve_spotify_token
        global_token = {"access_token": "global"}
        ctx = _make_ctx("spotify_now_playing", session_id="default")

        with patch("app.tools.handlers.spotify_tools.load_user_credentials") as mock_load:
            with patch("app.tools.handlers.spotify_tools.load_credentials", return_value=global_token):
                result = _resolve_spotify_token(ctx)

        mock_load.assert_not_called()
        assert result is global_token

    def test_user_not_connected_handler_returns_clear_message(self):
        from app.tools.handlers.spotify_tools import handle_spotify_now_playing
        ctx = _make_ctx("spotify_now_playing", session_id="user:42")

        with patch("app.tools.handlers.spotify_tools.load_user_credentials", return_value=None):
            with patch("app.tools.handlers.spotify_tools.load_credentials", return_value=None):
                result = handle_spotify_now_playing(ctx)

        assert result.ok is False
        assert "no está conectado" in result.message.lower()
        assert "/auth/integrations/spotify/connect" in result.message


# ---------------------------------------------------------------------------
# Token refresh persists to DB, not to disk
# ---------------------------------------------------------------------------

class TestSpotifyTokenRefreshToDb:
    def test_expired_token_is_refreshed_and_persisted_to_db(self, mem_engine):
        from app.integrations.spotify_auth import load_user_credentials

        old_token = {
            "access_token": "old_access",
            "refresh_token": "the_refresh",
            "client_id": "fake_client_id",
            "client_secret": "fake_client_secret",
            "expires_at": 0,  # expired long ago
        }

        with Session(mem_engine) as session:
            row = UserIntegration(
                user_id=200,
                provider="spotify",
                encrypted_credentials=encrypt_str(json.dumps(old_token)),
                scopes="user-read-currently-playing",
                connected_at=_utc_now(),
                is_active=True,
            )
            session.add(row)
            session.commit()

        new_token_data = {"access_token": "new_access", "expires_in": 3600}

        with patch("app.integrations.spotify_auth._do_refresh", return_value=new_token_data):
            with Session(mem_engine) as session:
                result = load_user_credentials(200, session)

        assert result is not None
        assert result["access_token"] == "new_access"

        # Verify DB row was updated
        with Session(mem_engine) as session:
            row = session.exec(
                select(UserIntegration)
                .where(UserIntegration.user_id == 200)
                .where(UserIntegration.provider == "spotify")
            ).first()
            updated = json.loads(decrypt_str(row.encrypted_credentials))
            assert updated["access_token"] == "new_access"

    def test_failed_refresh_returns_none(self, mem_engine):
        from app.integrations.spotify_auth import load_user_credentials

        expired_token = {
            "access_token": "old_access",
            "refresh_token": "bad_refresh",
            "client_id": "fake_client_id",
            "client_secret": "fake_client_secret",
            "expires_at": 0,
        }

        with Session(mem_engine) as session:
            existing = session.exec(
                select(UserIntegration)
                .where(UserIntegration.user_id == 201)
                .where(UserIntegration.provider == "spotify")
            ).first()
            if existing is None:
                session.add(UserIntegration(
                    user_id=201, provider="spotify",
                    encrypted_credentials=encrypt_str(json.dumps(expired_token)),
                    scopes="user-read-currently-playing",
                    connected_at=_utc_now(), is_active=True,
                ))
                session.commit()

        with patch("app.integrations.spotify_auth._do_refresh", return_value=None):
            with Session(mem_engine) as session:
                result = load_user_credentials(201, session)

        assert result is None

    def test_no_integration_row_returns_none(self, mem_engine):
        from app.integrations.spotify_auth import load_user_credentials

        with Session(mem_engine) as session:
            result = load_user_credentials(9999, session)

        assert result is None

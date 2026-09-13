"""Tests for guest access to voice/language/location/initiative settings.

Regression test for the 15-day bug (commit 1953534 removed 'voice' from
ADMIN_ONLY_TABS, exposing guests to 401 errors on 4 settings endpoints).

Fix (Option C, 2026-09-14):
  GET endpoints return 200 with schema defaults for guests.
  PUT endpoints keep 401 — guests can never persist changes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# GET endpoints — guests receive 200 with schema defaults
# ---------------------------------------------------------------------------

class TestGuestGetReturnsDefaults:

    def test_get_voice_guest_200(self) -> None:
        with _client() as c:
            resp = c.get("/settings/voice")
        assert resp.status_code == 200
        data = resp.json()
        assert "voice_response_mode" in data
        assert "voice_include_text" in data

    def test_get_language_guest_200(self) -> None:
        with _client() as c:
            resp = c.get("/settings/language")
        assert resp.status_code == 200
        data = resp.json()
        assert "language_override" in data

    def test_get_location_guest_200(self) -> None:
        with _client() as c:
            resp = c.get("/settings/location")
        assert resp.status_code == 200
        data = resp.json()
        assert "city" in data
        assert "source" in data

    def test_get_initiative_guest_200(self) -> None:
        with _client() as c:
            resp = c.get("/settings/initiative")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data


# ---------------------------------------------------------------------------
# PUT endpoints — guests are rejected with 401
# ---------------------------------------------------------------------------

class TestGuestPutRejected:

    def test_put_voice_guest_401(self) -> None:
        with _client() as c:
            resp = c.put("/settings/voice", json={
                "voice_response_mode": "always",
                "voice_include_text": True,
                "voice_long_response_action": "split",
                "audio_cleanup_days": 7,
                "tts_engine": "piper",
                "elevenlabs_chars_used": 0,
                "elevenlabs_daily_limit": 0,
                "model_upgrade_ttl_hours": 4,
            })
        assert resp.status_code == 401

    def test_put_language_guest_401(self) -> None:
        with _client() as c:
            resp = c.put("/settings/language", json={"language_override": "es-ES"})
        assert resp.status_code == 401

    def test_put_location_guest_401(self) -> None:
        with _client() as c:
            resp = c.put("/settings/location", json={"city": "Madrid", "source": "manual"})
        assert resp.status_code == 401

    def test_put_initiative_guest_401(self) -> None:
        with _client() as c:
            resp = c.put("/settings/initiative", json={
                "enabled": True,
                "trigger_conversation_abandoned": True,
                "trigger_long_inactivity": True,
                "trigger_open_loop": True,
            })
        assert resp.status_code == 401

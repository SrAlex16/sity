"""Tests for GET/PUT /settings/user-instructions and persona_engine injection.

Coverage:
  - GET as guest → 401
  - PUT as guest → 401
  - PUT + GET as registered user → persists correctly
  - Empty user_instructions → block NOT in generated system prompt
  - Non-empty user_instructions → block injected in system prompt
  - Value > 500 chars is trimmed server-side
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import make_user_token


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestUserInstructionsEndpoints:

    def test_guest_get_returns_401(self) -> None:
        with _client() as c:
            resp = c.get("/settings/user-instructions")
        assert resp.status_code == 401

    def test_guest_put_returns_401(self) -> None:
        with _client() as c:
            resp = c.put("/settings/user-instructions",
                         json={"user_instructions": "hola"})
        assert resp.status_code == 401

    def test_user_put_and_get_persists(self) -> None:
        token = make_user_token()
        text = "Soy desarrollador de software. Prefiero respuestas concisas."
        with _client() as c:
            put = c.put(
                "/settings/user-instructions",
                json={"user_instructions": text},
                cookies={"sity_session": token},
            )
            assert put.status_code == 200
            assert put.json()["user_instructions"] == text

            get = c.get(
                "/settings/user-instructions",
                cookies={"sity_session": token},
            )
            assert get.status_code == 200
            assert get.json()["user_instructions"] == text

    def test_value_trimmed_to_500_chars(self) -> None:
        token = make_user_token()
        long_text = "x" * 600
        with _client() as c:
            put = c.put(
                "/settings/user-instructions",
                json={"user_instructions": long_text},
                cookies={"sity_session": token},
            )
        assert put.status_code == 200
        assert len(put.json()["user_instructions"]) == 500

    def test_empty_string_clears_instructions(self) -> None:
        token = make_user_token()
        with _client() as c:
            c.put("/settings/user-instructions",
                  json={"user_instructions": "algo"},
                  cookies={"sity_session": token})
            put = c.put("/settings/user-instructions",
                        json={"user_instructions": ""},
                        cookies={"sity_session": token})
            assert put.status_code == 200
            get = c.get("/settings/user-instructions",
                        cookies={"sity_session": token})
        assert get.json()["user_instructions"] == ""


# ---------------------------------------------------------------------------
# Persona engine injection tests
# ---------------------------------------------------------------------------

class TestPersonaEngineInjection:
    """user_instructions appear in the system prompt iff non-empty."""

    def _build(self, user_instructions: str) -> str:
        from app.core.persona_engine import PersonaEngine
        from app.settings.settings_service import SettingsService
        from sqlmodel import Session, SQLModel, create_engine

        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(eng)
        with Session(eng) as db:
            svc = SettingsService(db)
            personality = svc.get_personality()
        decision = PersonaEngine().build_persona_prompt(
            personality,
            "hola",
            user_instructions=user_instructions,
        )
        return decision.system_prompt

    def test_empty_instructions_not_in_prompt(self) -> None:
        prompt = self._build("")
        assert "complementaria" not in prompt
        assert "usuario ha proporcionado" not in prompt

    def test_whitespace_only_not_in_prompt(self) -> None:
        prompt = self._build("   ")
        assert "complementaria" not in prompt

    def test_non_empty_injected_in_prompt(self) -> None:
        prompt = self._build("Soy desarrollador de software.")
        assert "Soy desarrollador de software." in prompt
        assert "complementaria" in prompt

    def test_injection_clamped_to_500_chars(self) -> None:
        long = "z" * 600
        prompt = self._build(long)
        # The injected text is clamped; 600 z's must not appear
        assert "z" * 600 not in prompt
        assert "z" * 500 in prompt

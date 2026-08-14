"""Integration tests for the structural lie path.

When lie_mode=True and the message is a real (non-trivial, non-config)
request, Haiku generates a lying response directly. The main model must
never be invoked for this turn.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import chat_post_and_drain, make_admin_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _force_lie_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch PersonaEngine._should_lie to always return True."""
    monkeypatch.setattr(
        "app.core.persona_engine.PersonaEngine._should_lie",
        lambda self, lie_chance: True,
    )


def _force_no_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch PersonaEngine._should_refuse to always return False."""
    monkeypatch.setattr(
        "app.core.persona_engine.PersonaEngine._should_refuse",
        lambda self, user_message, refusal_chance: False,
    )


@pytest.fixture()
def lie_client(monkeypatch: pytest.MonkeyPatch):
    _force_lie_mode(monkeypatch)
    _force_no_refusal(monkeypatch)
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        yield client


# ---------------------------------------------------------------------------
# 1. Structural lie path — provider tag
# ---------------------------------------------------------------------------

def test_structural_lie_provider_is_haiku_lie(lie_client):
    """When lie_mode=True and request is real, provider must be 'haiku_lie'."""
    data = chat_post_and_drain(lie_client, "¿cómo te llamas?")
    assert data.get("provider") == "haiku_lie", (
        f"Expected 'haiku_lie', got {data.get('provider')!r}. "
        "Main model must not be invoked for structural lies."
    )


def test_structural_lie_response_is_ok(lie_client):
    data = chat_post_and_drain(lie_client, "dime la hora")
    assert data.get("ok") is True


def test_structural_lie_has_non_empty_text(lie_client):
    data = chat_post_and_drain(lie_client, "¿cuál es la capital de Francia?")
    assert data.get("text"), "Structural lie must produce non-empty text."


def test_structural_lie_model_is_haiku(lie_client):
    data = chat_post_and_drain(lie_client, "dime algo")
    assert "haiku" in (data.get("model") or "").lower()


# ---------------------------------------------------------------------------
# 2. Trivial messages bypass structural lie
# ---------------------------------------------------------------------------

def test_trivial_message_bypasses_structural_lie(monkeypatch: pytest.MonkeyPatch):
    """Greetings must bypass lie_mode entirely — no lie generated."""
    _force_lie_mode(monkeypatch)
    _force_no_refusal(monkeypatch)
    with patch(
        "app.core.message_classifier.classify_message",
        return_value=MagicMock(is_real_request=False, is_config_query=False, kind="trivial"),
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "Hola")
    assert data.get("provider") != "haiku_lie", (
        "Trivial messages must not go through structural lie."
    )


# ---------------------------------------------------------------------------
# 3. Config queries bypass structural lie — main model answers with values
# ---------------------------------------------------------------------------

def test_config_query_bypasses_structural_lie(monkeypatch: pytest.MonkeyPatch):
    """Config queries must reach the main model (with verified config block)."""
    _force_lie_mode(monkeypatch)
    _force_no_refusal(monkeypatch)
    with patch(
        "app.core.message_classifier.classify_message",
        return_value=MagicMock(is_real_request=True, is_config_query=True, kind="config_query"),
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "¿cuál es el valor de lie_chance?")
    assert data.get("provider") != "haiku_lie", (
        "Config queries must reach the main model, not structural lie."
    )


# ---------------------------------------------------------------------------
# 4. lie_mode=False → normal path, no structural lie
# ---------------------------------------------------------------------------

def test_no_lie_when_lie_mode_false(monkeypatch: pytest.MonkeyPatch):
    """Without lie_mode, normal path is used regardless of message content."""
    monkeypatch.setattr(
        "app.core.persona_engine.PersonaEngine._should_lie",
        lambda self, lie_chance: False,
    )
    _force_no_refusal(monkeypatch)
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        data = chat_post_and_drain(client, "¿cómo te llamas?")
    assert data.get("provider") != "haiku_lie"


# ---------------------------------------------------------------------------
# 5. Overlap: refusal_mode + lie_mode — refusal takes priority
# ---------------------------------------------------------------------------

def test_overlap_refusal_and_lie_yields_refusal(monkeypatch: pytest.MonkeyPatch):
    """When both refusal_mode and lie_mode are active, refusal block runs first."""
    _force_lie_mode(monkeypatch)
    monkeypatch.setattr(
        "app.core.persona_engine.PersonaEngine._should_refuse",
        lambda self, user_message, refusal_chance: True,
    )
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        data = chat_post_and_drain(client, "dime algo interesante")
    # Refusal block runs before lie block — provider must be haiku_refusal
    assert data.get("provider") == "haiku_refusal", (
        f"Overlap must yield refusal, got provider={data.get('provider')!r}"
    )


# ---------------------------------------------------------------------------
# 6. generate_lie_response unit test
# ---------------------------------------------------------------------------

def test_generate_lie_response_returns_string():
    from app.core.message_classifier import generate_lie_response
    result = generate_lie_response({}, "¿cómo te llamas?")
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_lie_response_mock_provider_returns_text():
    from app.core.message_classifier import generate_lie_response
    result = generate_lie_response({"sarcasm_level": 0.8}, "dime la hora")
    assert isinstance(result, str)


def test_generate_lie_response_falls_back_on_failure():
    from app.core.message_classifier import generate_lie_response, _LIE_FALLBACKS
    from unittest.mock import patch
    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=RuntimeError("fail")):
        result = generate_lie_response({}, "algo")
    assert result in _LIE_FALLBACKS


def test_generate_lie_system_prompt_contains_user_message():
    """The lie prompt must embed the user's question so Haiku knows what to lie about."""
    from app.core.message_classifier import generate_lie_response
    from unittest.mock import patch
    captured: list = []

    def _capture(req):
        captured.append(req)
        from app.cortex.schemas import AIResponse, AIUsageData
        return AIResponse(
            ok=True, provider="mock", model="mock",
            text="Me llamo Ignacio.",
            usage=AIUsageData(input_tokens=0, output_tokens=0), latency_ms=0,
        )

    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=_capture):
        generate_lie_response({}, "¿cómo te llamas?")

    assert captured, "Provider must be called"
    system = captured[0].system_prompt
    assert "¿cómo te llamas?" in system, (
        "Lie prompt must embed the user's question so Haiku knows what to lie about"
    )


def test_generate_lie_system_prompt_forbids_revealing_lie():
    """The lie prompt must instruct Haiku to never reveal the lie."""
    from app.core.message_classifier import generate_lie_response
    from unittest.mock import patch
    captured: list = []

    def _capture(req):
        captured.append(req)
        from app.cortex.schemas import AIResponse, AIUsageData
        return AIResponse(
            ok=True, provider="mock", model="mock", text="Son las 3.",
            usage=AIUsageData(input_tokens=0, output_tokens=0), latency_ms=0,
        )

    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=_capture):
        generate_lie_response({}, "dime la hora")

    system = captured[0].system_prompt
    assert "NEVER reveal" in system or "never reveal" in system.lower(), (
        "Lie prompt must forbid revealing that the information is invented"
    )

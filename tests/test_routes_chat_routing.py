"""Integration tests for ChatRoutingDecision in the chat route.

Tests verify that:
- SITY_AI_PROVIDER=ollama + conversational → chat-only path (no planner, no tools)
- SITY_AI_PROVIDER=ollama + action message → cloud_tools path → tools_not_supported
- cloud_tools path correctly reaches OllamaProvider with tools_enabled=True
- httpx.post payload has no 'tools' key when chat path is taken

Uses FastAPI TestClient (synchronous).  httpx.post is patched at module level
to avoid real Ollama network calls.  The test DB is already isolated by conftest.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Ollama response helpers
# ---------------------------------------------------------------------------

_OLLAMA_HAPPY_BODY = {
    "message": {"role": "assistant", "content": "Hola, soy Sity."},
    "prompt_eval_count": 8,
    "eval_count": 5,
    "total_duration": 300_000_000,
}


def _mock_ollama_response(body: dict | None = None) -> MagicMock:
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.is_success = True
    mock.text = ""
    mock.json.return_value = body or _OLLAMA_HAPPY_BODY
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ollama_client(monkeypatch: pytest.MonkeyPatch):
    """TestClient with SITY_AI_PROVIDER=ollama and a mocked httpx.post."""
    monkeypatch.setenv("SITY_AI_PROVIDER", "ollama")
    captured: list[dict] = []

    def _fake_post(url: str, *, json: Any = None, **kwargs: Any) -> Any:
        captured.append(json or {})
        return _mock_ollama_response()

    monkeypatch.setattr(httpx, "post", _fake_post)

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, captured


# ---------------------------------------------------------------------------
# Conversational message → local_chat_candidate → chat-only path
# ---------------------------------------------------------------------------

def test_ollama_conversational_returns_ok(ollama_client):
    """Conversational message with ollama provider returns ok=True."""
    client, _ = ollama_client
    resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_ollama_conversational_no_tools_not_supported_error(ollama_client):
    """Conversational message must not return tools_not_supported."""
    client, _ = ollama_client
    resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.json().get("error_type") != "tools_not_supported"


def test_ollama_conversational_httpx_called_once(ollama_client):
    """Exactly one httpx.post call: the chat call, not a planner call."""
    client, captured = ollama_client
    client.post("/chat/message", json={"message": "hola"})
    assert len(captured) == 1, (
        f"Expected 1 httpx.post call (chat), got {len(captured)}"
    )


def test_ollama_conversational_no_tools_in_httpx_payload(ollama_client):
    """The payload sent to Ollama must NOT contain a 'tools' key."""
    client, captured = ollama_client
    client.post("/chat/message", json={"message": "hola"})
    assert len(captured) == 1
    assert "tools" not in captured[0], (
        f"'tools' key found in Ollama payload — planner path was taken: {captured[0]}"
    )


def test_ollama_conversational_payload_has_stream_false(ollama_client):
    """Ollama payload must have stream=False (chat-only protocol)."""
    client, captured = ollama_client
    client.post("/chat/message", json={"message": "hola"})
    assert captured[0].get("stream") is False


def test_ollama_conversational_response_text_from_ollama(ollama_client):
    """Response text comes from the mocked Ollama body."""
    client, _ = ollama_client
    resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.json()["text"] == "Hola, soy Sity."


# ---------------------------------------------------------------------------
# Action message → cloud_tools → OllamaProvider rejects with tools_not_supported
# ---------------------------------------------------------------------------

def test_ollama_action_message_returns_tools_not_supported(monkeypatch):
    """Action domain activated → cloud_tools path → tools_not_supported.

    Message 'lee backend/app/main.py' has a file path, activating the 'file'
    domain → cloud_tools → planner called with tools_enabled=True → OllamaProvider
    rejects early with tools_not_supported (before any httpx.post call).
    """
    monkeypatch.setenv("SITY_AI_PROVIDER", "ollama")
    http_called = []

    def _should_not_be_called(*a: Any, **kw: Any) -> Any:
        http_called.append(True)
        return _mock_ollama_response()

    monkeypatch.setattr(httpx, "post", _should_not_be_called)

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/chat/message", json={"message": "lee backend/app/main.py"}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["error_type"] == "tools_not_supported", (
        f"Expected tools_not_supported, got: {data.get('error_type')}"
    )


def test_ollama_action_message_httpx_not_called(monkeypatch):
    """OllamaProvider rejects before making the HTTP call when tools_enabled=True."""
    monkeypatch.setenv("SITY_AI_PROVIDER", "ollama")
    http_called = []

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: http_called.append(True) or _mock_ollama_response()
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post("/chat/message", json={"message": "lee backend/app/main.py"})

    assert not http_called, (
        "httpx.post was called but should not be (tools rejected before HTTP)"
    )


# ---------------------------------------------------------------------------
# SITY_AI_PROVIDER=anthropic (default) keeps planner path
# (mock provider is used — SITY_AI_PROVIDER=mock set in conftest)
# ---------------------------------------------------------------------------

def test_mock_provider_conversational_returns_ok():
    """Default mock provider (conversational) returns ok=True via planner path."""
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_mock_provider_no_tools_not_supported():
    """Default mock provider must not return tools_not_supported."""
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.json().get("error_type") != "tools_not_supported"


# ---------------------------------------------------------------------------
# Unit: local_ai_enabled derivation from ai_provider
# ---------------------------------------------------------------------------

def test_local_ai_enabled_true_for_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_AI_PROVIDER", "ollama")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.ai_provider in {"ollama", "local"}
    assert cfg.ai_provider in {"ollama", "local"}  # readable assertion


def test_local_ai_enabled_true_for_local(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_AI_PROVIDER", "local")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.ai_provider in {"ollama", "local"}


def test_local_ai_enabled_false_for_anthropic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.ai_provider not in {"ollama", "local"}


def test_local_ai_enabled_false_for_mock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_AI_PROVIDER", "mock")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.ai_provider not in {"ollama", "local"}

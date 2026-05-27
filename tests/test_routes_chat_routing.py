"""Integration tests for ChatRoutingDecision in the chat route.

Architecture: hybrid provider model.
  - SITY_AI_PROVIDER       = cloud provider (anthropic / mock).  Tools + planner always use this.
  - SITY_LOCAL_AI_ENABLED  = true → enables local routing for conversational turns.
  - SITY_LOCAL_AI_PROVIDER = ollama → which local backend to use (default).

Tests verify:
  - SITY_LOCAL_AI_ENABLED=true + conversational → local_chat_candidate → chat-only (Ollama) path.
  - SITY_LOCAL_AI_ENABLED=true + action message → cloud_tools path (planner/mock, NOT Ollama).
  - Ollama httpx.post payload has no 'tools' key when chat path is taken.
  - Default (SITY_LOCAL_AI_ENABLED not set) routes through cloud planner (mock).

Uses FastAPI TestClient (synchronous). httpx.post is patched at module level to avoid real
Ollama network calls. The test DB is already isolated by conftest.
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
def local_ai_client(monkeypatch: pytest.MonkeyPatch):
    """TestClient with local AI enabled (Ollama) and a mocked httpx.post.

    Cloud provider stays as 'mock' (set by conftest).
    Local provider is 'ollama', backed by patched httpx.post.
    """
    monkeypatch.setenv("SITY_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("SITY_LOCAL_AI_PROVIDER", "ollama")
    captured: list[dict] = []

    def _fake_post(url: str, *, json: Any = None, **kwargs: Any) -> Any:
        captured.append(json or {})
        return _mock_ollama_response()

    monkeypatch.setattr(httpx, "post", _fake_post)

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, captured


# ---------------------------------------------------------------------------
# Conversational message → local_chat_candidate → Ollama chat path
# ---------------------------------------------------------------------------

def test_local_ai_conversational_returns_ok(local_ai_client):
    """Conversational message with local AI enabled returns ok=True."""
    client, _ = local_ai_client
    resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_local_ai_conversational_no_tools_not_supported(local_ai_client):
    """Conversational message must not return tools_not_supported."""
    client, _ = local_ai_client
    resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.json().get("error_type") != "tools_not_supported"


def test_local_ai_conversational_httpx_called_once(local_ai_client):
    """Exactly one httpx.post call: the Ollama chat call, not a planner call."""
    client, captured = local_ai_client
    client.post("/chat/message", json={"message": "hola"})
    assert len(captured) == 1, (
        f"Expected 1 httpx.post call (local chat), got {len(captured)}"
    )


def test_local_ai_conversational_no_tools_in_httpx_payload(local_ai_client):
    """The payload sent to Ollama must NOT contain a 'tools' key."""
    client, captured = local_ai_client
    client.post("/chat/message", json={"message": "hola"})
    assert len(captured) == 1
    assert "tools" not in captured[0], (
        f"'tools' key found in Ollama payload — planner path was taken: {captured[0]}"
    )


def test_local_ai_conversational_payload_has_stream_false(local_ai_client):
    """Ollama payload must have stream=False (chat-only protocol)."""
    client, captured = local_ai_client
    client.post("/chat/message", json={"message": "hola"})
    assert captured[0].get("stream") is False


def test_local_ai_conversational_response_text_from_ollama(local_ai_client):
    """Response text comes from the mocked Ollama body."""
    client, _ = local_ai_client
    resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.json()["text"] == "Hola, soy Sity."


# ---------------------------------------------------------------------------
# Action message → cloud_tools → cloud (mock) provider, NOT Ollama
# ---------------------------------------------------------------------------

def test_local_ai_action_message_ollama_not_called(monkeypatch):
    """Action domain activated → cloud_tools → Ollama httpx.post is NOT called.

    'lee backend/app/main.py' has a file path → file domain activated → cloud_tools.
    Cloud provider is mock (conftest default) — it handles the planner turn.
    Ollama is configured but must stay idle.
    """
    monkeypatch.setenv("SITY_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("SITY_LOCAL_AI_PROVIDER", "ollama")
    ollama_called = []

    def _should_not_be_called(*a: Any, **kw: Any) -> Any:
        ollama_called.append(True)
        return _mock_ollama_response()

    monkeypatch.setattr(httpx, "post", _should_not_be_called)

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/chat/message", json={"message": "lee backend/app/main.py"}
        )

    assert resp.status_code == 200
    assert not ollama_called, (
        "Ollama httpx.post was called for an action message — should use cloud path"
    )


def test_local_ai_action_message_no_tools_not_supported(monkeypatch):
    """Action domain + local AI enabled must NOT return tools_not_supported.

    cloud_tools path uses mock provider (cloud), which supports tools.
    Ollama is never called, so tools_not_supported never fires.
    """
    monkeypatch.setenv("SITY_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("SITY_LOCAL_AI_PROVIDER", "ollama")
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: _mock_ollama_response()  # guard — should not be reached
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/chat/message", json={"message": "lee backend/app/main.py"}
        )

    assert resp.status_code == 200
    assert resp.json().get("error_type") != "tools_not_supported", (
        f"Got tools_not_supported — action message was routed to Ollama: {resp.json()}"
    )


# ---------------------------------------------------------------------------
# SITY_LOCAL_AI_ENABLED not set (default) → cloud planner path (mock provider)
# ---------------------------------------------------------------------------

def test_default_cloud_provider_conversational_returns_ok():
    """Default (no local AI) conversational → cloud (mock) → ok=True."""
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_default_cloud_provider_no_tools_not_supported():
    """Default (no local AI) conversational must not return tools_not_supported."""
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/chat/message", json={"message": "hola"})
    assert resp.json().get("error_type") != "tools_not_supported"


def test_default_cloud_provider_ollama_not_called(monkeypatch):
    """SITY_LOCAL_AI_ENABLED not set → Ollama httpx.post is never called."""
    # Ensure local AI is disabled
    monkeypatch.delenv("SITY_LOCAL_AI_ENABLED", raising=False)
    ollama_called = []

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **kw: ollama_called.append(True) or _mock_ollama_response()
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post("/chat/message", json={"message": "hola"})

    assert not ollama_called, (
        "Ollama was called but SITY_LOCAL_AI_ENABLED is not set"
    )


# ---------------------------------------------------------------------------
# Unit: RuntimeConfig fields for local AI
# ---------------------------------------------------------------------------

def test_local_ai_enabled_true_when_env_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_LOCAL_AI_ENABLED", "true")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.local_ai_enabled is True


def test_local_ai_enabled_false_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SITY_LOCAL_AI_ENABLED", raising=False)
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.local_ai_enabled is False


def test_local_ai_provider_default_is_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SITY_LOCAL_AI_PROVIDER", raising=False)
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.local_ai_provider == "ollama"


def test_local_ai_provider_reads_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SITY_LOCAL_AI_PROVIDER", "local")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.local_ai_provider == "local"


def test_cloud_ai_provider_unaffected_by_local_flag(monkeypatch: pytest.MonkeyPatch):
    """SITY_LOCAL_AI_ENABLED does not change SITY_AI_PROVIDER."""
    monkeypatch.setenv("SITY_LOCAL_AI_ENABLED", "true")
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")
    from app.core.runtime_config import get_runtime_config
    cfg = get_runtime_config()
    assert cfg.ai_provider == "anthropic"
    assert cfg.local_ai_enabled is True


# ---------------------------------------------------------------------------
# Unit: ProviderCallRunner.run_local_chat with no local_provider
# ---------------------------------------------------------------------------

def test_run_local_chat_no_provider_returns_error():
    """run_local_chat with local_provider=None returns a controlled error."""
    from app.chat.provider_call_runner import ProviderCallRunner
    from app.cortex.ai_gateway import AIGateway
    from app.settings.config_loader import load_default_config

    config = load_default_config()
    runner = ProviderCallRunner(AIGateway(config=config), local_provider=None)

    from app.cortex.schemas import AIRequest
    req = AIRequest(
        trace_id="test",
        task_type="chat",
        system_prompt="sys",
        user_message="hello",
        tools=[],
        tools_enabled=False,
        max_tokens=100,
    )
    resp = runner.run_local_chat(req)
    assert resp.ok is False
    assert resp.error_type == "provider_not_configured"

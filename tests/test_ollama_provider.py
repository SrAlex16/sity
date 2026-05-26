"""Tests for OllamaProvider v1 (chat-only, httpx-based) and its factory registration."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.cortex.ollama_provider import OllamaProvider
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest


def _minimal_request(**kwargs: Any) -> AIRequest:
    defaults: dict[str, Any] = dict(
        trace_id="trc_test",
        task_type="chat_message",
        system_prompt="Test.",
        user_message="Hola.",
        max_tokens=100,
        tools_enabled=False,
    )
    defaults.update(kwargs)
    return AIRequest(**defaults)


def _mock_response(
    *,
    status_code: int = 200,
    body: dict | None = None,
    raw_text: str | None = None,
) -> MagicMock:
    """Build a minimal fake httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.is_success = (200 <= status_code < 300)
    mock.text = raw_text or ""
    if body is not None:
        mock.json.return_value = body
    else:
        mock.json.side_effect = ValueError("invalid JSON")
    return mock


_HAPPY_BODY = {
    "message": {"role": "assistant", "content": "Hola, ¿cómo estás?"},
    "prompt_eval_count": 12,
    "eval_count": 8,
    "total_duration": 500_000_000,  # 500 ms in nanoseconds
}


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------

def test_factory_ollama_returns_ollama_provider() -> None:
    assert isinstance(build_ai_provider("ollama", model="llama3"), OllamaProvider)


def test_factory_local_returns_ollama_provider() -> None:
    assert isinstance(build_ai_provider("local", model="llama3"), OllamaProvider)


def test_ollama_provider_attributes() -> None:
    provider = build_ai_provider("ollama", model="llama3.2:3b")
    assert provider.name == "ollama"
    assert provider.model == "llama3.2:3b"


# ---------------------------------------------------------------------------
# Happy path — successful generate()
# ---------------------------------------------------------------------------

def test_generate_happy_path_ok_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is True


def test_generate_happy_path_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.text == "Hola, ¿cómo estás?"


def test_generate_happy_path_provider_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.provider == "ollama"


def test_generate_happy_path_usage_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 8


def test_generate_happy_path_latency_from_total_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request())
    # total_duration=500_000_000 ns → 500 ms
    assert response.latency_ms == 500


def test_generate_happy_path_model_in_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3.2").generate(_minimal_request())
    assert response.model == "llama3.2"


def test_generate_happy_path_system_prompt_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def _capture(url: str, **kwargs: Any) -> Any:
        captured.append(kwargs.get("json", {}))
        return _mock_response(body=_HAPPY_BODY)

    monkeypatch.setattr(httpx, "post", _capture)
    OllamaProvider("llama3").generate(_minimal_request(system_prompt="Eres Sity."))
    messages = captured[0]["messages"]
    assert messages[0] == {"role": "system", "content": "Eres Sity."}
    assert messages[1]["role"] == "user"


def test_generate_no_system_prompt_single_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def _capture(url: str, **kwargs: Any) -> Any:
        captured.append(kwargs.get("json", {}))
        return _mock_response(body=_HAPPY_BODY)

    monkeypatch.setattr(httpx, "post", _capture)
    OllamaProvider("llama3").generate(_minimal_request(system_prompt=""))
    messages = captured[0]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


# ---------------------------------------------------------------------------
# SITY_OLLAMA_MODEL env override
# ---------------------------------------------------------------------------

def test_env_model_override_used_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "mistral:7b")
    captured: list[dict] = []

    def _capture(url: str, **kwargs: Any) -> Any:
        captured.append(kwargs.get("json", {}))
        return _mock_response(body=_HAPPY_BODY)

    monkeypatch.setattr(httpx, "post", _capture)
    OllamaProvider("llama3").generate(_minimal_request())
    assert captured[0]["model"] == "mistral:7b"


def test_env_model_override_reflected_in_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "mistral:7b")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.model == "mistral:7b"


# ---------------------------------------------------------------------------
# Tool requests blocked before HTTP
# ---------------------------------------------------------------------------

def test_tools_enabled_no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http_called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: http_called.append(True) or _mock_response(body=_HAPPY_BODY))
    OllamaProvider("llama3").generate(_minimal_request(tools_enabled=True))
    assert not http_called


def test_tools_enabled_returns_tools_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request(tools_enabled=True))
    assert response.ok is False
    assert response.error_type == "tools_not_supported"


def test_tools_list_nonempty_no_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http_called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: http_called.append(True) or _mock_response(body=_HAPPY_BODY))
    OllamaProvider("llama3").generate(_minimal_request(tools=[{"name": "web_search"}]))
    assert not http_called


def test_tools_list_nonempty_returns_tools_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=_HAPPY_BODY))
    response = OllamaProvider("llama3").generate(_minimal_request(tools=[{"name": "web_search"}]))
    assert response.ok is False
    assert response.error_type == "tools_not_supported"


# ---------------------------------------------------------------------------
# Network errors → provider_unavailable
# ---------------------------------------------------------------------------

def test_transport_error_returns_provider_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: Any, **kw: Any) -> Any:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_unavailable"


def test_timeout_returns_provider_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: Any, **kw: Any) -> Any:
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", _raise)
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_unavailable"


def test_provider_unavailable_includes_url_in_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: Any, **kw: Any) -> Any:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert "/api/chat" in response.error_message or "11434" in response.error_message


# ---------------------------------------------------------------------------
# HTTP error responses → provider_error
# ---------------------------------------------------------------------------

def test_http_500_returns_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(status_code=500, raw_text="Internal Error"))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_error"


def test_http_404_returns_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(status_code=404, raw_text="Not Found"))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_error"


def test_http_error_includes_status_code_in_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(status_code=500, raw_text="Boom"))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert "500" in response.error_message


# ---------------------------------------------------------------------------
# Invalid JSON → provider_error
# ---------------------------------------------------------------------------

def test_invalid_json_returns_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(status_code=200, raw_text="not json"))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_error"


# ---------------------------------------------------------------------------
# Missing message.content → provider_error
# ---------------------------------------------------------------------------

def test_missing_message_content_returns_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"model": "llama3", "message": {"role": "assistant"}}  # no "content" key
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=body))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_error"


def test_missing_message_key_returns_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"model": "llama3"}  # no "message" key at all
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _mock_response(body=body))
    response = OllamaProvider("llama3").generate(_minimal_request())
    assert response.ok is False
    assert response.error_type == "provider_error"


# ---------------------------------------------------------------------------
# generate_with_tool_results → tools_not_supported
# ---------------------------------------------------------------------------

def test_generate_with_tool_results_returns_tools_not_supported() -> None:
    response = OllamaProvider("llama3").generate_with_tool_results(
        request=_minimal_request(),
        first_response_content=[],
        tool_results=[],
    )
    assert response.ok is False
    assert response.error_type == "tools_not_supported"


# ---------------------------------------------------------------------------
# generate_micro_reaction — returns empty text (triggers static fallback)
# ---------------------------------------------------------------------------

def test_generate_micro_reaction_returns_dict() -> None:
    result = OllamaProvider("llama3").generate_micro_reaction(
        messages=[{"role": "user", "content": "test"}],
        system="",
        max_tokens=50,
    )
    assert isinstance(result, dict)
    assert "text" in result


def test_generate_micro_reaction_empty_text_triggers_fallback() -> None:
    result = OllamaProvider("llama3").generate_micro_reaction(messages=[], system="", max_tokens=50)
    assert result["text"] == ""


# ---------------------------------------------------------------------------
# Unknown provider still raises ValueError
# ---------------------------------------------------------------------------

def test_unknown_provider_still_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown AI provider"):
        build_ai_provider("openai", model="gpt-4")


# ---------------------------------------------------------------------------
# AIGateway integration — error_type preserved end-to-end
# ---------------------------------------------------------------------------

def test_gateway_with_ollama_provider_no_tools_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SITY_AI_PROVIDER=ollama with no Ollama running → provider_unavailable."""
    monkeypatch.setenv("SITY_AI_PROVIDER", "ollama")

    def _raise(*a: Any, **kw: Any) -> Any:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", _raise)

    from app.cortex.ai_gateway import AIGateway
    gateway = AIGateway({})
    response = gateway.generate(_minimal_request())

    assert response.ok is False
    assert response.error_type == "provider_unavailable"


def test_gateway_generate_with_tool_results_ollama_tools_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SITY_AI_PROVIDER", "ollama")

    from app.cortex.ai_gateway import AIGateway
    gateway = AIGateway({})
    response = gateway.generate_with_tool_results(
        request=_minimal_request(),
        first_response_content=[],
        tool_results=[],
    )

    assert response.ok is False
    assert response.error_type == "tools_not_supported"

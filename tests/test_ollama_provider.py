"""Tests for OllamaProvider skeleton and its factory registration."""
from __future__ import annotations

import pytest

from app.cortex.ollama_provider import OllamaProvider
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest


def _minimal_request() -> AIRequest:
    return AIRequest(
        trace_id="trc_test",
        task_type="chat_message",
        system_prompt="Test.",
        user_message="Hola.",
        max_tokens=100,
        tools_enabled=False,
    )


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------

def test_factory_ollama_returns_ollama_provider() -> None:
    provider = build_ai_provider("ollama", model="llama3")
    assert isinstance(provider, OllamaProvider)


def test_factory_local_returns_ollama_provider() -> None:
    """'local' is an alias for the Ollama/local provider."""
    provider = build_ai_provider("local", model="llama3")
    assert isinstance(provider, OllamaProvider)


def test_ollama_provider_attributes() -> None:
    provider = build_ai_provider("ollama", model="llama3.2:3b")
    assert provider.name == "ollama"
    assert provider.model == "llama3.2:3b"


# ---------------------------------------------------------------------------
# generate — returns controlled error, no uncaught exception
# ---------------------------------------------------------------------------

def test_generate_returns_error_response_not_exception() -> None:
    provider = OllamaProvider(model="llama3")
    response = provider.generate(_minimal_request())
    assert response.ok is False


def test_generate_error_type_is_provider_not_configured() -> None:
    provider = OllamaProvider(model="llama3")
    response = provider.generate(_minimal_request())
    assert response.error_type == "provider_not_configured"


def test_generate_error_message_is_informative() -> None:
    provider = OllamaProvider(model="llama3")
    response = provider.generate(_minimal_request())
    assert response.error_message is not None
    assert "skeleton" in response.error_message.lower() or "not implemented" in response.error_message.lower()


def test_generate_with_tool_results_returns_error_response() -> None:
    provider = OllamaProvider(model="llama3")
    response = provider.generate_with_tool_results(
        request=_minimal_request(),
        first_response_content=[],
        tool_results=[],
    )
    assert response.ok is False
    assert response.error_type == "provider_not_configured"


# ---------------------------------------------------------------------------
# generate_micro_reaction — returns empty text (triggers static fallback)
# ---------------------------------------------------------------------------

def test_generate_micro_reaction_returns_dict() -> None:
    provider = OllamaProvider(model="llama3")
    result = provider.generate_micro_reaction(
        messages=[{"role": "user", "content": "test"}],
        system="",
        max_tokens=50,
    )
    assert isinstance(result, dict)
    assert "text" in result


def test_generate_micro_reaction_empty_text_triggers_fallback() -> None:
    """Empty text causes micro_reactions.py to use its static fallback table."""
    provider = OllamaProvider(model="llama3")
    result = provider.generate_micro_reaction(messages=[], system="", max_tokens=50)
    assert result["text"] == ""


# ---------------------------------------------------------------------------
# Unknown provider still raises ValueError
# ---------------------------------------------------------------------------

def test_unknown_provider_still_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown AI provider"):
        build_ai_provider("openai", model="gpt-4")

"""Tests for app.cortex.providers.factory.build_ai_provider.

The "anthropic" test patches ANTHROPIC_API_KEY so ClaudeProvider can be
instantiated without an actual key. No network calls are made — the
Anthropic SDK client does not connect until a request is issued.
"""
from __future__ import annotations

import pytest

from app.cortex.providers.factory import build_ai_provider
from app.cortex.mock_provider import MockProvider
from app.cortex.claude_provider import ClaudeProvider


def test_mock_provider_returns_mock_instance() -> None:
    provider = build_ai_provider("mock", model="mock")
    assert isinstance(provider, MockProvider)


def test_mock_provider_attributes() -> None:
    provider = build_ai_provider("mock", model="mock")
    assert provider.name == "mock"
    assert provider.model == "mock"


def test_mock_provider_case_insensitive() -> None:
    """Provider name matching is case-insensitive."""
    assert isinstance(build_ai_provider("MOCK", model="mock"), MockProvider)
    assert isinstance(build_ai_provider("Mock", model="mock"), MockProvider)


def test_anthropic_provider_returns_claude_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """ClaudeProvider is returned for 'anthropic'. No network call is made."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    provider = build_ai_provider("anthropic", model="claude-haiku-4-5-20251001")
    assert isinstance(provider, ClaudeProvider)


def test_anthropic_provider_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    provider = build_ai_provider("anthropic", model="claude-haiku-4-5-20251001")
    assert provider.name == "anthropic"
    assert provider.model == "claude-haiku-4-5-20251001"


def test_unknown_provider_raises_value_error() -> None:
    """Unknown provider names raise ValueError immediately.

    Previously AIGateway fell back silently to ClaudeProvider for any
    unrecognised SITY_AI_PROVIDER value. The factory makes this explicit
    so misconfiguration is caught at startup rather than at request time.
    """
    with pytest.raises(ValueError, match="Unknown AI provider"):
        build_ai_provider("ollama", model="llama3")


def test_unknown_provider_error_lists_known_providers() -> None:
    with pytest.raises(ValueError, match="anthropic"):
        build_ai_provider("something_else", model="x")

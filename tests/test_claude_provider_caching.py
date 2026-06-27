"""Tests for prompt caching in ClaudeProvider.

Verifies that:
- _tools_with_cache marks only the last tool with cache_control.
- generate() sends system as a list with cache_control.
- _to_ai_response extracts cache token counts from message.usage.

No real API calls are made — client.messages.create is mocked.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.cortex.claude_provider import ClaudeProvider, _tools_with_cache
from app.cortex.schemas import AIRequest


# ---------------------------------------------------------------------------
# _tools_with_cache
# ---------------------------------------------------------------------------

def test_tools_with_cache_empty_returns_empty() -> None:
    assert _tools_with_cache([]) == []


def test_tools_with_cache_single_tool_gets_marker() -> None:
    tools = [{"name": "foo", "description": "bar"}]
    result = _tools_with_cache(tools)
    assert result[0]["cache_control"] == {"type": "ephemeral"}


def test_tools_with_cache_only_last_tool_gets_marker() -> None:
    tools = [
        {"name": "a"},
        {"name": "b"},
        {"name": "c"},
    ]
    result = _tools_with_cache(tools)
    assert "cache_control" not in result[0]
    assert "cache_control" not in result[1]
    assert result[2]["cache_control"] == {"type": "ephemeral"}


def test_tools_with_cache_does_not_mutate_original() -> None:
    tools = [{"name": "x"}, {"name": "y"}]
    _tools_with_cache(tools)
    assert "cache_control" not in tools[-1]


def test_tools_with_cache_preserves_existing_fields() -> None:
    tools = [{"name": "a", "description": "desc", "input_schema": {}}]
    result = _tools_with_cache(tools)
    assert result[0]["name"] == "a"
    assert result[0]["description"] == "desc"
    assert result[0]["input_schema"] == {}


# ---------------------------------------------------------------------------
# generate — system prompt caching
# ---------------------------------------------------------------------------

def _make_provider(monkeypatch: pytest.MonkeyPatch) -> ClaudeProvider:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return ClaudeProvider(model="claude-haiku-4-5-20251001")


def _make_fake_message(*, text: str = "ok") -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_creation_input_tokens=100,
        cache_read_input_tokens=50,
    )
    return SimpleNamespace(content=[block], usage=usage)


def _make_request(**kwargs) -> AIRequest:
    defaults = dict(
        trace_id="t1",
        task_type="chat",
        system_prompt="You are Sity.",
        user_message="Hello",
        max_tokens=100,
        tools_enabled=True,
        tools=[{"name": "tool_a"}, {"name": "tool_b"}],
    )
    defaults.update(kwargs)
    return AIRequest(**defaults)


def test_generate_system_is_list_with_cache_control(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_msg = _make_fake_message()

    with patch.object(provider.client.messages, "create", return_value=fake_msg) as mock_create:
        provider.generate(_make_request())

    call_kwargs = mock_create.call_args.kwargs
    system = call_kwargs["system"]
    assert isinstance(system, list), "system must be a list for caching"
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "You are Sity."
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_generate_tools_last_has_cache_control(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_msg = _make_fake_message()

    with patch.object(provider.client.messages, "create", return_value=fake_msg) as mock_create:
        provider.generate(_make_request())

    tools = mock_create.call_args.kwargs["tools"]
    assert "cache_control" not in tools[0]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}


def test_generate_with_tool_results_system_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_msg = _make_fake_message()
    request = _make_request()

    with patch.object(provider.client.messages, "create", return_value=fake_msg) as mock_create:
        provider.generate_with_tool_results(
            request=request,
            first_response_content=[],
            tool_results=[],
        )

    system = mock_create.call_args.kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# _to_ai_response — cache token extraction
# ---------------------------------------------------------------------------

def test_cache_tokens_extracted_into_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_msg = _make_fake_message()

    with patch.object(provider.client.messages, "create", return_value=fake_msg):
        response = provider.generate(_make_request())

    assert response.usage.cache_creation_tokens == 100
    assert response.usage.cache_read_tokens == 50


def test_cache_tokens_default_to_zero_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    block = SimpleNamespace(type="text", text="hi")
    usage = SimpleNamespace(input_tokens=5, output_tokens=3)
    fake_msg = SimpleNamespace(content=[block], usage=usage)

    with patch.object(provider.client.messages, "create", return_value=fake_msg):
        response = provider.generate(_make_request())

    assert response.usage.cache_creation_tokens == 0
    assert response.usage.cache_read_tokens == 0

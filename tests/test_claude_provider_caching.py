"""Tests for prompt caching in ClaudeProvider.

Verifies that:
- _tools_with_cache marks only the last tool with cache_control.
- generate() sends system as a list with cache_control.
- _to_ai_response extracts cache token counts from message.usage.

No real API calls are made — client.messages.stream is mocked as a context manager.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.cortex.claude_provider import ClaudeProvider, _messages_with_history_cache, _tools_with_cache
from app.cortex.schemas import AIRequest


class _FakeStream:
    """Minimal context-manager stream that yields nothing and returns a fake final message."""

    def __init__(self, message: SimpleNamespace) -> None:
        self._message = message
        self.call_kwargs: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        return iter([])

    def get_final_message(self):
        return self._message


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
    fake_stream = _FakeStream(_make_fake_message())

    with patch.object(provider.client.messages, "stream", return_value=fake_stream) as mock_stream:
        provider.generate(_make_request())

    call_kwargs = mock_stream.call_args.kwargs
    system = call_kwargs["system"]
    assert isinstance(system, list), "system must be a list for caching"
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "You are Sity."
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_generate_tools_last_has_cache_control(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_stream = _FakeStream(_make_fake_message())

    with patch.object(provider.client.messages, "stream", return_value=fake_stream) as mock_stream:
        provider.generate(_make_request())

    tools = mock_stream.call_args.kwargs["tools"]
    assert "cache_control" not in tools[0]
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}


def test_generate_with_tool_results_system_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_stream = _FakeStream(_make_fake_message())
    request = _make_request()

    with patch.object(provider.client.messages, "stream", return_value=fake_stream) as mock_stream:
        provider.generate_with_tool_results(
            request=request,
            first_response_content=[],
            tool_results=[],
        )

    system = mock_stream.call_args.kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# _to_ai_response — cache token extraction
# ---------------------------------------------------------------------------

def test_cache_tokens_extracted_into_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    fake_stream = _FakeStream(_make_fake_message())

    with patch.object(provider.client.messages, "stream", return_value=fake_stream):
        response = provider.generate(_make_request())

    assert response.usage.cache_creation_tokens == 100
    assert response.usage.cache_read_tokens == 50


# ---------------------------------------------------------------------------
# _messages_with_history_cache
# ---------------------------------------------------------------------------

def test_history_cache_empty_returns_empty() -> None:
    assert _messages_with_history_cache([], "hello") == []


def test_history_cache_string_content_converted_to_block() -> None:
    prior = [{"role": "user", "content": "previous message"}]
    result = _messages_with_history_cache(prior, "new")
    last_content = result[-1]["content"]
    assert isinstance(last_content, list)
    assert last_content[-1]["type"] == "text"
    assert last_content[-1]["text"] == "previous message"
    assert last_content[-1]["cache_control"] == {"type": "ephemeral"}


def test_history_cache_list_content_marks_last_block() -> None:
    prior = [
        {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    ]
    result = _messages_with_history_cache(prior, "new")
    content = result[-1]["content"]
    assert "cache_control" not in content[0]
    assert content[-1]["cache_control"] == {"type": "ephemeral"}
    assert content[-1]["text"] == "b"


def test_history_cache_only_last_message_marked() -> None:
    prior = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    result = _messages_with_history_cache(prior, "new")
    # First two messages untouched (string content preserved as-is)
    assert result[0]["content"] == "first"
    assert result[1]["content"] == "second"
    # Only last is converted and marked
    assert isinstance(result[2]["content"], list)
    assert result[2]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_history_cache_does_not_mutate_original() -> None:
    prior = [{"role": "user", "content": "original"}]
    _messages_with_history_cache(prior, "new")
    assert prior[0]["content"] == "original"


def test_history_cache_preserves_list_block_fields() -> None:
    prior = [{"role": "user", "content": [{"type": "text", "text": "hello", "extra": "field"}]}]
    result = _messages_with_history_cache(prior, "new")
    block = result[-1]["content"][-1]
    assert block["text"] == "hello"
    assert block["extra"] == "field"
    assert block["cache_control"] == {"type": "ephemeral"}


def test_cache_tokens_default_to_zero_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _make_provider(monkeypatch)
    block = SimpleNamespace(type="text", text="hi")
    usage = SimpleNamespace(input_tokens=5, output_tokens=3)
    fake_msg = SimpleNamespace(content=[block], usage=usage)

    with patch.object(provider.client.messages, "stream", return_value=_FakeStream(fake_msg)):
        response = provider.generate(_make_request())

    assert response.usage.cache_creation_tokens == 0
    assert response.usage.cache_read_tokens == 0

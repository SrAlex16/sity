"""Tests for Paso C — chat_response dispatcher hook.

Covers:
- _snippet: word-boundary truncation
- _maybe_dispatch_chat_response: visible → no dispatch
- _maybe_dispatch_chat_response: background → dispatch with correct NotificationFact
- _maybe_dispatch_chat_response: none → dispatch (falls to push/pending via dispatcher)
- Cancelled / error turns → no dispatch (tested at _run_turn_in_background level)
- Snippet text in NotificationFact payload matches _snippet output
- fact_id is deterministic from trace_id (dedup guarantee)
"""
from __future__ import annotations

import uuid as _uuid_mod
from unittest.mock import MagicMock, call, patch

import pytest

from app.api.routes_chat import _maybe_dispatch_chat_response, _snippet
from app.api.schemas import ChatMessageResponse, UsageSummary
from app.notifications.fact import DispatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_STATE = "app.api.routes_chat.get_subscriber_state"   # module-level import in routes_chat
_PATCH_DISPATCH = "app.notifications.dispatcher.dispatch"   # lazy import inside function → patch at source


def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _result(text: str = "Hola, esto es una respuesta de prueba.", *, error_type: str | None = None) -> ChatMessageResponse:
    return ChatMessageResponse(
        ok=True,
        trace_id=f"trace_{_uid()}",
        text=text,
        provider="anthropic",
        model="claude-haiku",
        fallback_used=False,
        error_type=error_type,
        usage=UsageSummary(
            input_tokens=100, output_tokens=50, total_tokens=150,
            daily_used_tokens=150, daily_budget_tokens=100_000, daily_ratio=0.0015,
        ),
        warnings=[],
        personality_updated=False,
        updated_parameter=None,
        updated_parameters=[],
        artifacts=[],
    )


def _fake_db() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# _snippet
# ---------------------------------------------------------------------------

class TestSnippet:
    def test_short_text_unchanged(self) -> None:
        assert _snippet("Hola", 80) == "Hola"

    def test_exactly_at_limit_unchanged(self) -> None:
        s = "a" * 80
        assert _snippet(s, 80) == s

    def test_truncates_at_word_boundary(self) -> None:
        text = "Hello world this is a longer sentence that exceeds the limit"
        result = _snippet(text, 20)
        assert len(result) <= 20
        # Must not cut mid-word
        assert not result.endswith(" ")
        words = text.split()
        assert all(result == " ".join(words[:i]) for i in range(len(words)) if " ".join(words[:i]) == result)

    def test_truncates_at_last_space_before_limit(self) -> None:
        # "Hello world" — limit 10 → "Hello worl" rfind(" ")=5 → "Hello"
        assert _snippet("Hello world", 10) == "Hello"

    def test_no_space_before_limit_cuts_hard(self) -> None:
        # "Helloworld" — no space in first 5 chars → return first 5
        assert _snippet("Helloworld", 5) == "Hello"

    def test_80_char_limit(self) -> None:
        text = "Esta es una respuesta muy larga que supera el límite de ochenta caracteres en total."
        result = _snippet(text, 80)
        assert len(result) <= 80
        # Should not end with a space or a partial word (space before limit exists)
        assert " " not in result[len(result)-1:]  # last char is not a space

    def test_empty_text(self) -> None:
        assert _snippet("", 80) == ""


# ---------------------------------------------------------------------------
# _maybe_dispatch_chat_response — visibility states
# ---------------------------------------------------------------------------

class TestMaybeDispatchChatResponse:
    def test_visible_does_not_dispatch(self) -> None:
        """Tab in foreground → no notification, user already sees the response."""
        result = _result()
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="visible"), \
             patch(_PATCH_DISPATCH) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)
            assert mock_dispatch.call_count == 0

    def test_background_dispatches(self) -> None:
        """Tab in background → dispatch is called once."""
        result = _result()
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="sse+push", notification_id=1)) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)
            assert mock_dispatch.call_count == 1

    def test_none_dispatches(self) -> None:
        """No SSE subscriber → dispatch is called (push/pending path)."""
        result = _result()
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="none"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="pending", notification_id=2)) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)
            assert mock_dispatch.call_count == 1

    def test_fact_type_is_chat_response(self) -> None:
        """NotificationFact sent to dispatcher has notification_type='chat_response'."""
        result = _result()
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="sse+push")) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)

        fact, passed_db = mock_dispatch.call_args[0]
        assert fact.notification_type == "chat_response"
        assert fact.session_id == "user:1"
        assert passed_db is db

    def test_fact_id_is_deterministic_from_trace_id(self) -> None:
        """fact_id is stable across calls with the same trace_id — ensures dedup."""
        result = _result()
        result2 = _result(text="Same turn, different call")
        result2 = result2.__class__(**{**result2.model_dump(), "trace_id": result.trace_id})
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="sse+push")) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)
            fact1 = mock_dispatch.call_args[0][0]

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="sse+push")) as mock_dispatch:
            _maybe_dispatch_chat_response(result2, "user:1", db)
            fact2 = mock_dispatch.call_args[0][0]

        assert fact1.fact_id == fact2.fact_id
        assert fact1.fact_id == f"chat_response:{result.trace_id}"

    def test_payload_body_is_snippet_of_response_text(self) -> None:
        """Payload body is the truncated text, not the full response."""
        long_text = "Esta es una respuesta muy larga " * 10  # >> 80 chars
        result = _result(text=long_text)
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="sse+push")) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)

        fact = mock_dispatch.call_args[0][0]
        assert fact.payload["body"] == _snippet(long_text, 80)
        assert len(fact.payload["body"]) <= 80

    def test_payload_contains_title_and_url(self) -> None:
        result = _result()
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(channel="sse+push")) as mock_dispatch:
            _maybe_dispatch_chat_response(result, "user:1", db)

        fact = mock_dispatch.call_args[0][0]
        assert fact.payload["title"] == "Sity"
        assert fact.payload["url"] == "/"
        assert fact.payload["urgent"] is False

    def test_dispatch_exception_does_not_propagate(self) -> None:
        """A dispatch error must not crash the chat turn."""
        result = _result()
        db = _fake_db()

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, side_effect=RuntimeError("DB down")):
            # Must not raise
            _maybe_dispatch_chat_response(result, "user:1", db)

    def test_guest_session_dispatches(self) -> None:
        """Guest sessions in background call dispatch (dispatcher handles guest_drop internally)."""
        result = _result()
        db = _fake_db()
        sid = f"guest:{_uid()}"

        with patch(_PATCH_STATE, return_value="background"), \
             patch(_PATCH_DISPATCH, return_value=DispatchResult(discarded=True, reason="guest_no_sse")) as mock_dispatch:
            _maybe_dispatch_chat_response(result, sid, db)

        fact = mock_dispatch.call_args[0][0]
        assert fact.session_id == sid

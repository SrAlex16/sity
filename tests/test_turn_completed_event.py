"""Tests for the turn_completed session event published at end of successful turns.

When a turn succeeds, turn_runner must publish a turn_completed event on the
session's fan-out channel so other devices (same user_id) can reload history.
"""
from __future__ import annotations

from unittest.mock import patch

from app.api.schemas import ChatMessageRequest, ChatMessageResponse, UsageSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(message: str = "hola", turn_id: str = "t1") -> ChatMessageRequest:
    return ChatMessageRequest(
        message=message,
        client_turn_id=turn_id,
        source_channel="mobile",
    )


def _fake_response(text: str = "Hola.", error_type: str | None = None) -> ChatMessageResponse:
    return ChatMessageResponse(
        ok=True, text=text, trace_id="tr1",
        provider="mock", model="mock", fallback_used=False,
        error_type=error_type,
        usage=UsageSummary(
            input_tokens=5, output_tokens=5, total_tokens=10,
            daily_used_tokens=10, daily_budget_tokens=100000, daily_ratio=0.0001,
        ),
    )


def _run_turn(
    session_id: str,
    turn_id: str,
    message: str = "hola",
    inner_result: ChatMessageResponse | None = None,
) -> tuple[list, list]:
    """Run one turn, capturing turn-channel events and session-channel events separately."""
    from app.chat.turn_runner import _run_turn_in_background

    turn_events: list[dict] = []
    session_events: list[dict] = []

    inner_result = inner_result or _fake_response()

    with patch("app.chat.turn_runner._chat_message_inner", return_value=inner_result), \
         patch("app.chat.turn_runner.publish_event_sync",
               side_effect=lambda _tid, ev: turn_events.append(ev)), \
         patch("app.chat.turn_runner.publish_session_event_sync",
               side_effect=lambda _sid, ev: session_events.append(ev)), \
         patch("app.chat.turn_runner.write_log"), \
         patch("app.chat.turn_runner.Session"), \
         patch("app.achievements.triggers.inline.fire"):
        _run_turn_in_background(_make_request(message, turn_id), turn_id, session_id)

    return turn_events, session_events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTurnCompletedEvent:

    def test_successful_turn_publishes_turn_completed_on_session_channel(self):
        """A successful turn must publish turn_completed on the session channel."""
        _, session_events = _run_turn("user:42", "t_ok_1")
        types = [e.get("type") for e in session_events]
        assert "turn_completed" in types, f"Expected turn_completed in session events: {session_events}"

    def test_turn_completed_contains_turn_id_and_session_id(self):
        """turn_completed event must carry both turn_id and session_id."""
        _, session_events = _run_turn("user:42", "t_ok_2")
        ev = next((e for e in session_events if e.get("type") == "turn_completed"), None)
        assert ev is not None
        assert ev["turn_id"] == "t_ok_2"
        assert ev["session_id"] == "user:42"

    def test_turn_completed_not_published_for_empty_response(self):
        """If the response has no text, turn_completed must NOT be published
        (no message was saved to DB, other devices have nothing new to reload)."""
        empty = _fake_response(text="")
        _, session_events = _run_turn("user:42", "t_empty", inner_result=empty)
        types = [e.get("type") for e in session_events]
        assert "turn_completed" not in types

    def test_turn_channel_still_gets_response_and_done(self):
        """turn_completed on the session channel must not replace the turn-channel events."""
        turn_events, _ = _run_turn("user:42", "t_ok_3")
        types = [e.get("type") for e in turn_events]
        assert "response" in types
        assert "done" in types

    def test_cancelled_turn_does_not_publish_turn_completed(self):
        """Cancelled turns produce no assistant message — no turn_completed."""
        cancelled = _fake_response(text="", error_type="cancelled")
        _, session_events = _run_turn("user:42", "t_cancel", inner_result=cancelled)
        types = [e.get("type") for e in session_events]
        assert "turn_completed" not in types

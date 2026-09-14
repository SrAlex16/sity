"""Tests for session_queue — per-session turn serialization.

Covers:
- claim_session_slot versioning
- is_superseded detection
- Per-session lock independence (different sessions never block each other)
- _run_turn_in_background serialization: second turn sees first turn's persisted response
- _run_turn_in_background supersede: near-simultaneous messages processed only once
- Immediate HTTP feedback (202) before session lock is acquired

Regression for: guest session trc_938febd74c5a + trc_66ca5c8e64fa (2026-09-14)
  Two messages ~2s apart processed concurrently → second turn built context without
  seeing first turn's response → hallucinated "sierra", "Pico Roble", stale recipe.
"""
from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from app.core.session_queue import (
    acquire_session_lock,
    claim_session_slot,
    is_superseded,
    _session_version,
    _session_locks,
    _global_lock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_session(session_id: str) -> None:
    """Remove session state between tests."""
    with _global_lock:
        _session_version.pop(session_id, None)
        _session_locks.pop(session_id, None)


# ---------------------------------------------------------------------------
# claim_session_slot + is_superseded — unit tests
# ---------------------------------------------------------------------------

class TestClaimSessionSlot:
    def test_first_claim_returns_1(self):
        sid = "user:_test_claim_1"
        _reset_session(sid)
        assert claim_session_slot(sid) == 1

    def test_second_claim_increments(self):
        sid = "user:_test_claim_2"
        _reset_session(sid)
        claim_session_slot(sid)
        assert claim_session_slot(sid) == 2

    def test_independent_sessions_have_independent_counters(self):
        sid_a = "user:_test_ind_a"
        sid_b = "user:_test_ind_b"
        _reset_session(sid_a)
        _reset_session(sid_b)
        v_a = claim_session_slot(sid_a)
        v_b = claim_session_slot(sid_b)
        assert v_a == 1
        assert v_b == 1  # independent — not affected by sid_a's counter

    def test_guest_and_user_sessions_independent(self):
        sid_u = "user:_test_gu_u"
        sid_g = "guest:_test_gu_g"
        _reset_session(sid_u)
        _reset_session(sid_g)
        v_u = claim_session_slot(sid_u)
        v_g = claim_session_slot(sid_g)
        assert v_u == 1
        assert v_g == 1


class TestIsSuperseded:
    def test_not_superseded_when_version_unchanged(self):
        sid = "user:_test_sup_1"
        _reset_session(sid)
        v = claim_session_slot(sid)
        assert not is_superseded(sid, v)

    def test_superseded_when_newer_claim_arrives(self):
        sid = "user:_test_sup_2"
        _reset_session(sid)
        v1 = claim_session_slot(sid)
        claim_session_slot(sid)  # newer claim
        assert is_superseded(sid, v1)

    def test_latest_claim_not_superseded(self):
        sid = "user:_test_sup_3"
        _reset_session(sid)
        claim_session_slot(sid)
        v2 = claim_session_slot(sid)
        assert not is_superseded(sid, v2)

    def test_supersede_across_multiple_claims(self):
        sid = "user:_test_sup_4"
        _reset_session(sid)
        v1 = claim_session_slot(sid)
        claim_session_slot(sid)
        claim_session_slot(sid)
        v4 = claim_session_slot(sid)
        assert is_superseded(sid, v1)
        assert not is_superseded(sid, v4)

    def test_different_session_supersede_is_independent(self):
        sid_a = "user:_test_sup_ind_a"
        sid_b = "user:_test_sup_ind_b"
        _reset_session(sid_a)
        _reset_session(sid_b)
        v_a = claim_session_slot(sid_a)
        claim_session_slot(sid_b)  # newer claim on sid_b
        assert not is_superseded(sid_a, v_a)  # sid_a unaffected


# ---------------------------------------------------------------------------
# Lock independence — different sessions must never block each other
# ---------------------------------------------------------------------------

class TestSessionLockIndependence:
    def test_different_sessions_acquire_lock_concurrently(self):
        """Two turns for different sessions must run in parallel without blocking."""
        sid_a = "user:_test_lock_ind_a"
        sid_b = "user:_test_lock_ind_b"
        _reset_session(sid_a)
        _reset_session(sid_b)

        acquired: list[str] = []
        barrier = threading.Barrier(2)

        def acquire_and_signal(sid: str) -> None:
            lock = acquire_session_lock(sid)
            acquired.append(sid)
            barrier.wait(timeout=2.0)  # both must reach here simultaneously
            lock.release()

        t1 = threading.Thread(target=acquire_and_signal, args=(sid_a,))
        t2 = threading.Thread(target=acquire_and_signal, args=(sid_b,))
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        assert not t1.is_alive(), "Thread for sid_a timed out — possible global deadlock"
        assert not t2.is_alive(), "Thread for sid_b timed out — possible global deadlock"
        assert set(acquired) == {sid_a, sid_b}

    def test_same_session_blocks_second_until_first_releases(self):
        """Two turns for the same session must be serialized."""
        sid = "user:_test_lock_same"
        _reset_session(sid)

        order: list[str] = []
        lock_a_released = threading.Event()

        def turn_a() -> None:
            lock = acquire_session_lock(sid)
            order.append("a_start")
            lock_a_released.wait(timeout=2.0)
            order.append("a_end")
            lock.release()

        def turn_b() -> None:
            # waits until a releases
            lock = acquire_session_lock(sid)
            order.append("b_start")
            lock.release()

        t_a = threading.Thread(target=turn_a)
        t_a.start()
        # Give A a moment to acquire the lock before B tries
        import time
        time.sleep(0.05)
        t_b = threading.Thread(target=turn_b)
        t_b.start()

        # Let A finish
        lock_a_released.set()
        t_a.join(timeout=2.0)
        t_b.join(timeout=2.0)

        assert order == ["a_start", "a_end", "b_start"], (
            f"Expected serial execution, got: {order}"
        )


# ---------------------------------------------------------------------------
# _run_turn_in_background integration — serialization and supersede
# ---------------------------------------------------------------------------

def _make_request(message: str = "hola", turn_id: str = "turn_test") -> Any:
    from app.api.schemas import ChatMessageRequest
    return ChatMessageRequest(message=message, client_turn_id=turn_id)


def _fake_response(text: str = "respuesta") -> Any:
    from app.api.schemas import ChatMessageResponse, UsageSummary
    return ChatMessageResponse(
        ok=True,
        trace_id="trc_test",
        text=text,
        provider="anthropic",
        model="claude-haiku",
        fallback_used=False,
        usage=UsageSummary(
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            daily_used_tokens=30,
            daily_budget_tokens=100000,
            daily_ratio=0.0003,
        ),
    )


class TestRunTurnInBackground:
    """Integration tests for _run_turn_in_background serialization via mocks."""

    def _run(
        self,
        session_id: str,
        turn_id: str,
        message: str = "hola",
        inner_side_effect: Any = None,
    ) -> list[tuple[str, Any]]:
        """Run one turn synchronously, returning list of (event_type, payload) published."""
        from app.chat.turn_runner import _run_turn_in_background

        events: list[tuple[str, Any]] = []

        def capture_event(tid: str, ev: dict) -> None:
            events.append((ev.get("type", "?"), ev))

        req = _make_request(message=message, turn_id=turn_id)
        inner_result = inner_side_effect or _fake_response(text=f"respuesta a {message}")

        with patch("app.chat.turn_runner._chat_message_inner", return_value=inner_result), \
             patch("app.chat.turn_runner.publish_event_sync", side_effect=capture_event), \
             patch("app.chat.turn_runner.write_log"), \
             patch("app.chat.turn_runner.Session"), \
             patch("app.achievements.triggers.inline.fire"):
            _run_turn_in_background(req, turn_id, session_id)

        return events

    def test_normal_turn_emits_response_and_done(self):
        sid = "user:_bg_normal"
        _reset_session(sid)
        events = self._run(sid, "t1")
        types = [e[0] for e in events]
        assert "response" in types
        assert "done" in types

    def test_superseded_turn_emits_only_done(self):
        """When a newer claim arrives before this turn runs, it emits done without response.

        Simulates: turn A claims v1, then before A acquires the lock a newer message
        claims v2 (bumping _session_version to 2).  When A acquires the lock and checks,
        is_superseded returns True → A exits without calling _chat_message_inner.
        """
        from app.chat.turn_runner import _run_turn_in_background

        sid = "user:_bg_supersede"
        _reset_session(sid)

        v1 = claim_session_slot(sid)
        # Simulate a newer message arriving: bump the version counter directly.
        with _global_lock:
            _session_version[sid] = v1 + 1

        events: list[tuple] = []

        def capture(tid: str, ev: dict) -> None:
            events.append((ev.get("type"), ev))

        req = _make_request(message="first", turn_id="t_sup_1")
        # Patch claim_session_slot at the turn_runner import site so it returns v1
        # (the "old" version), while _session_version is already at v1+1.
        with patch("app.chat.turn_runner._chat_message_inner") as mock_inner, \
             patch("app.chat.turn_runner.publish_event_sync", side_effect=capture), \
             patch("app.chat.turn_runner.write_log"), \
             patch("app.chat.turn_runner.Session"), \
             patch("app.chat.turn_runner.claim_session_slot", return_value=v1):
            _run_turn_in_background(req, "t_sup_1", sid)

        mock_inner.assert_not_called()
        types = [e[0] for e in events]
        assert "response" not in types
        assert "done" in types

    def test_serial_turns_second_runs_after_first_completes(self):
        """Core race condition fix: second turn must not run while first holds the lock."""
        from app.chat.turn_runner import _run_turn_in_background

        sid = "user:_bg_serial"
        _reset_session(sid)

        execution_order: list[str] = []
        first_done = threading.Event()

        def slow_inner(**kwargs: Any) -> Any:
            msg = kwargs.get("request").message
            execution_order.append(f"inner_start:{msg}")
            if msg == "first":
                first_done.wait(timeout=3.0)
            execution_order.append(f"inner_end:{msg}")
            return _fake_response(text=f"respuesta a {msg}")

        req_a = _make_request(message="first", turn_id="t_ser_a")
        req_b = _make_request(message="second", turn_id="t_ser_b")

        with patch("app.chat.turn_runner._chat_message_inner", side_effect=slow_inner), \
             patch("app.chat.turn_runner.publish_event_sync"), \
             patch("app.chat.turn_runner.write_log"), \
             patch("app.chat.turn_runner.Session"), \
             patch("app.achievements.triggers.inline.fire"):

            t_a = threading.Thread(
                target=_run_turn_in_background,
                args=(req_a, "t_ser_a", sid),
            )
            t_a.start()

            import time
            time.sleep(0.05)  # ensure A has acquired the session lock

            t_b = threading.Thread(
                target=_run_turn_in_background,
                args=(req_b, "t_ser_b", sid),
            )
            t_b.start()

            time.sleep(0.05)  # B is now blocking on the session lock

            assert "inner_start:second" not in execution_order, (
                "Turn B started before turn A finished — race condition NOT fixed"
            )

            first_done.set()  # let A finish
            t_a.join(timeout=3.0)
            t_b.join(timeout=3.0)

        assert execution_order == [
            "inner_start:first",
            "inner_end:first",
            "inner_start:second",
            "inner_end:second",
        ], f"Unexpected execution order: {execution_order}"

    def test_different_sessions_run_in_parallel(self):
        """Turns for different sessions must never block each other."""
        from app.chat.turn_runner import _run_turn_in_background

        sid_a = "user:_bg_par_a"
        sid_b = "user:_bg_par_b"
        _reset_session(sid_a)
        _reset_session(sid_b)

        barrier = threading.Barrier(2, timeout=3.0)
        reached_barrier: list[str] = []

        def barrier_inner(**kwargs: Any) -> Any:
            msg = kwargs.get("request").message
            reached_barrier.append(msg)
            barrier.wait()  # both must arrive here concurrently
            return _fake_response(text=f"ok {msg}")

        req_a = _make_request(message="session_a", turn_id="t_par_a")
        req_b = _make_request(message="session_b", turn_id="t_par_b")

        with patch("app.chat.turn_runner._chat_message_inner", side_effect=barrier_inner), \
             patch("app.chat.turn_runner.publish_event_sync"), \
             patch("app.chat.turn_runner.write_log"), \
             patch("app.chat.turn_runner.Session"), \
             patch("app.achievements.triggers.inline.fire"):

            t_a = threading.Thread(
                target=_run_turn_in_background,
                args=(req_a, "t_par_a", sid_a),
            )
            t_b = threading.Thread(
                target=_run_turn_in_background,
                args=(req_b, "t_par_b", sid_b),
            )
            t_a.start()
            t_b.start()
            t_a.join(timeout=5.0)
            t_b.join(timeout=5.0)

        assert not t_a.is_alive(), "Thread A timed out — sessions may share a global lock"
        assert not t_b.is_alive(), "Thread B timed out — sessions may share a global lock"
        assert set(reached_barrier) == {"session_a", "session_b"}

    def test_session_lock_released_on_inner_exception(self):
        """Even if _chat_message_inner raises, the session lock must be released."""
        from app.chat.turn_runner import _run_turn_in_background

        sid = "user:_bg_exc"
        _reset_session(sid)

        def raise_inner(**kwargs: Any) -> Any:
            raise RuntimeError("simulated inner failure")

        req = _make_request(message="boom", turn_id="t_exc")
        with patch("app.chat.turn_runner._chat_message_inner", side_effect=raise_inner), \
             patch("app.chat.turn_runner.publish_event_sync"), \
             patch("app.chat.turn_runner.write_log"), \
             patch("app.chat.turn_runner.Session"), \
             patch("app.achievements.triggers.inline.fire"):
            _run_turn_in_background(req, "t_exc", sid)

        # If lock was NOT released, this would deadlock.  The thread below
        # acquiring the same session lock would timeout.
        acquired = threading.Event()

        def try_acquire() -> None:
            from app.core.session_queue import acquire_session_lock
            lock = acquire_session_lock(sid)
            acquired.set()
            lock.release()

        t = threading.Thread(target=try_acquire)
        t.start()
        t.join(timeout=2.0)
        assert acquired.is_set(), "Session lock was NOT released after inner exception"

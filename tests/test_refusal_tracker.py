"""Tests for refusal_tracker — per-session state and clear semantics."""
from __future__ import annotations

from app.core.refusal_tracker import clear_last_refusal, get_last_refusal, set_last_refusal


def _seed(session_id: str = "user:1") -> None:
    set_last_refusal(
        session_id=session_id,
        user_message="dime algo",
        assistant_message="No.",
        trace_id="trc_test",
    )


def teardown_function():
    clear_last_refusal("user:1")
    clear_last_refusal("user:2")
    clear_last_refusal("user:99")


# ------------------------------------------------------------------ #
# 1. Basic set / get                                                  #
# ------------------------------------------------------------------ #

def test_get_returns_none_before_any_set():
    assert get_last_refusal("user:99") is None


def test_set_and_get_returns_data():
    _seed()
    data = get_last_refusal("user:1")
    assert data is not None
    assert data["user_message"] == "dime algo"
    assert data["assistant_message"] == "No."


def test_get_without_session_id_returns_none():
    _seed()
    assert get_last_refusal("") is None
    assert get_last_refusal() is None


# ------------------------------------------------------------------ #
# 2. Per-session isolation                                            #
# ------------------------------------------------------------------ #

def test_session_isolation_different_sessions():
    _seed("user:1")
    # user:2 must not see user:1's refusal
    assert get_last_refusal("user:2") is None


def test_session_isolation_set_for_different_session():
    set_last_refusal(session_id="user:2", user_message="msg2", assistant_message="No2.", trace_id="t2")
    assert get_last_refusal("user:1") is None
    assert get_last_refusal("user:2") is not None


# ------------------------------------------------------------------ #
# 3. clear_last_refusal — resets immediately                         #
# ------------------------------------------------------------------ #

def test_clear_resets_state():
    _seed()
    clear_last_refusal("user:1")
    assert get_last_refusal("user:1") is None


def test_clear_only_affects_target_session():
    _seed("user:1")
    set_last_refusal(session_id="user:2", user_message="x", assistant_message="No.", trace_id="t")
    clear_last_refusal("user:1")
    assert get_last_refusal("user:1") is None
    assert get_last_refusal("user:2") is not None


def test_clear_on_empty_session_is_safe():
    clear_last_refusal("user:99")  # must not raise


# ------------------------------------------------------------------ #
# 4. State does not bleed across turns (the original bug)            #
# ------------------------------------------------------------------ #

def test_refusal_state_cleared_after_non_refusal_turn():
    """After a non-refusal turn clears the state, the next turn sees None."""
    _seed()
    assert get_last_refusal("user:1") is not None  # was set
    clear_last_refusal("user:1")                    # simulates a normal turn completing
    assert get_last_refusal("user:1") is None       # next turn sees no refusal


def test_refusal_state_updated_on_consecutive_refusals():
    set_last_refusal(session_id="user:1", user_message="msg1", assistant_message="No1.", trace_id="t1")
    set_last_refusal(session_id="user:1", user_message="msg2", assistant_message="No2.", trace_id="t2")
    data = get_last_refusal("user:1")
    assert data["user_message"] == "msg2"
    assert data["trace_id"] == "t2"

"""Tests for the 3-state visibility mechanism — Paso A.

Covers:
- _SessionQueue defaults is_visible=True
- set_session_visibility() updates the field; no-op for unknown sessions
- get_subscriber_state() returns correct state for all 3 cases
- POST /events/visibility updates state for authenticated users
- POST /events/visibility is accepted for guests (silent no-op)
- Visibility resets to True when a new SSE queue is created (default)
- Cleanup: listener does not leak state between tests
"""
from __future__ import annotations

import time
import uuid as _uuid_mod
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.core.realtime_events as re_mod
from app.core.realtime_events import (
    _SessionQueue,
    get_subscriber_state,
    set_session_visibility,
)
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _inject(session_id: str, *, subscribers: int = 0, is_visible: bool = True) -> _SessionQueue:
    sq = _SessionQueue()
    sq.subscriber_count = subscribers
    sq.is_visible = is_visible
    sq.last_active = time.monotonic()
    re_mod._session_queues[session_id] = sq
    return sq


def _remove(session_id: str) -> None:
    re_mod._session_queues.pop(session_id, None)


def _register_and_login(client: TestClient) -> tuple[str, int]:
    email = f"vis_{_uid()}@sity-test.invalid"
    resp = client.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    return resp.cookies["sity_session"], resp.json()["id"]


# ---------------------------------------------------------------------------
# Unit: _SessionQueue defaults
# ---------------------------------------------------------------------------

def test_session_queue_default_is_visible_true():
    sq = _SessionQueue()
    assert sq.is_visible is True


# ---------------------------------------------------------------------------
# Unit: set_session_visibility
# ---------------------------------------------------------------------------

def test_set_visibility_marks_background():
    sid = f"test_vis_{_uid()}"
    _inject(sid, subscribers=1, is_visible=True)
    set_session_visibility(sid, False)
    assert re_mod._session_queues[sid].is_visible is False
    _remove(sid)


def test_set_visibility_marks_visible():
    sid = f"test_vis_{_uid()}"
    _inject(sid, subscribers=1, is_visible=False)
    set_session_visibility(sid, True)
    assert re_mod._session_queues[sid].is_visible is True
    _remove(sid)


def test_set_visibility_noop_for_unknown_session():
    sid = f"test_vis_unknown_{_uid()}"
    # Must not raise; session not in dict
    set_session_visibility(sid, False)
    assert sid not in re_mod._session_queues


# ---------------------------------------------------------------------------
# Unit: get_subscriber_state
# ---------------------------------------------------------------------------

def test_get_state_none_when_no_queue():
    sid = f"test_state_{_uid()}"
    assert get_subscriber_state(sid) == "none"


def test_get_state_none_when_no_subscriber():
    sid = f"test_state_{_uid()}"
    _inject(sid, subscribers=0)
    assert get_subscriber_state(sid) == "none"
    _remove(sid)


def test_get_state_visible_when_subscribed_and_visible():
    sid = f"test_state_{_uid()}"
    _inject(sid, subscribers=1, is_visible=True)
    assert get_subscriber_state(sid) == "visible"
    _remove(sid)


def test_get_state_background_when_subscribed_and_not_visible():
    sid = f"test_state_{_uid()}"
    _inject(sid, subscribers=1, is_visible=False)
    assert get_subscriber_state(sid) == "background"
    _remove(sid)


def test_get_state_default_visible_without_explicit_set():
    """A freshly created queue (is_visible=True by default) with a subscriber
    returns 'visible' even if set_session_visibility was never called."""
    sid = f"test_state_{_uid()}"
    _inject(sid, subscribers=1)  # is_visible defaults to True
    assert get_subscriber_state(sid) == "visible"
    _remove(sid)


# ---------------------------------------------------------------------------
# Integration: POST /events/visibility
# ---------------------------------------------------------------------------

class TestVisibilityEndpoint:
    def test_authenticated_user_sets_background(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"

        _inject(session_id, subscribers=1, is_visible=True)

        resp = client.post(
            "/events/visibility",
            json={"is_visible": False},
            cookies={"sity_session": cookie},
        )
        assert resp.status_code == 204
        assert re_mod._session_queues[session_id].is_visible is False
        _remove(session_id)

    def test_authenticated_user_sets_visible(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"

        _inject(session_id, subscribers=1, is_visible=False)

        resp = client.post(
            "/events/visibility",
            json={"is_visible": True},
            cookies={"sity_session": cookie},
        )
        assert resp.status_code == 204
        assert re_mod._session_queues[session_id].is_visible is True
        _remove(session_id)

    def test_guest_accepted_silently(self) -> None:
        """Guests post visibility without error — they have no push subs so
        the state is irrelevant, but we don't want the frontend to gate the call."""
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post("/events/visibility", json={"is_visible": True})
        assert resp.status_code == 204

    def test_missing_field_returns_422(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, _ = _register_and_login(client)
        resp = client.post(
            "/events/visibility",
            json={},
            cookies={"sity_session": cookie},
        )
        assert resp.status_code == 422

    def test_no_queue_yet_is_noop(self) -> None:
        """POST before SSE connects — no session queue exists — must not crash."""
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        session_id = f"user:{user_id}"
        # Ensure no queue exists for this session
        _remove(session_id)

        resp = client.post(
            "/events/visibility",
            json={"is_visible": False},
            cookies={"sity_session": cookie},
        )
        assert resp.status_code == 204
        assert session_id not in re_mod._session_queues

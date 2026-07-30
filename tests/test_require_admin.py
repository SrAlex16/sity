"""Tests for require_admin access control on the 6 restricted endpoints.

For each endpoint:
  - Guest (no cookie)      → 403
  - Authenticated User     → 403
  - Authenticated Admin    → 2xx (same behaviour as before — not 403)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import make_admin_token, make_user_token


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fixtures — one client per role, reused across all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guest():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="module")
def user():
    token = make_user_token()
    with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
        yield c


@pytest.fixture(scope="module")
def admin():
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True, cookies={"sity_session": token}) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /settings/voice
# ---------------------------------------------------------------------------


def test_get_voice_guest_403(guest: TestClient) -> None:
    assert guest.get("/settings/voice").status_code == 403


def test_get_voice_user_403(user: TestClient) -> None:
    assert user.get("/settings/voice").status_code == 403


def test_get_voice_admin_ok(admin: TestClient) -> None:
    assert admin.get("/settings/voice").status_code == 200


# ---------------------------------------------------------------------------
# PUT /settings/voice
# ---------------------------------------------------------------------------

_VOICE_PAYLOAD = {
    "voice_response_mode": "never",
    "voice_include_text": True,
    "voice_long_response_action": "text_only",
    "audio_cleanup_days": 7,
}


def test_put_voice_guest_403(guest: TestClient) -> None:
    assert guest.put("/settings/voice", json=_VOICE_PAYLOAD).status_code == 403


def test_put_voice_user_403(user: TestClient) -> None:
    assert user.put("/settings/voice", json=_VOICE_PAYLOAD).status_code == 403


def test_put_voice_admin_ok(admin: TestClient) -> None:
    assert admin.put("/settings/voice", json=_VOICE_PAYLOAD).status_code == 200


# ---------------------------------------------------------------------------
# POST /settings/personality/reset
# ---------------------------------------------------------------------------


def test_reset_personality_guest_403(guest: TestClient) -> None:
    assert guest.post("/settings/personality/reset").status_code == 403


def test_reset_personality_user_403(user: TestClient) -> None:
    assert user.post("/settings/personality/reset").status_code == 403


def test_reset_personality_admin_ok(admin: TestClient) -> None:
    assert admin.post("/settings/personality/reset").status_code == 200


# ---------------------------------------------------------------------------
# GET /debug/dataset-capture
# ---------------------------------------------------------------------------


def test_get_dataset_capture_guest_403(guest: TestClient) -> None:
    assert guest.get("/debug/dataset-capture").status_code == 403


def test_get_dataset_capture_user_403(user: TestClient) -> None:
    assert user.get("/debug/dataset-capture").status_code == 403


def test_get_dataset_capture_admin_ok(admin: TestClient) -> None:
    assert admin.get("/debug/dataset-capture").status_code == 200


# ---------------------------------------------------------------------------
# PUT /debug/dataset-capture
# ---------------------------------------------------------------------------

_CAPTURE_PAYLOAD = {
    "enabled": False,
    "dataset_source": "normal_use",
    "dataset_tags": [],
}


def test_put_dataset_capture_guest_403(guest: TestClient) -> None:
    assert guest.put("/debug/dataset-capture", json=_CAPTURE_PAYLOAD).status_code == 403


def test_put_dataset_capture_user_403(user: TestClient) -> None:
    assert user.put("/debug/dataset-capture", json=_CAPTURE_PAYLOAD).status_code == 403


def test_put_dataset_capture_admin_ok(admin: TestClient) -> None:
    assert admin.put("/debug/dataset-capture", json=_CAPTURE_PAYLOAD).status_code == 200


# ---------------------------------------------------------------------------
# POST /debug/dataset-capture/disable
# ---------------------------------------------------------------------------


def test_disable_capture_guest_403(guest: TestClient) -> None:
    assert guest.post("/debug/dataset-capture/disable").status_code == 403


def test_disable_capture_user_403(user: TestClient) -> None:
    assert user.post("/debug/dataset-capture/disable").status_code == 403


def test_disable_capture_admin_ok(admin: TestClient) -> None:
    assert admin.post("/debug/dataset-capture/disable").status_code == 200


# ---------------------------------------------------------------------------
# GET /debug/events/recent
# ---------------------------------------------------------------------------


def test_events_recent_guest_403(guest: TestClient) -> None:
    assert guest.get("/debug/events/recent").status_code == 403


def test_events_recent_user_403(user: TestClient) -> None:
    assert user.get("/debug/events/recent").status_code == 403


def test_events_recent_admin_ok(admin: TestClient) -> None:
    assert admin.get("/debug/events/recent").status_code == 200


# ---------------------------------------------------------------------------
# GET /debug/last-trace
# ---------------------------------------------------------------------------


def test_last_trace_guest_403(guest: TestClient) -> None:
    assert guest.get("/debug/last-trace").status_code == 403


def test_last_trace_user_403(user: TestClient) -> None:
    assert user.get("/debug/last-trace").status_code == 403


def test_last_trace_admin_ok(admin: TestClient) -> None:
    assert admin.get("/debug/last-trace").status_code == 200


# ---------------------------------------------------------------------------
# GET /debug/traces/{trace_id}
# ---------------------------------------------------------------------------


def test_trace_by_id_guest_403(guest: TestClient) -> None:
    assert guest.get("/debug/traces/nonexistent-trace-id").status_code == 403


def test_trace_by_id_user_403(user: TestClient) -> None:
    assert user.get("/debug/traces/nonexistent-trace-id").status_code == 403


def test_trace_by_id_admin_ok(admin: TestClient) -> None:
    assert admin.get("/debug/traces/nonexistent-trace-id").status_code == 200


# ---------------------------------------------------------------------------
# GET /debug/budget
# ---------------------------------------------------------------------------


def test_budget_guest_403(guest: TestClient) -> None:
    assert guest.get("/debug/budget").status_code == 403


def test_budget_user_403(user: TestClient) -> None:
    assert user.get("/debug/budget").status_code == 403


def test_budget_admin_ok(admin: TestClient) -> None:
    assert admin.get("/debug/budget").status_code == 200

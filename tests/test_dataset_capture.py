"""Tests for DatasetCaptureService, /debug/dataset-capture endpoints,
and chat-route integration (metadata forwarded to saved ChatMessages).

All tests use the isolated test DB (conftest.py) and mock AI provider.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.models import ChatMessage
from helpers import chat_post_and_drain


# ---------------------------------------------------------------------------
# DB isolation — delete the dataset_capture Setting row before every test so
# that service-level tests don't see state left by API-level tests, and vice versa.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_capture_setting(db_session: Session) -> None:  # type: ignore[return]
    from sqlmodel import delete as sql_delete
    from app.memory.models import Setting
    db_session.exec(sql_delete(Setting).where(Setting.key == "dataset_capture"))  # type: ignore[arg-type]
    db_session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENABLE_SYNTHETIC = {
    "enabled": True,
    "dataset_source": "synthetic_claude_user",
    "speaker_source": "synthetic_claude_user",
    "speaker_label": "guest_confused_01",
    "speaker_confidence": 0.9,
    "dataset_eligible": True,
    "dataset_tags": ["multi_persona"],
}


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        # Reset capture to a known default state before every test.
        c.put("/debug/dataset-capture", json={
            "enabled": False,
            "dataset_source": "normal_use",
            "dataset_tags": [],
        })
        yield c


# ---------------------------------------------------------------------------
# DatasetCaptureService — unit tests (no HTTP)
# ---------------------------------------------------------------------------

def test_service_get_returns_disabled_by_default(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureService
    ctx = DatasetCaptureService(db_session).get()
    assert ctx.enabled is False
    assert ctx.dataset_source == "normal_use"
    assert ctx.dataset_tags == []


def test_service_save_and_get_roundtrip(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(
        enabled=True,
        dataset_source="synthetic_claude_user",
        speaker_source="synthetic_claude_user",
        speaker_label="persona_a",
        speaker_confidence=0.85,
        dataset_eligible=True,
        dataset_tags=["multi_persona", "casual"],
    )
    svc = DatasetCaptureService(db_session)
    svc.save(ctx)
    loaded = svc.get()
    assert loaded.enabled is True
    assert loaded.dataset_source == "synthetic_claude_user"
    assert loaded.speaker_source == "synthetic_claude_user"
    assert loaded.speaker_label == "persona_a"
    assert loaded.speaker_confidence == pytest.approx(0.85)
    assert loaded.dataset_tags == ["multi_persona", "casual"]
    assert loaded.updated_at is not None


def test_service_disable_sets_enabled_false(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(
        enabled=True, dataset_source="synthetic_claude_user",
        speaker_source="synthetic_claude_user",
    )
    svc = DatasetCaptureService(db_session)
    svc.save(ctx)
    disabled = svc.disable()
    assert disabled.enabled is False
    assert disabled.dataset_source == "synthetic_claude_user"  # other fields preserved


def test_service_build_user_metadata_disabled(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(enabled=False)
    meta = DatasetCaptureService(db_session).build_user_metadata(ctx)
    assert meta.speaker_source == "human_local"
    assert meta.dataset_source == "normal_use"


def test_service_build_user_metadata_enabled(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(
        enabled=True, dataset_source="synthetic_claude_user",
        speaker_source="synthetic_claude_user", speaker_label="p1",
        speaker_confidence=0.9, dataset_eligible=True,
        dataset_tags=["multi_persona"],
    )
    meta = DatasetCaptureService(db_session).build_user_metadata(ctx)
    assert meta.speaker_source == "synthetic_claude_user"
    assert meta.dataset_source == "synthetic_claude_user"
    assert meta.speaker_label == "p1"
    assert meta.speaker_confidence == pytest.approx(0.9)
    assert json.loads(meta.dataset_tags_json or "[]") == ["multi_persona"]


def test_service_build_sity_metadata_enabled(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(
        enabled=True, dataset_source="synthetic_claude_user",
        speaker_source="synthetic_claude_user",
        dataset_tags=["multi_persona"],
    )
    meta = DatasetCaptureService(db_session).build_sity_metadata(ctx)
    assert meta.speaker_source == "sity_local"
    assert meta.dataset_source == "synthetic_claude_user"
    assert json.loads(meta.dataset_tags_json or "[]") == ["multi_persona"]


def test_service_build_sity_metadata_disabled(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(enabled=False)
    meta = DatasetCaptureService(db_session).build_sity_metadata(ctx)
    assert meta.speaker_source == "sity_local"
    assert meta.dataset_source == "normal_use"


def test_service_empty_tags_gives_none_json(db_session: Session) -> None:
    from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
    ctx = DatasetCaptureContext(
        enabled=True, dataset_source="human_guest",
        speaker_source="human_guest", dataset_tags=[],
    )
    meta = DatasetCaptureService(db_session).build_user_metadata(ctx)
    assert meta.dataset_tags_json is None


# ---------------------------------------------------------------------------
# GET /debug/dataset-capture
# ---------------------------------------------------------------------------

def test_get_dataset_capture_ok(client) -> None:
    resp = client.get("/debug/dataset-capture")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["enabled"] is False


def test_get_dataset_capture_default_source_is_normal_use(client) -> None:
    resp = client.get("/debug/dataset-capture")
    assert resp.json()["dataset_source"] == "normal_use"


# ---------------------------------------------------------------------------
# PUT /debug/dataset-capture
# ---------------------------------------------------------------------------

def test_put_dataset_capture_enabled_synthetic(client) -> None:
    resp = client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["dataset_source"] == "synthetic_claude_user"
    assert body["speaker_source"] == "synthetic_claude_user"
    assert body["speaker_label"] == "guest_confused_01"
    assert body["speaker_confidence"] == pytest.approx(0.9)
    assert body["dataset_tags"] == ["multi_persona"]


def test_put_dataset_capture_persists(client) -> None:
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    resp = client.get("/debug/dataset-capture")
    assert resp.json()["enabled"] is True
    assert resp.json()["dataset_source"] == "synthetic_claude_user"


def test_put_dataset_capture_confidence_out_of_range(client) -> None:
    payload = {**_ENABLE_SYNTHETIC, "speaker_confidence": 1.5}
    resp = client.put("/debug/dataset-capture", json=payload)
    assert resp.status_code == 422


def test_put_dataset_capture_negative_confidence(client) -> None:
    payload = {**_ENABLE_SYNTHETIC, "speaker_confidence": -0.1}
    resp = client.put("/debug/dataset-capture", json=payload)
    assert resp.status_code == 422


def test_put_dataset_capture_enabled_without_speaker_source(client) -> None:
    payload = {
        "enabled": True,
        "dataset_source": "synthetic_claude_user",
        # speaker_source missing / None
    }
    resp = client.put("/debug/dataset-capture", json=payload)
    assert resp.status_code == 422


def test_put_dataset_capture_disabled_does_not_require_speaker_source(client) -> None:
    payload = {"enabled": False, "dataset_source": "normal_use"}
    resp = client.put("/debug/dataset-capture", json=payload)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_put_dataset_capture_empty_tags(client) -> None:
    payload = {**_ENABLE_SYNTHETIC, "dataset_tags": []}
    resp = client.put("/debug/dataset-capture", json=payload)
    assert resp.status_code == 200
    assert resp.json()["dataset_tags"] == []


# ---------------------------------------------------------------------------
# POST /debug/dataset-capture/disable
# ---------------------------------------------------------------------------

def test_disable_sets_enabled_false(client) -> None:
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    resp = client.post("/debug/dataset-capture/disable")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["enabled"] is False


def test_disable_preserves_other_fields(client) -> None:
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    resp = client.post("/debug/dataset-capture/disable")
    body = resp.json()
    assert body["dataset_source"] == "synthetic_claude_user"
    assert body["speaker_source"] == "synthetic_claude_user"


def test_disable_idempotent_when_already_disabled(client) -> None:
    resp = client.post("/debug/dataset-capture/disable")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


# ---------------------------------------------------------------------------
# Chat integration — metadata forwarded to ChatMessage rows
# ---------------------------------------------------------------------------

def _last_pair(db_session: Session) -> tuple[ChatMessage | None, ChatMessage | None]:
    """Return the last saved (user, sity) ChatMessage pair."""
    rows = list(db_session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == "default")
        .order_by(ChatMessage.id.desc())
        .limit(2)
    ))
    rows.reverse()
    user_msg = next((r for r in rows if r.role == "user"), None)
    sity_msg = next((r for r in rows if r.role == "sity"), None)
    return user_msg, sity_msg


def test_chat_normal_mode_user_saved_with_human_local(client, db_session: Session) -> None:
    """With capture disabled, user message gets human_local speaker_source."""
    client.post("/debug/dataset-capture/disable")
    chat_post_and_drain(client, "hola")
    user_msg, _ = _last_pair(db_session)
    assert user_msg is not None
    assert user_msg.speaker_source == "human_local"
    assert user_msg.dataset_source == "normal_use"


def test_chat_normal_mode_sity_saved_with_sity_local(client, db_session: Session) -> None:
    """With capture disabled, sity message gets sity_local + normal_use."""
    client.post("/debug/dataset-capture/disable")
    chat_post_and_drain(client, "hola")
    _, sity_msg = _last_pair(db_session)
    assert sity_msg is not None
    assert sity_msg.speaker_source == "sity_local"
    assert sity_msg.dataset_source == "normal_use"


def test_chat_capture_user_saved_with_synthetic_metadata(client, db_session: Session) -> None:
    """With capture enabled, user message gets synthetic_claude_user metadata."""
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    chat_post_and_drain(client, "hola desde capture")
    user_msg, _ = _last_pair(db_session)
    assert user_msg is not None
    assert user_msg.speaker_source == "synthetic_claude_user"
    assert user_msg.dataset_source == "synthetic_claude_user"
    assert user_msg.speaker_label == "guest_confused_01"
    tags = json.loads(user_msg.dataset_tags_json or "[]")
    assert "multi_persona" in tags


def test_chat_capture_sity_saved_with_sity_local_and_synthetic_source(
    client, db_session: Session
) -> None:
    """With capture enabled, sity message uses dataset_source from capture but speaker_source=sity_local."""
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    chat_post_and_drain(client, "hola desde capture sity")
    _, sity_msg = _last_pair(db_session)
    assert sity_msg is not None
    assert sity_msg.speaker_source == "sity_local"
    assert sity_msg.dataset_source == "synthetic_claude_user"
    tags = json.loads(sity_msg.dataset_tags_json or "[]")
    assert "multi_persona" in tags


def test_chat_capture_sity_tone_meta_preserved(client, db_session: Session) -> None:
    """tone_meta is still saved on sity messages when capture is active."""
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    chat_post_and_drain(client, "qué tal?")
    _, sity_msg = _last_pair(db_session)
    assert sity_msg is not None
    assert sity_msg.tone_meta is not None
    parsed = json.loads(sity_msg.tone_meta)
    assert isinstance(parsed, dict)
    assert "sarcasm" in parsed or len(parsed) > 0


def test_chat_after_disable_reverts_to_normal_use(client, db_session: Session) -> None:
    """After disabling capture, new messages revert to normal_use metadata."""
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    client.post("/debug/dataset-capture/disable")
    chat_post_and_drain(client, "post-disable")
    user_msg, _ = _last_pair(db_session)
    assert user_msg is not None
    assert user_msg.speaker_source == "human_local"
    assert user_msg.dataset_source == "normal_use"


# ---------------------------------------------------------------------------
# Dataset stats — captures counted in by_source and by_tag
# ---------------------------------------------------------------------------

def test_dataset_stats_counts_synthetic_source(client) -> None:
    """After a capture-mode chat turn, stats show synthetic_claude_user in by_source."""
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    chat_post_and_drain(client, "stats check synthetic")
    client.post("/debug/dataset-capture/disable")

    resp = client.get("/debug/dataset-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["by_source"].get("synthetic_claude_user", 0) >= 1


def test_dataset_stats_multi_persona_tag_counted(client) -> None:
    """multi_persona tag from capture is counted in by_tag."""
    client.put("/debug/dataset-capture", json=_ENABLE_SYNTHETIC)
    chat_post_and_drain(client, "stats check multi_persona")
    client.post("/debug/dataset-capture/disable")

    resp = client.get("/debug/dataset-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["by_tag"].get("multi_persona", 0) >= 1

"""Tests for file management Parts 1+2.

Part 1 — model fields + settings:
  - FileArtifact gets file_size_bytes and expires_at when saved via save_uploaded_image
  - FileArtifact gets file_size_bytes and expires_at when saved via register_capture_artifact
  - GET/PUT /settings/file-retention: guest→401, user persist, clamp 1–30, default 7

Part 2 — guest upload restriction:
  - POST /chat/message with images as guest → 403
  - POST /chat/message with images as registered user → proceeds past upload gate
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.main import app
from helpers import make_user_token


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Part 1 — save_uploaded_image populates file_size_bytes + expires_at
# ---------------------------------------------------------------------------

class TestSaveUploadedImageFields:

    def _make_db(self):
        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(eng)
        return eng

    def test_file_size_bytes_populated(self, tmp_path: Path) -> None:
        from app.chat.file_artifact import save_uploaded_image, UPLOADS_IMAGES_DIR

        raw = b"\xff\xd8\xff\xe0" + b"x" * 100
        b64 = base64.b64encode(raw).decode()

        eng = self._make_db()
        with Session(eng) as db:
            with patch("app.chat.file_artifact.UPLOADS_IMAGES_DIR", tmp_path):
                fa = save_uploaded_image(b64, "image/jpeg", db, user_id=1)

        assert fa.file_size_bytes == len(raw)

    def test_expires_at_default_7_days(self, tmp_path: Path) -> None:
        from app.chat.file_artifact import save_uploaded_image
        from datetime import timedelta

        raw = b"\xff\xd8\xff\xe0" + b"x" * 50
        b64 = base64.b64encode(raw).decode()

        eng = self._make_db()
        before = datetime.now(timezone.utc)
        with Session(eng) as db:
            with patch("app.chat.file_artifact.UPLOADS_IMAGES_DIR", tmp_path):
                fa = save_uploaded_image(b64, "image/jpeg", db, user_id=1, retention_days=7)
        after = datetime.now(timezone.utc)

        assert fa.expires_at is not None
        expires = fa.expires_at if fa.expires_at.tzinfo else fa.expires_at.replace(tzinfo=timezone.utc)
        expected_min = before + timedelta(days=7) - timedelta(seconds=5)
        expected_max = after + timedelta(days=7) + timedelta(seconds=5)
        assert expected_min <= expires <= expected_max

    def test_custom_retention_days(self, tmp_path: Path) -> None:
        from app.chat.file_artifact import save_uploaded_image
        from datetime import timedelta

        raw = b"\xff\xd8\xff\xe0" + b"x" * 50
        b64 = base64.b64encode(raw).decode()

        eng = self._make_db()
        before = datetime.now(timezone.utc)
        with Session(eng) as db:
            with patch("app.chat.file_artifact.UPLOADS_IMAGES_DIR", tmp_path):
                fa = save_uploaded_image(b64, "image/jpeg", db, user_id=1, retention_days=14)

        assert fa.expires_at is not None
        expires = fa.expires_at if fa.expires_at.tzinfo else fa.expires_at.replace(tzinfo=timezone.utc)
        assert expires > before + timedelta(days=13)


# ---------------------------------------------------------------------------
# Part 1 — register_capture_artifact populates file_size_bytes + expires_at
# ---------------------------------------------------------------------------

class TestRegisterCaptureArtifactFields:

    def _make_db(self):
        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(eng)
        return eng

    def _make_artifact_schema(self, tmp_path: Path, size: int = 200) -> "object":
        from app.api.schemas import ChatArtifact
        fname = "test_capture.jpg"
        file_path = tmp_path / "captures" / "camera" / fname
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"x" * size)
        return ChatArtifact(
            type="image",
            url="/captures/camera/" + fname,
            filename=fname,
            mime_type="image/jpeg",
        )

    def test_file_size_bytes_from_disk(self, tmp_path: Path) -> None:
        from app.chat.file_artifact import register_capture_artifact, PROJECT_ROOT

        artifact = self._make_artifact_schema(tmp_path, size=300)
        eng = self._make_db()
        with Session(eng) as db:
            with patch("app.chat.file_artifact.PROJECT_ROOT", tmp_path):
                fa = register_capture_artifact(artifact, db, user_id=1)

        assert fa is not None
        assert fa.file_size_bytes == 300

    def test_expires_at_set(self, tmp_path: Path) -> None:
        from app.chat.file_artifact import register_capture_artifact
        from datetime import timedelta

        artifact = self._make_artifact_schema(tmp_path, size=100)
        eng = self._make_db()
        before = datetime.now(timezone.utc)
        with Session(eng) as db:
            with patch("app.chat.file_artifact.PROJECT_ROOT", tmp_path):
                fa = register_capture_artifact(artifact, db, user_id=1, retention_days=7)

        assert fa is not None
        assert fa.expires_at is not None
        expires = fa.expires_at if fa.expires_at.tzinfo else fa.expires_at.replace(tzinfo=timezone.utc)
        assert expires > before + timedelta(days=6)

    def test_missing_file_size_zero(self, tmp_path: Path) -> None:
        from app.chat.file_artifact import register_capture_artifact
        from app.api.schemas import ChatArtifact

        artifact = ChatArtifact(
            type="image",
            url="/captures/camera/nonexistent.jpg",
            filename="nonexistent.jpg",
            mime_type="image/jpeg",
        )
        eng = self._make_db()
        with Session(eng) as db:
            with patch("app.chat.file_artifact.PROJECT_ROOT", tmp_path):
                fa = register_capture_artifact(artifact, db, user_id=1)

        assert fa is not None
        assert fa.file_size_bytes == 0


# ---------------------------------------------------------------------------
# Part 1 — /settings/file-retention endpoints
# ---------------------------------------------------------------------------

class TestFileRetentionEndpoints:

    def test_guest_get_returns_401(self) -> None:
        with _client() as c:
            resp = c.get("/settings/file-retention")
        assert resp.status_code == 401

    def test_guest_put_returns_401(self) -> None:
        with _client() as c:
            resp = c.put("/settings/file-retention", json={"file_retention_days": 14})
        assert resp.status_code == 401

    def test_default_is_7(self) -> None:
        token = make_user_token()
        with _client() as c:
            resp = c.get("/settings/file-retention", cookies={"sity_session": token})
        assert resp.status_code == 200
        assert resp.json()["file_retention_days"] == 7

    def test_put_and_get_persists(self) -> None:
        token = make_user_token()
        with _client() as c:
            put = c.put(
                "/settings/file-retention",
                json={"file_retention_days": 14},
                cookies={"sity_session": token},
            )
            assert put.status_code == 200
            assert put.json()["file_retention_days"] == 14

            get = c.get("/settings/file-retention", cookies={"sity_session": token})
            assert get.status_code == 200
            assert get.json()["file_retention_days"] == 14

    def test_value_clamped_to_30(self) -> None:
        token = make_user_token()
        with _client() as c:
            put = c.put(
                "/settings/file-retention",
                json={"file_retention_days": 99},
                cookies={"sity_session": token},
            )
        # Pydantic rejects > 30 at schema level with 422
        assert put.status_code in (200, 422)
        if put.status_code == 200:
            assert put.json()["file_retention_days"] <= 30

    def test_value_minimum_1(self) -> None:
        token = make_user_token()
        with _client() as c:
            put = c.put(
                "/settings/file-retention",
                json={"file_retention_days": 0},
                cookies={"sity_session": token},
            )
        assert put.status_code in (200, 422)
        if put.status_code == 200:
            assert put.json()["file_retention_days"] >= 1


# ---------------------------------------------------------------------------
# Part 2 — guest upload restriction
# ---------------------------------------------------------------------------

class TestGuestUploadRestriction:

    def test_guest_upload_returns_403(self) -> None:
        """Guest with images in request → 403 before any processing."""
        raw = b"\xff\xd8\xff\xe0" + b"x" * 50
        b64 = base64.b64encode(raw).decode()
        payload = {
            "message": "mira esta imagen",
            "history": [],
            "images": [{"data": b64, "media_type": "image/jpeg"}],
        }
        with _client() as c:
            resp = c.post("/chat/message", json=payload)
        assert resp.status_code == 403

    def test_guest_no_images_not_blocked(self) -> None:
        """Guest without images → not blocked at upload gate (may get other error)."""
        payload = {
            "message": "hola",
            "history": [],
            "images": [],
        }
        with _client() as c:
            resp = c.post("/chat/message", json=payload)
        assert resp.status_code != 403

    def test_registered_user_upload_not_blocked(self) -> None:
        """Registered user with images → passes upload gate (202 or other non-403)."""
        raw = b"\xff\xd8\xff\xe0" + b"x" * 50
        b64 = base64.b64encode(raw).decode()
        payload = {
            "message": "mira esta imagen",
            "history": [],
            "images": [{"data": b64, "media_type": "image/jpeg"}],
        }
        token = make_user_token()

        # Mock save_uploaded_image to avoid disk writes and also mock the turn runner
        with patch("app.api.routes_chat.save_uploaded_image") as mock_save, \
             patch("app.api.routes_chat._run_turn_in_background"):
            mock_fa = MagicMock()
            mock_fa.id = 42
            mock_save.return_value = mock_fa
            with _client() as c:
                resp = c.post(
                    "/chat/message",
                    json=payload,
                    cookies={"sity_session": token},
                )
        assert resp.status_code != 403

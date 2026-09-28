"""Tests for file management Parts 3+4.

Part 3 — 500 MB storage limit:
  - get_user_storage_bytes returns correct sum
  - sum = 0 when user has no files
  - POST /chat/message with images over limit → 507
  - POST /chat/message with images under limit → not 507

Part 4 — auto-delete via expires_at + is_permanent:
  - Row with past expires_at → deleted
  - Row with future expires_at → kept
  - Row with is_permanent=True → never deleted even if expires_at is past
  - Row without expires_at (legacy) → falls back to created_at cutoff
  - Interval is 1 hour
"""
from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.main import app
from app.memory.models import FileArtifact
from helpers import make_user_token


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _mem_db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _add_artifact(
    db: Session,
    *,
    user_id: int = 1,
    file_size_bytes: int = 100,
    is_permanent: bool = False,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> FileArtifact:
    ts = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    fa = FileArtifact(
        user_id=user_id,
        artifact_type="image",
        filename=f"f_{id(ts)}_{int(time.monotonic()*1e6)}.jpg",
        rel_path="uploads/images/placeholder.jpg",
        mime_type="image/jpeg",
        source="chat_upload",
        file_size_bytes=file_size_bytes,
        is_permanent=is_permanent,
        expires_at=expires_at,
        created_at=ts,
    )
    db.add(fa)
    db.commit()
    db.refresh(fa)
    return fa


# ---------------------------------------------------------------------------
# Part 3 — get_user_storage_bytes
# ---------------------------------------------------------------------------

class TestGetUserStorageBytes:

    def test_sum_of_multiple_files(self) -> None:
        from app.chat.file_artifact import get_user_storage_bytes
        eng = _mem_db()
        with Session(eng) as db:
            _add_artifact(db, user_id=10, file_size_bytes=1000)
            _add_artifact(db, user_id=10, file_size_bytes=2000)
            _add_artifact(db, user_id=10, file_size_bytes=500)
            result = get_user_storage_bytes(db, 10)
        assert result == 3500

    def test_zero_when_no_files(self) -> None:
        from app.chat.file_artifact import get_user_storage_bytes
        eng = _mem_db()
        with Session(eng) as db:
            result = get_user_storage_bytes(db, 99)
        assert result == 0

    def test_only_counts_own_user(self) -> None:
        from app.chat.file_artifact import get_user_storage_bytes
        eng = _mem_db()
        with Session(eng) as db:
            _add_artifact(db, user_id=1, file_size_bytes=5000)
            _add_artifact(db, user_id=2, file_size_bytes=9000)
            assert get_user_storage_bytes(db, 1) == 5000
            assert get_user_storage_bytes(db, 2) == 9000


# ---------------------------------------------------------------------------
# Part 3 — 507 endpoint check
# ---------------------------------------------------------------------------

class TestStorageLimitEndpoint:

    def _image_payload(self, size_bytes: int = 50) -> dict:
        raw = b"\xff\xd8\xff\xe0" + b"x" * size_bytes
        b64 = base64.b64encode(raw).decode()
        return {
            "message": "mira",
            "history": [],
            "images": [{"data": b64, "media_type": "image/jpeg"}],
        }

    def test_over_limit_returns_507(self) -> None:
        token = make_user_token()
        # 1 MB limit; current usage is 1 048 500 B; incoming image is ~104 B
        # → total 1 048 604 > 1 048 576 (1 MB) → 507
        with patch("app.api.routes_chat.get_user_storage_bytes", return_value=1_048_500), \
             patch("app.api.routes_chat.load_default_config",
                   return_value={"storage": {"file_storage_limit_mb": 1}}):
            with _client() as c:
                resp = c.post(
                    "/chat/message",
                    json=self._image_payload(size_bytes=100),
                    cookies={"sity_session": token},
                )
        assert resp.status_code == 507

    def test_under_limit_not_507(self) -> None:
        token = make_user_token()
        with patch("app.api.routes_chat.get_user_storage_bytes", return_value=0), \
             patch("app.api.routes_chat.load_default_config",
                   return_value={"storage": {"file_storage_limit_mb": 500}}), \
             patch("app.api.routes_chat.save_uploaded_image") as mock_save, \
             patch("app.api.routes_chat._run_turn_in_background"):
            mock_fa = MagicMock()
            mock_fa.id = 1
            mock_save.return_value = mock_fa
            with _client() as c:
                resp = c.post(
                    "/chat/message",
                    json=self._image_payload(size_bytes=50),
                    cookies={"sity_session": token},
                )
        assert resp.status_code != 507


# ---------------------------------------------------------------------------
# Part 4 — delete_old_file_artifacts with expires_at + is_permanent
# ---------------------------------------------------------------------------

@pytest.fixture()
def retention_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import app.chat.file_retention as _ret
    monkeypatch.setattr(_ret, "PROJECT_ROOT", tmp_path)
    return tmp_path


class TestDeleteWithExpiresAt:

    def test_past_expires_at_deletes_row(self, db_session: Session, retention_root: Path) -> None:
        from app.chat.file_retention import delete_old_file_artifacts
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        fa = _add_artifact(db_session, expires_at=past, user_id=20)
        result = delete_old_file_artifacts(db_session)
        assert result["deleted"] >= 1
        assert db_session.get(FileArtifact, fa.id) is None

    def test_future_expires_at_keeps_row(self, db_session: Session, retention_root: Path) -> None:
        from app.chat.file_retention import delete_old_file_artifacts
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
        fa = _add_artifact(db_session, expires_at=future, user_id=21)
        delete_old_file_artifacts(db_session)
        assert db_session.get(FileArtifact, fa.id) is not None

    def test_permanent_file_never_deleted(self, db_session: Session, retention_root: Path) -> None:
        from app.chat.file_retention import delete_old_file_artifacts
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        fa = _add_artifact(db_session, expires_at=past, is_permanent=True, user_id=22)
        result = delete_old_file_artifacts(db_session)
        assert db_session.get(FileArtifact, fa.id) is not None

    def test_legacy_row_uses_created_at_cutoff(self, db_session: Session, retention_root: Path) -> None:
        from app.chat.file_retention import delete_old_file_artifacts
        # No expires_at, created_at 10 days ago → should be deleted with older_than_days=7
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        fa = _add_artifact(db_session, created_at=old, user_id=23)
        result = delete_old_file_artifacts(db_session, older_than_days=7)
        assert result["deleted"] >= 1
        assert db_session.get(FileArtifact, fa.id) is None

    def test_legacy_recent_row_not_deleted(self, db_session: Session, retention_root: Path) -> None:
        from app.chat.file_retention import delete_old_file_artifacts
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        fa = _add_artifact(db_session, created_at=recent, user_id=24)
        delete_old_file_artifacts(db_session, older_than_days=7)
        assert db_session.get(FileArtifact, fa.id) is not None

    def test_interval_is_one_hour(self) -> None:
        from app.chat.file_retention import _INTERVAL_HOURS
        assert _INTERVAL_HOURS == 1

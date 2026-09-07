"""Tests for file_retention.delete_old_file_artifacts.

Coverage:
  - Files older than cutoff: DB row deleted + disk file removed
  - Files newer than cutoff: not touched
  - Missing disk file: DB row still deleted (best-effort)
  - older_than_days parameter respected
  - Returns correct deleted count
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session

from app.memory.models import FileArtifact


@pytest.fixture()
def retention_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import app.chat.file_retention as _ret
    monkeypatch.setattr(_ret, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _make_artifact(
    db: Session,
    *,
    user_id: int = 1,
    tmp_path: Path,
    created_at: datetime,
    write_file: bool = True,
) -> tuple[FileArtifact, Path]:
    filename = f"ret_{id(created_at)}_{int(time.time() * 1000)}.jpg"
    rel_path = f"uploads/images/{filename}"
    file_path = tmp_path / "uploads" / "images" / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if write_file:
        file_path.write_bytes(b"\xff\xd8\xff\xe0test")

    fa = FileArtifact(
        user_id=user_id,
        artifact_type="image",
        filename=filename,
        rel_path=rel_path,
        mime_type="image/jpeg",
        source="chat_upload",
        created_at=created_at,
    )
    db.add(fa)
    db.commit()
    db.refresh(fa)
    return fa, file_path


# ---------------------------------------------------------------------------
# Core retention logic
# ---------------------------------------------------------------------------

class TestDeleteOldFileArtifacts:
    def test_old_file_deleted_from_db(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        fa, _ = _make_artifact(db_session, tmp_path=retention_root, created_at=old_ts)

        result = delete_old_file_artifacts(db_session, older_than_days=7)

        assert result["deleted"] >= 1
        refreshed = db_session.get(FileArtifact, fa.id)
        assert refreshed is None

    def test_old_file_deleted_from_disk(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        _, file_path = _make_artifact(db_session, tmp_path=retention_root, created_at=old_ts)
        assert file_path.exists()

        delete_old_file_artifacts(db_session, older_than_days=7)

        assert not file_path.exists()

    def test_recent_file_not_deleted(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        recent_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        fa, file_path = _make_artifact(db_session, tmp_path=retention_root, created_at=recent_ts)

        result = delete_old_file_artifacts(db_session, older_than_days=7)

        assert db_session.get(FileArtifact, fa.id) is not None
        assert file_path.exists()

    def test_missing_disk_file_still_deletes_db_row(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        fa, file_path = _make_artifact(
            db_session, tmp_path=retention_root, created_at=old_ts, write_file=False
        )
        assert not file_path.exists()

        result = delete_old_file_artifacts(db_session, older_than_days=7)

        assert result["deleted"] >= 1
        assert db_session.get(FileArtifact, fa.id) is None

    def test_returns_correct_deleted_count(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        recent_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)

        _make_artifact(db_session, tmp_path=retention_root, created_at=old_ts, user_id=91)
        _make_artifact(db_session, tmp_path=retention_root, created_at=old_ts, user_id=91)
        _make_artifact(db_session, tmp_path=retention_root, created_at=recent_ts, user_id=91)

        result = delete_old_file_artifacts(db_session, older_than_days=7)

        assert result["deleted"] >= 2

    def test_custom_older_than_days(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        ts_3days = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
        fa, _ = _make_artifact(db_session, tmp_path=retention_root, created_at=ts_3days, user_id=92)

        # With older_than_days=7: should NOT be deleted
        delete_old_file_artifacts(db_session, older_than_days=7)
        assert db_session.get(FileArtifact, fa.id) is not None

        # With older_than_days=2: should BE deleted
        delete_old_file_artifacts(db_session, older_than_days=2)
        assert db_session.get(FileArtifact, fa.id) is None

    def test_result_ok_true_on_success(
        self, db_session: Session, retention_root: Path
    ) -> None:
        from app.chat.file_retention import delete_old_file_artifacts

        result = delete_old_file_artifacts(db_session, older_than_days=7)
        assert result["ok"] is True
        assert isinstance(result["errors"], list)

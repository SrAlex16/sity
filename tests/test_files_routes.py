"""Tests for GET/DELETE /files and GET /files/export.

Coverage:
  - GET /files: list files, pagination, isolation (user A cannot see user B's files)
  - DELETE /files/{id}: delete own file, 404 for missing/other-user's file, disk+DB sync
  - DELETE /files: delete all own files
  - GET /files/export: zip download, valid zip contents
  - All endpoints: 401 for guests
"""
from __future__ import annotations

import io
import uuid as _uuid_mod
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.memory.db import engine
from app.memory.models import FileArtifact


def _uid() -> str:
    return _uuid_mod.uuid4().hex[:8]


def _register_and_login(client: TestClient) -> tuple[str, int]:
    email = f"files_{_uid()}@sity-test.invalid"
    resp = client.post("/auth/register", json={"email": email, "password": "Str0ngPass1"})
    assert resp.status_code == 201, resp.text
    return resp.cookies["sity_session"], resp.json()["id"]


def _insert_artifact(
    user_id: int,
    tmp_path: Path,
    *,
    artifact_type: str = "image",
    source: str = "chat_upload",
) -> tuple[int, Path]:
    """Insert a FileArtifact and write a real dummy file to disk. Returns (id, path)."""
    filename = f"test_{_uid()}.jpg"
    rel_path = f"uploads/images/{filename}"
    file_path = tmp_path / "uploads" / "images" / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal JPEG-ish bytes

    with Session(engine) as db:
        fa = FileArtifact(
            user_id=user_id,
            artifact_type=artifact_type,
            filename=filename,
            rel_path=rel_path,
            mime_type="image/jpeg",
            source=source,
        )
        db.add(fa)
        db.commit()
        db.refresh(fa)
        return fa.id, file_path  # type: ignore[return-value]


@pytest.fixture()
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect PROJECT_ROOT in routes_files so disk operations use tmp_path."""
    import app.api.routes_files as _rf
    monkeypatch.setattr(_rf, "PROJECT_ROOT", tmp_path)
    # Also patch file_retention if imported
    try:
        import app.chat.file_retention as _ret
        monkeypatch.setattr(_ret, "PROJECT_ROOT", tmp_path)
    except Exception:
        pass
    return tmp_path


# ---------------------------------------------------------------------------
# GET /files — list
# ---------------------------------------------------------------------------

class TestListFiles:
    def test_guest_returns_401(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/files")
        assert resp.status_code == 401

    def test_empty_list_for_new_user(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, _ = _register_and_login(client)
        resp = client.get("/files", cookies={"sity_session": cookie})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["files"] == []
        assert data["total"] == 0

    def test_lists_own_files(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)
        _insert_artifact(user_id, upload_dir)

        resp = client.get("/files", cookies={"sity_session": cookie})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["files"]) == 2

    def test_isolation_user_a_cannot_see_user_b_files(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        _, user_a_id = _register_and_login(client)
        cookie_b, user_b_id = _register_and_login(client)

        _insert_artifact(user_a_id, upload_dir)

        resp = client.get("/files", cookies={"sity_session": cookie_b})

        data = resp.json()
        assert data["total"] == 0
        assert data["files"] == []

    def test_file_item_has_expected_fields(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)

        resp = client.get("/files", cookies={"sity_session": cookie})
        item = resp.json()["files"][0]

        for field in ("id", "artifact_type", "filename", "url", "source", "created_at"):
            assert field in item, f"Missing field: {field}"

    def test_pagination(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        for _ in range(5):
            _insert_artifact(user_id, upload_dir)

        resp = client.get("/files?page=1&size=3", cookies={"sity_session": cookie})
        data = resp.json()

        assert data["total"] == 5
        assert len(data["files"]) == 3
        assert data["page"] == 1
        assert data["size"] == 3


# ---------------------------------------------------------------------------
# DELETE /files/{id} — single delete
# ---------------------------------------------------------------------------

class TestDeleteFile:
    def test_guest_returns_401(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.delete("/files/1")
        assert resp.status_code == 401

    def test_deletes_own_file_from_db(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        artifact_id, _ = _insert_artifact(user_id, upload_dir)

        resp = client.delete(f"/files/{artifact_id}", cookies={"sity_session": cookie})

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Confirm gone from list
        list_resp = client.get("/files", cookies={"sity_session": cookie})
        assert list_resp.json()["total"] == 0

    def test_deletes_file_from_disk(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        artifact_id, file_path = _insert_artifact(user_id, upload_dir)
        assert file_path.exists()

        client.delete(f"/files/{artifact_id}", cookies={"sity_session": cookie})

        assert not file_path.exists()

    def test_missing_id_returns_404(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, _ = _register_and_login(client)
        resp = client.delete("/files/999999", cookies={"sity_session": cookie})
        assert resp.status_code == 404

    def test_other_user_file_returns_404(self, upload_dir: Path) -> None:
        """Accessing another user's file ID returns 404, not 403 — never reveals existence."""
        client = TestClient(app, raise_server_exceptions=True)
        _, user_a_id = _register_and_login(client)
        cookie_b, _ = _register_and_login(client)
        artifact_id, _ = _insert_artifact(user_a_id, upload_dir)

        resp = client.delete(f"/files/{artifact_id}", cookies={"sity_session": cookie_b})

        assert resp.status_code == 404

    def test_db_row_removed_after_delete(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        artifact_id, _ = _insert_artifact(user_id, upload_dir)

        client.delete(f"/files/{artifact_id}", cookies={"sity_session": cookie})

        with Session(engine) as db:
            row = db.get(FileArtifact, artifact_id)
        assert row is None


# ---------------------------------------------------------------------------
# DELETE /files — bulk delete
# ---------------------------------------------------------------------------

class TestDeleteAllFiles:
    def test_guest_returns_401(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.delete("/files")
        assert resp.status_code == 401

    def test_deletes_all_own_files(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)
        _insert_artifact(user_id, upload_dir)

        resp = client.delete("/files", cookies={"sity_session": cookie})

        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2
        assert client.get("/files", cookies={"sity_session": cookie}).json()["total"] == 0

    def test_does_not_delete_other_user_files(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        _, user_a_id = _register_and_login(client)
        cookie_b, user_b_id = _register_and_login(client)
        _insert_artifact(user_a_id, upload_dir)
        _insert_artifact(user_b_id, upload_dir)

        client.delete("/files", cookies={"sity_session": cookie_b})

        # User A's file must still exist
        with Session(engine) as db:
            from sqlmodel import select
            rows = db.exec(
                select(FileArtifact).where(FileArtifact.user_id == user_a_id)
            ).all()
        assert len(rows) == 1

    def test_files_removed_from_disk(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _, p1 = _insert_artifact(user_id, upload_dir)
        _, p2 = _insert_artifact(user_id, upload_dir)
        assert p1.exists() and p2.exists()

        client.delete("/files", cookies={"sity_session": cookie})

        assert not p1.exists()
        assert not p2.exists()

    def test_empty_delete_returns_zero(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, _ = _register_and_login(client)
        resp = client.delete("/files", cookies={"sity_session": cookie})
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# GET /files/export — zip download
# ---------------------------------------------------------------------------

class TestExportFiles:
    def test_guest_returns_401(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/files/export")
        assert resp.status_code == 401

    def test_returns_zip_content_type(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)

        resp = client.get("/files/export", cookies={"sity_session": cookie})

        assert resp.status_code == 200
        assert "zip" in resp.headers.get("content-type", "")

    def test_zip_contains_user_files(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)
        _insert_artifact(user_id, upload_dir)

        resp = client.get("/files/export", cookies={"sity_session": cookie})
        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()

        assert len(names) == 2

    def test_zip_is_valid(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)

        resp = client.get("/files/export", cookies={"sity_session": cookie})
        buf = io.BytesIO(resp.content)

        assert zipfile.is_zipfile(buf)

    def test_zip_does_not_include_other_user_files(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        _, user_a_id = _register_and_login(client)
        cookie_b, user_b_id = _register_and_login(client)
        _insert_artifact(user_a_id, upload_dir)
        artifact_b_id, _ = _insert_artifact(user_b_id, upload_dir)

        resp = client.get("/files/export", cookies={"sity_session": cookie_b})
        buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()

        assert len(names) == 1

    def test_empty_export_returns_valid_empty_zip(self) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, _ = _register_and_login(client)

        resp = client.get("/files/export", cookies={"sity_session": cookie})
        buf = io.BytesIO(resp.content)

        assert zipfile.is_zipfile(buf)
        with zipfile.ZipFile(buf) as zf:
            assert zf.namelist() == []

    def test_content_disposition_filename(self, upload_dir: Path) -> None:
        client = TestClient(app, raise_server_exceptions=True)
        cookie, user_id = _register_and_login(client)
        _insert_artifact(user_id, upload_dir)

        resp = client.get("/files/export", cookies={"sity_session": cookie})
        cd = resp.headers.get("content-disposition", "")

        assert "sity-archivos.zip" in cd

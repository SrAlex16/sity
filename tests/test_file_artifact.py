"""Tests for file_artifact.py — image saving to disk + FileArtifact DB inventory."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from sqlmodel import Session, select

# 1×1 transparent PNG (valid image, minimal size)
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect UPLOADS_IMAGES_DIR to a temp dir for the duration of the test."""
    import app.chat.file_artifact as _fa
    target = tmp_path / "uploads" / "images"
    target.mkdir(parents=True)
    monkeypatch.setattr(_fa, "UPLOADS_IMAGES_DIR", target)
    return target


# ------------------------------------------------------------------ #
# 1. save_uploaded_image — file written to disk                       #
# ------------------------------------------------------------------ #

def test_save_uploaded_image_creates_file(db_session: Session, upload_dir: Path) -> None:
    from app.chat.file_artifact import save_uploaded_image

    row = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)

    saved = upload_dir / row.filename
    assert saved.exists(), "File must be written to disk"
    assert saved.read_bytes() == base64.b64decode(_PNG_B64)


def test_save_uploaded_image_correct_extension(db_session: Session, upload_dir: Path) -> None:
    from app.chat.file_artifact import save_uploaded_image

    row = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    assert row.filename.endswith(".png")


def test_save_uploaded_image_db_row_fields(db_session: Session, upload_dir: Path) -> None:
    from app.chat.file_artifact import save_uploaded_image
    from app.memory.models import FileArtifact

    row = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=42)

    persisted = db_session.get(FileArtifact, row.id)
    assert persisted is not None
    assert persisted.user_id == 42
    assert persisted.artifact_type == "image"
    assert persisted.source == "chat_upload"
    assert persisted.mime_type == "image/png"
    assert persisted.rel_path == f"uploads/images/{row.filename}"
    assert persisted.chat_message_id is None  # not linked in Paso 1


def test_save_uploaded_image_guest_user_null(db_session: Session, upload_dir: Path) -> None:
    from app.chat.file_artifact import save_uploaded_image

    row = save_uploaded_image(_PNG_B64, "image/jpeg", db_session, user_id=None)
    assert row.user_id is None


# ------------------------------------------------------------------ #
# 2. register_capture_artifact — existing file registered             #
# ------------------------------------------------------------------ #

def test_register_capture_artifact_image(db_session: Session) -> None:
    from app.api.schemas import ChatArtifact
    from app.chat.file_artifact import register_capture_artifact
    from app.memory.models import FileArtifact

    artifact = ChatArtifact(
        type="image",
        url="/captures/camera/snap_001.jpg",
        filename="snap_001.jpg",
        mime_type="image/jpeg",
    )
    row = register_capture_artifact(artifact, db_session, user_id=7)

    assert row is not None
    persisted = db_session.get(FileArtifact, row.id)
    assert persisted is not None
    assert persisted.artifact_type == "image"
    assert persisted.source == "camera_capture"
    assert persisted.rel_path == "captures/camera/snap_001.jpg"
    assert persisted.filename == "snap_001.jpg"
    assert persisted.user_id == 7


def test_register_capture_artifact_audio(db_session: Session) -> None:
    from app.api.schemas import ChatArtifact
    from app.chat.file_artifact import register_capture_artifact

    artifact = ChatArtifact(
        type="audio",
        url="/captures/audio/rec_001.wav",
        filename="rec_001.wav",
        mime_type="audio/wav",
    )
    row = register_capture_artifact(artifact, db_session, user_id=7)

    assert row is not None
    assert row.artifact_type == "audio"
    assert row.source == "camera_capture"
    assert row.rel_path == "captures/audio/rec_001.wav"


def test_register_capture_artifact_invalid_url_returns_none(db_session: Session) -> None:
    from app.api.schemas import ChatArtifact
    from app.chat.file_artifact import register_capture_artifact

    artifact = ChatArtifact(
        type="image",
        url="relative/path/no/slash",
        filename="foo.jpg",
        mime_type="image/jpeg",
    )
    result = register_capture_artifact(artifact, db_session, user_id=1)
    assert result is None


# ------------------------------------------------------------------ #
# 3. user_id_from_session helper                                      #
# ------------------------------------------------------------------ #

def test_user_id_from_session_authenticated() -> None:
    from app.chat.file_artifact import user_id_from_session
    assert user_id_from_session("user:42") == 42


def test_user_id_from_session_guest() -> None:
    from app.chat.file_artifact import user_id_from_session
    assert user_id_from_session("guest") is None


def test_user_id_from_session_default() -> None:
    from app.chat.file_artifact import user_id_from_session
    assert user_id_from_session("default") is None


# ------------------------------------------------------------------ #
# 4. User isolation — user A cannot see user B's FileArtifact rows   #
# ------------------------------------------------------------------ #

def test_file_artifact_user_isolation(db_session: Session, upload_dir: Path) -> None:
    from app.chat.file_artifact import save_uploaded_image
    from app.memory.models import FileArtifact

    row_a = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=101)
    row_b = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=202)

    user_a_rows = db_session.exec(
        select(FileArtifact).where(FileArtifact.user_id == 101)
    ).all()
    user_b_rows = db_session.exec(
        select(FileArtifact).where(FileArtifact.user_id == 202)
    ).all()

    a_ids = {r.id for r in user_a_rows}
    b_ids = {r.id for r in user_b_rows}

    assert row_a.id in a_ids
    assert row_b.id not in a_ids
    assert row_b.id in b_ids
    assert row_a.id not in b_ids

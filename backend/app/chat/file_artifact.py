"""file_artifact.py — save files to disk and register them in the FileArtifact inventory.

Two entry points:
  save_uploaded_image()    — for images arriving as base64 in ChatMessageRequest.images.
                             Decodes, writes to uploads/images/, inserts FileArtifact row.
  register_capture_artifact() — for files already on disk (camera/audio captures).
                             Inserts a FileArtifact row pointing at the existing path.

The model call path is unchanged: base64 still goes to the Claude API as before.
These functions only build the persistent inventory on disk and in the DB.
"""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

from sqlmodel import Session

from app.api.schemas import ChatArtifact
from app.memory.models import FileArtifact
from app.trace.logger import write_log

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOADS_IMAGES_DIR = PROJECT_ROOT / "uploads" / "images"

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def save_uploaded_image(
    base64_data: str,
    media_type: str,
    db: Session,
    user_id: int | None,
) -> FileArtifact:
    """Decode base64 image, write to disk, register in FileArtifact.

    Returns the persisted FileArtifact row. The base64 data is NOT consumed here —
    callers keep it in the request object to pass to the Claude API unchanged.
    """
    UPLOADS_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    ext = _MIME_TO_EXT.get(media_type, ".jpg")
    filename = uuid.uuid4().hex + ext
    file_path = UPLOADS_IMAGES_DIR / filename
    rel_path = f"uploads/images/{filename}"

    raw = base64.b64decode(base64_data)
    file_path.write_bytes(raw)

    row = FileArtifact(
        user_id=user_id,
        artifact_type="image",
        filename=filename,
        rel_path=rel_path,
        mime_type=media_type,
        source="chat_upload",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    write_log(
        level="INFO",
        module="file_artifact",
        event="uploaded_image_saved",
        payload={"filename": filename, "mime_type": media_type, "user_id": user_id},
    )
    return row


def register_capture_artifact(
    artifact: ChatArtifact,
    db: Session,
    user_id: int | None,
) -> FileArtifact | None:
    """Register an already-saved capture file (camera or audio) in FileArtifact.

    The file was already written to disk by the capture tool. This function only
    adds the inventory row so the file manager can list/delete it later.

    URL format expected: "/captures/camera/foo.jpg" or "/captures/audio/foo.wav"
    → rel_path = "captures/camera/foo.jpg"
    Returns None if the URL format is unexpected (never raises).
    """
    if not artifact.url.startswith("/"):
        return None

    rel_path = artifact.url.lstrip("/")
    artifact_type = "image" if artifact.type == "image" else "audio"

    row = FileArtifact(
        user_id=user_id,
        artifact_type=artifact_type,
        filename=artifact.filename,
        rel_path=rel_path,
        mime_type=artifact.mime_type,
        source="camera_capture",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    write_log(
        level="INFO",
        module="file_artifact",
        event="capture_artifact_registered",
        payload={"filename": artifact.filename, "type": artifact_type, "user_id": user_id},
    )
    return row


def wire_uploaded_images_to_message(
    db: Session,
    artifact_ids: list[int],
    chat_message_id: int,
) -> None:
    """Link FileArtifact rows to the ChatMessage that triggered their upload.

    Called immediately after the user's ChatMessage is persisted so that
    _load_history() can find images by chat_message_id in later turns.
    Best-effort: if any row is missing, the rest are still updated.
    """
    if not artifact_ids:
        return
    for aid in artifact_ids:
        row = db.get(FileArtifact, aid)
        if row is not None and row.chat_message_id is None:
            row.chat_message_id = chat_message_id
            db.add(row)
    db.commit()


def user_id_from_session(session_id: str) -> int | None:
    """Extract numeric user_id from session_id ('user:42' → 42, else None)."""
    if session_id.startswith("user:"):
        try:
            return int(session_id.split(":", 1)[1])
        except (ValueError, IndexError):
            pass
    return None

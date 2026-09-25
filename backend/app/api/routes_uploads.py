from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.auth.dependencies import CurrentUser, get_current_user, require_admin
from app.memory.db import get_session
from app.memory.models import ChatMessage, FileArtifact

router = APIRouter(prefix="/uploads", tags=["uploads"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOADS_ROOT = PROJECT_ROOT / "uploads"

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _safe_upload_path(kind: str, filename: str) -> Path:
    if kind not in {"images"}:
        raise HTTPException(status_code=404, detail="Unknown upload type")

    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = (UPLOADS_ROOT / kind / filename).resolve()
    root = (UPLOADS_ROOT / kind).resolve()

    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="Invalid path")

    if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Upload not found")

    return path


@router.get("/images/{filename}")
def get_uploaded_image(
    filename: str,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    path = _safe_upload_path("images", filename)

    rel_path = f"uploads/images/{filename}"
    artifact = db.exec(select(FileArtifact).where(FileArtifact.rel_path == rel_path)).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    if current.is_authenticated:
        if artifact.user_id != current.user_id:
            raise HTTPException(status_code=404, detail="Upload not found")
    else:
        # Guest path
        if artifact.user_id is not None:
            raise HTTPException(status_code=404, detail="Upload not found")
        if artifact.chat_message_id is not None:
            msg = db.get(ChatMessage, artifact.chat_message_id)
            if msg is None or msg.session_id != current.session_id:
                raise HTTPException(status_code=404, detail="Upload not found")
        # chat_message_id IS NULL: brief window before wire_uploaded_images_to_message
        # runs in the background turn. user_id IS NULL scopes to guest uploads; allow.

    suffix = path.suffix.lower()
    media_type = (
        "image/png" if suffix == ".png"
        else "image/webp" if suffix == ".webp"
        else "image/gif" if suffix == ".gif"
        else "image/jpeg"
    )
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/bug-reports/{filename}")
def get_bug_report_attachment(
    filename: str,
    current: CurrentUser = Depends(require_admin),
):
    """Serve a bug-report attachment image. Admin only."""
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = (UPLOADS_ROOT / "bug-reports" / filename).resolve()
    root = (UPLOADS_ROOT / "bug-reports").resolve()

    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="Invalid path")

    if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")

    suffix = path.suffix.lower()
    media_type = (
        "image/png" if suffix == ".png"
        else "image/webp" if suffix == ".webp"
        else "image/gif" if suffix == ".gif"
        else "image/jpeg"
    )
    return FileResponse(path, media_type=media_type, filename=filename)

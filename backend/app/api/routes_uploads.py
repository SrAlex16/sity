from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

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
def get_uploaded_image(filename: str):
    path = _safe_upload_path("images", filename)
    suffix = path.suffix.lower()
    media_type = (
        "image/png" if suffix == ".png"
        else "image/webp" if suffix == ".webp"
        else "image/gif" if suffix == ".gif"
        else "image/jpeg"
    )
    return FileResponse(path, media_type=media_type, filename=filename)

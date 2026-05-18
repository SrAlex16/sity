from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


router = APIRouter(prefix="/captures", tags=["captures"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURES_ROOT = PROJECT_ROOT / "captures"

ALLOWED_EXTENSIONS = {
    "camera": {".jpg", ".jpeg", ".png"},
    "audio": {".wav", ".mp3", ".ogg", ".m4a"},
}


def safe_capture_path(kind: str, filename: str) -> Path:
    if kind not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Unknown capture type")

    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = (CAPTURES_ROOT / kind / filename).resolve()
    root = (CAPTURES_ROOT / kind).resolve()

    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="Invalid path")

    if path.suffix.lower() not in ALLOWED_EXTENSIONS[kind]:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Capture not found")

    return path


@router.get("/camera/{filename}")
def get_camera_capture(filename: str):
    path = safe_capture_path("camera", filename)
    return FileResponse(path, media_type="image/jpeg", filename=filename)


@router.get("/audio/{filename}")
def get_audio_capture(filename: str):
    path = safe_capture_path("audio", filename)
    return FileResponse(path, media_type="audio/wav", filename=filename)

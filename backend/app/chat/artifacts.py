from __future__ import annotations

from pathlib import Path

from app.api.schemas import ChatArtifact


def capture_artifact_from_path(path_value: str) -> ChatArtifact | None:
    if not path_value:
        return None

    path = Path(path_value)
    filename = path.name
    suffix = path.suffix.lower()

    if suffix in {".jpg", ".jpeg", ".png"}:
        return ChatArtifact(
            type="image",
            url=f"/captures/camera/{filename}",
            filename=filename,
            mime_type="image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png",
        )

    if suffix in {".wav", ".mp3", ".ogg", ".m4a"}:
        return ChatArtifact(
            type="audio",
            url=f"/captures/audio/{filename}",
            filename=filename,
            mime_type="audio/wav" if suffix == ".wav" else None,
        )

    return None

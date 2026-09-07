"""routes_files.py — file manager endpoints.

GET  /files            list user's FileArtifact rows (paginated)
GET  /files/export     download zip of all user's files
DELETE /files/{id}     delete one file (disk + DB)
DELETE /files          delete all user's files (disk + DB)

Isolation: all queries filter by user_id == current.user.id.
Guests (user_id=None) are rejected with 401 — their files cannot
be safely isolated since all guest rows share user_id=None.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.auth.dependencies import CurrentUser, get_current_user
from app.memory.db import get_session
from app.memory.models import FileArtifact
from app.trace.logger import write_log

router = APIRouter(prefix="/files", tags=["files"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _require_user(current: CurrentUser) -> int:
    if current.is_guest or current.user is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    assert current.user.id is not None
    return current.user.id


def _file_url(fa: FileArtifact) -> str:
    if fa.source == "chat_upload":
        return f"/uploads/images/{fa.filename}"
    return f"/{fa.rel_path}"


class FileItem(BaseModel):
    id: int
    artifact_type: str
    filename: str
    url: str
    mime_type: Optional[str] = None
    source: str
    size_bytes: Optional[int] = None
    created_at: Optional[datetime] = None


class FilesListResponse(BaseModel):
    ok: bool
    total: int
    page: int
    size: int
    files: list[FileItem]


def _to_item(fa: FileArtifact) -> FileItem:
    path = PROJECT_ROOT / fa.rel_path
    size_bytes: Optional[int] = None
    try:
        if path.exists():
            size_bytes = path.stat().st_size
    except Exception:
        pass
    created = fa.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return FileItem(
        id=fa.id,  # type: ignore[arg-type]
        artifact_type=fa.artifact_type,
        filename=fa.filename,
        url=_file_url(fa),
        mime_type=fa.mime_type,
        source=fa.source,
        size_bytes=size_bytes,
        created_at=created,
    )


# GET /files/export must be declared BEFORE DELETE /files/{file_id}
# so that "export" is not mismatched as a file_id on a different method.
# (In practice HTTP methods differ, but explicit ordering is clearer.)

@router.get("/export")
def export_files(
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Download a zip archive with all the user's files."""
    user_id = _require_user(current)
    rows = db.exec(
        select(FileArtifact)
        .where(FileArtifact.user_id == user_id)
        .order_by(col(FileArtifact.id))
    ).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen: set[str] = set()
        for fa in rows:
            path = (PROJECT_ROOT / fa.rel_path).resolve()
            if not path.exists() or not path.is_file():
                continue
            name = fa.filename
            if name in seen:
                name = f"{fa.id}_{fa.filename}"
            seen.add(name)
            zf.write(path, arcname=name)
    buf.seek(0)

    write_log(
        level="INFO",
        module="files",
        event="files_exported",
        payload={"user_id": user_id, "file_count": len(rows)},
    )
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="sity-archivos.zip"',
        },
    )


@router.get("", response_model=FilesListResponse)
def list_files(
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    user_id = _require_user(current)
    page = max(1, page)
    size = max(1, min(size, 100))
    offset = (page - 1) * size

    total: int = db.exec(
        select(func.count()).select_from(FileArtifact).where(FileArtifact.user_id == user_id)
    ).one()

    rows = db.exec(
        select(FileArtifact)
        .where(FileArtifact.user_id == user_id)
        .order_by(col(FileArtifact.id).desc())
        .offset(offset)
        .limit(size)
    ).all()

    return FilesListResponse(
        ok=True,
        total=total,
        page=page,
        size=size,
        files=[_to_item(fa) for fa in rows],
    )


@router.delete("/{file_id}", status_code=200)
def delete_file(
    file_id: int,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Delete one file. Returns 404 whether the ID doesn't exist or belongs to another user
    (never reveals whether a given ID exists in the system)."""
    user_id = _require_user(current)
    fa = db.get(FileArtifact, file_id)
    if fa is None or fa.user_id != user_id:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    path = (PROJECT_ROOT / fa.rel_path).resolve()
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass

    db.delete(fa)
    db.commit()

    write_log(
        level="INFO",
        module="files",
        event="file_deleted",
        payload={"file_id": file_id, "user_id": user_id, "filename": fa.filename},
    )
    return {"ok": True, "deleted": file_id}


@router.delete("", status_code=200)
def delete_all_files(
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Delete all files for the current user (disk + DB)."""
    user_id = _require_user(current)
    rows = db.exec(
        select(FileArtifact).where(FileArtifact.user_id == user_id)
    ).all()

    deleted = 0
    for fa in rows:
        path = (PROJECT_ROOT / fa.rel_path).resolve()
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except Exception:
            pass
        db.delete(fa)
        deleted += 1

    if deleted:
        db.commit()

    write_log(
        level="INFO",
        module="files",
        event="files_deleted_all",
        payload={"user_id": user_id, "deleted_count": deleted},
    )
    return {"ok": True, "deleted": deleted}

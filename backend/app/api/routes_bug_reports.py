"""routes_bug_reports.py — user bug report submission and admin listing.

POST   /bug-report           submit a report (any role, including Guest)
GET    /bug-reports          list reports (admin only)
GET    /bug-reports/{id}     full report detail (admin only)
GET    /bug-reports/{id}/download  JSON download (admin only)
DELETE /bug-reports/{id}     delete one report + attachments (admin only)
DELETE /bug-reports          body: {ids:[…]} — delete many (admin only)
"""
from __future__ import annotations

import base64
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, field_validator
from sqlmodel import Session, col, select

from app.auth.dependencies import CurrentUser, get_current_user, require_admin
from app.memory.db import get_session
from app.memory.models import BugReport
from app.trace.logger import write_log

router = APIRouter(tags=["bug-reports"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ATTACHMENTS_DIR = PROJECT_ROOT / "uploads" / "bug-reports"

_VALID_SEVERITIES = {"baja", "media", "alta", "crítica"}
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_ATTACHMENTS = 5


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT),
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        return "unknown"


# ── Request / Response schemas ────────────────────────────────────────────────

class AttachmentInput(BaseModel):
    data: str        # base64-encoded bytes
    media_type: str  # image/jpeg | image/png | image/webp | image/gif

    @field_validator("media_type")
    @classmethod
    def _valid_mime(cls, v: str) -> str:
        if v not in _MIME_TO_EXT:
            raise ValueError(f"Tipo de imagen no soportado: {v}")
        return v


class BugReportSubmitRequest(BaseModel):
    observations: str
    severity: str = "media"
    attachments: list[AttachmentInput] = []

    @field_validator("severity")
    @classmethod
    def _valid_severity(cls, v: str) -> str:
        if v not in _VALID_SEVERITIES:
            raise ValueError(f"Severidad inválida: {v}. Usa baja, media, alta o crítica.")
        return v

    @field_validator("observations")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Las observaciones no pueden estar vacías.")
        return v


class BugReportListItem(BaseModel):
    id: int
    created_at: datetime
    severity: str
    role: Optional[str]
    has_attachments: bool


class BugReportListResponse(BaseModel):
    ok: bool
    total: int
    reports: list[BugReportListItem]


class AttachmentItem(BaseModel):
    filename: str
    url: str
    mime_type: Optional[str]


class BugReportDetailResponse(BaseModel):
    id: int
    created_at: datetime
    severity: str
    observations: Optional[str]
    session_id: Optional[str]
    user_id: Optional[int]
    role: Optional[str]
    user_agent: Optional[str]
    git_commit: Optional[str]
    attachments: list[AttachmentItem]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_attachment(attachment: AttachmentInput, report_id_hint: str) -> dict:
    """Decode base64, write to disk, return {filename, rel_path, mime_type}."""
    _ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = _MIME_TO_EXT[attachment.media_type]
    filename = f"{report_id_hint}_{uuid.uuid4().hex}{ext}"
    rel_path = f"uploads/bug-reports/{filename}"
    raw = base64.b64decode(attachment.data)
    (_ATTACHMENTS_DIR / filename).write_bytes(raw)
    return {"filename": filename, "rel_path": rel_path, "mime_type": attachment.media_type}


def _attachment_url(filename: str) -> str:
    return f"/uploads/bug-reports/{filename}"


def _parse_attachments(attachments_json: str) -> list[AttachmentItem]:
    try:
        items = json.loads(attachments_json)
    except Exception:
        return []
    return [
        AttachmentItem(
            filename=a.get("filename", ""),
            url=_attachment_url(a.get("filename", "")),
            mime_type=a.get("mime_type"),
        )
        for a in items
        if a.get("filename")
    ]


def _to_detail(report: BugReport) -> BugReportDetailResponse:
    created = report.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return BugReportDetailResponse(
        id=report.id,  # type: ignore[arg-type]
        created_at=created,
        severity=report.severity,
        observations=report.observations,
        session_id=report.session_id,
        user_id=report.user_id,
        role=report.role,
        user_agent=report.user_agent,
        git_commit=report.git_commit,
        attachments=_parse_attachments(report.attachments_json),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/bug-report", status_code=201)
def submit_bug_report(
    body: BugReportSubmitRequest,
    http_request: Request,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
):
    """Submit a bug report. Accessible to any role including Guest."""
    if len(body.attachments) > _MAX_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {_MAX_ATTACHMENTS} archivos adjuntos por reporte.",
        )
    for att in body.attachments:
        try:
            raw_size = len(base64.b64decode(att.data, validate=True))
        except Exception:
            raise HTTPException(status_code=400, detail="Adjunto con datos base64 inválidos.")
        if raw_size > _MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail="Un adjunto supera el límite de 5 MB.")

    user_agent = http_request.headers.get("user-agent", "")[:512]
    git_commit = _get_git_commit()

    report = BugReport(
        title=f"[user-report] {body.severity}",
        summary=body.observations[:500],   # legacy field; observations has the full text
        severity=body.severity,
        observations=body.observations,
        session_id=current.session_id,
        user_id=current.user_id,
        role=current.role,
        user_agent=user_agent,
        git_commit=git_commit,
        attachments_json="[]",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    report_id = report.id
    assert report_id is not None

    saved_attachments: list[dict] = []
    for att in body.attachments:
        try:
            meta = _save_attachment(att, str(report_id))
            saved_attachments.append(meta)
        except Exception as exc:
            write_log(
                level="WARN",
                module="bug_reports",
                event="attachment_save_failed",
                payload={"report_id": report_id, "error": str(exc)[:200]},
            )

    if saved_attachments:
        report.attachments_json = json.dumps(saved_attachments)
        db.add(report)
        db.commit()

    write_log(
        level="INFO",
        module="bug_reports",
        event="bug_report_submitted",
        payload={
            "report_id": report_id,
            "severity": body.severity,
            "role": current.role,
            "attachments": len(saved_attachments),
        },
    )
    return {"ok": True, "id": report_id}


@router.get("/bug-reports", response_model=BugReportListResponse)
def list_bug_reports(
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(require_admin),
):
    """Return summary list of all submitted reports. Admin only."""
    rows = db.exec(
        select(BugReport).order_by(col(BugReport.id).desc())
    ).all()

    items = [
        BugReportListItem(
            id=row.id,  # type: ignore[arg-type]
            created_at=row.created_at.replace(tzinfo=timezone.utc)
            if row.created_at.tzinfo is None else row.created_at,
            severity=row.severity,
            role=row.role,
            has_attachments=row.attachments_json != "[]",
        )
        for row in rows
    ]
    return BugReportListResponse(ok=True, total=len(items), reports=items)


@router.get("/bug-reports/{report_id}", response_model=BugReportDetailResponse)
def get_bug_report(
    report_id: int,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(require_admin),
):
    """Return full report detail. Admin only."""
    report = db.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    return _to_detail(report)


@router.get("/bug-reports/{report_id}/download")
def download_bug_report(
    report_id: int,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(require_admin),
):
    """Download full report as JSON. Admin only."""
    report = db.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    detail = _to_detail(report)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        **detail.model_dump(),
    }
    # datetime fields need to be serialized
    payload["created_at"] = detail.created_at.isoformat()
    payload["attachments"] = [a.model_dump() for a in detail.attachments]

    json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="bug-report-{report_id}.json"',
        },
    )


# ── Deletion ──────────────────────────────────────────────────────────────────

def _delete_report_attachments(report: BugReport) -> None:
    try:
        items = json.loads(report.attachments_json)
    except Exception:
        return
    for item in items:
        filename = item.get("filename", "")
        if filename:
            try:
                (_ATTACHMENTS_DIR / filename).unlink(missing_ok=True)
            except Exception:
                pass


class BugReportBulkDeleteRequest(BaseModel):
    ids: list[int]

    @field_validator("ids")
    @classmethod
    def _non_empty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("La lista de IDs no puede estar vacía.")
        return v


@router.delete("/bug-reports/{report_id}", status_code=200)
def delete_bug_report(
    report_id: int,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(require_admin),
):
    """Delete a single report and its disk attachments. Admin only."""
    report = db.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    _delete_report_attachments(report)
    db.delete(report)
    db.commit()
    write_log(
        level="INFO",
        module="bug_reports",
        event="bug_report_deleted",
        payload={"report_id": report_id, "by": current.role},
    )
    return {"ok": True, "deleted": 1}


@router.delete("/bug-reports", status_code=200)
def delete_bug_reports_bulk(
    body: BugReportBulkDeleteRequest,
    db: Session = Depends(get_session),
    current: CurrentUser = Depends(require_admin),
):
    """Delete multiple reports and their disk attachments. Admin only."""
    deleted = 0
    for rid in body.ids:
        report = db.get(BugReport, rid)
        if report is not None:
            _delete_report_attachments(report)
            db.delete(report)
            deleted += 1
    db.commit()
    write_log(
        level="INFO",
        module="bug_reports",
        event="bug_reports_bulk_deleted",
        payload={"ids": body.ids, "deleted": deleted, "by": current.role},
    )
    return {"ok": True, "deleted": deleted}

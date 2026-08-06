"""Shared conversation endpoints.

POST /chat/share          — authenticated (non-guest); creates a fixed snapshot.
GET  /shared/{share_id}   — public; validates expiry/revoked/max_views, returns snapshot.
DELETE /chat/share/{share_id} — authenticated; owner-only manual revocation.

Privacy guarantees:
  - snapshot_json stores only {role, text, created_at} — never session_id,
    speaker_id, identity_evidence_json, tone_meta, or dataset_source.
  - share_id is uuid4().hex (32-char hex), not sequential — not enumerable.
  - Messages added after sharing are never visible through the shared link.
  - Guests cannot create shared links (no stable identity).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.runtime_config import get_public_base_url
from app.memory.db import get_session
from app.memory.models import ChatMessage, SharedConversation, utc_now
from app.settings.config_loader import load_default_config
from app.trace.logger import write_log

router = APIRouter(tags=["share"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ShareCreateResponse(BaseModel):
    share_id: str
    url: str
    expires_at: str  # ISO 8601


class SharedMessageItem(BaseModel):
    role: str
    text: str
    created_at: str  # ISO 8601


class SharedConversationResponse(BaseModel):
    share_id: str
    messages: list[SharedMessageItem]
    created_at: str
    expires_at: str
    view_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_utc(dt) -> "datetime":
    from datetime import datetime
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_valid(sc: SharedConversation) -> bool:
    now = utc_now()
    if sc.revoked_at is not None:
        return False
    if now >= _ensure_utc(sc.expires_at):
        return False
    if sc.max_views is not None and sc.view_count >= sc.max_views:
        return False
    return True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/chat/share", response_model=ShareCreateResponse, status_code=201)
def create_share(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> ShareCreateResponse:
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Invitados no pueden compartir conversaciones.")

    messages = db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == current.session_id)
        .order_by(col(ChatMessage.created_at))
    ).all()

    snapshot = []
    for msg in messages:
        created = _ensure_utc(msg.created_at)
        snapshot.append({
            "role": msg.role,
            "text": msg.text,
            "created_at": created.isoformat(),
        })

    cfg = load_default_config()
    expiry_days = cfg.get("sharing", {}).get("default_expiry_days", 7)

    share_id = uuid4().hex
    now = utc_now()
    expires_at = now + timedelta(days=expiry_days)

    sc = SharedConversation(
        id=share_id,
        session_id=current.session_id,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        created_at=now,
        expires_at=expires_at,
    )
    db.add(sc)
    db.commit()

    base_url = get_public_base_url().rstrip("/")
    url = f"{base_url}/shared/{share_id}"

    write_log(
        level="INFO",
        module="share",
        event="share_created",
        session_id=current.session_id,
        payload={"share_id": share_id, "message_count": len(snapshot), "expiry_days": expiry_days},
    )

    return ShareCreateResponse(
        share_id=share_id,
        url=url,
        expires_at=expires_at.isoformat(),
    )


@router.get("/shared/{share_id}", response_model=SharedConversationResponse)
def get_shared(
    share_id: str,
    db: Session = Depends(get_session),
) -> SharedConversationResponse:
    sc = db.get(SharedConversation, share_id)
    if sc is None or not _is_valid(sc):
        raise HTTPException(status_code=410, detail="Este enlace ha caducado o no existe.")

    sc.view_count += 1
    db.add(sc)
    db.commit()

    snapshot: list[dict] = json.loads(sc.snapshot_json)

    return SharedConversationResponse(
        share_id=share_id,
        messages=[SharedMessageItem(**m) for m in snapshot],
        created_at=_ensure_utc(sc.created_at).isoformat(),
        expires_at=_ensure_utc(sc.expires_at).isoformat(),
        view_count=sc.view_count,
    )


@router.delete("/chat/share/{share_id}")
def revoke_share(
    share_id: str,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    if current.is_guest:
        raise HTTPException(status_code=401, detail="No autenticado.")

    sc = db.get(SharedConversation, share_id)
    if sc is None or sc.session_id != current.session_id:
        raise HTTPException(status_code=404, detail="Enlace no encontrado.")

    if sc.revoked_at is None:
        sc.revoked_at = utc_now()
        db.add(sc)
        db.commit()

    return {"ok": True, "share_id": share_id}

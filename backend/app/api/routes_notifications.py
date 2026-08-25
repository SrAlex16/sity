"""Web Push subscription endpoints (Paso 1 — infraestructura base).

GET    /notifications/vapid-public-key  — public; returns VAPID public key for the frontend
POST   /notifications/subscribe         — authenticated (non-guest); upserts PushSubscription
DELETE /notifications/subscribe         — authenticated (non-guest); marks subscription inactive
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.dependencies import CurrentUser, get_current_user
from app.memory.db import get_session
from app.memory.models import PushSubscription
from app.trace.logger import write_log

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class _PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: _PushKeys
    expirationTime: Optional[int] = None  # noqa: N815 — matches browser toJSON() field name


class UnsubscribeRequest(BaseModel):
    endpoint: str


# ---------------------------------------------------------------------------
# GET /notifications/vapid-public-key
# ---------------------------------------------------------------------------

@router.get("/vapid-public-key")
def get_vapid_public_key() -> dict:
    """Return the VAPID public key so the frontend can call PushManager.subscribe()."""
    key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Web Push no configurado en este servidor (falta VAPID_PUBLIC_KEY).",
        )
    return {"public_key": key}


# ---------------------------------------------------------------------------
# POST /notifications/subscribe
# ---------------------------------------------------------------------------

@router.post("/subscribe", status_code=201)
def subscribe(
    body: SubscribeRequest,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Register or refresh a Web Push subscription for this session+device."""
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")

    user_agent: Optional[str] = request.headers.get("user-agent")

    # Upsert: same endpoint → update (device may have refreshed its subscription).
    existing = db.exec(
        select(PushSubscription).where(
            PushSubscription.session_id == current.session_id,
            PushSubscription.endpoint == body.endpoint,
        )
    ).first()

    if existing:
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.user_agent = user_agent
        existing.is_active = True
        db.add(existing)
    else:
        sub = PushSubscription(
            session_id=current.session_id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=user_agent,
        )
        db.add(sub)

    db.commit()

    write_log(
        level="INFO",
        module="notifications",
        event="push_subscription_registered",
        payload={
            "session_id": current.session_id,
            "action": "updated" if existing else "created",
        },
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# DELETE /notifications/subscribe
# ---------------------------------------------------------------------------

@router.delete("/subscribe", status_code=204)
def unsubscribe(
    body: UnsubscribeRequest,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    """Mark a Web Push subscription inactive. Idempotent — 204 even if not found."""
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")

    rows = db.exec(
        select(PushSubscription).where(
            PushSubscription.session_id == current.session_id,
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.is_active == True,  # noqa: E712
        )
    ).all()

    for row in rows:
        row.is_active = False
        db.add(row)

    if rows:
        db.commit()
        write_log(
            level="INFO",
            module="notifications",
            event="push_subscription_deactivated",
            payload={"session_id": current.session_id, "count": len(rows)},
        )

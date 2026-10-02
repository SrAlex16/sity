"""Memory inspector endpoints — read and delete semantic facts, episodes, self-beliefs.

GET    /memory/semantic-facts           — user/admin; is_active=True, confidence DESC
GET    /memory/episodes                 — user/admin; salience_total DESC
GET    /memory/self-beliefs             — admin only; confidence DESC
DELETE /memory/semantic-facts/batch     — user/admin; own records only
DELETE /memory/semantic-facts/{id}      — user/admin; own records only
DELETE /memory/episodes/batch           — user/admin; own records only
DELETE /memory/episodes/{id}            — user/admin; own records only
DELETE /memory/self-beliefs/batch       — admin only
DELETE /memory/self-beliefs/{id}        — admin only
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.auth.dependencies import CurrentUser, get_current_user, require_admin
from app.memory.db import get_session
from app.memory.models import Episode, SemanticFact, SelfBelief

router = APIRouter(prefix="/memory", tags=["memory"])


def _require_authenticated(current: CurrentUser) -> None:
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")


class BatchDeleteBody(BaseModel):
    ids: list[int]


# ── SemanticFacts ─────────────────────────────────────────────────────────────


@router.get("/semantic-facts")
def list_semantic_facts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    _require_authenticated(current)
    uid = current.user_id
    total: int = db.exec(
        select(func.count()).select_from(SemanticFact).where(
            SemanticFact.user_id == uid,
            SemanticFact.is_active == True,  # noqa: E712
        )
    ).one()
    facts = db.exec(
        select(SemanticFact)
        .where(SemanticFact.user_id == uid, SemanticFact.is_active == True)  # noqa: E712
        .order_by(SemanticFact.confidence.desc())  # type: ignore[attr-defined]
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return {
        "items": [
            {
                "id": f.id,
                "proposition": f.proposition,
                "confidence": round(f.confidence, 3),
                "stability": f.stability,
                "inference_type": f.inference_type,
                "created_at": f.created_at.isoformat(),
            }
            for f in facts
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/semantic-facts/batch")
def batch_delete_semantic_facts(
    body: BatchDeleteBody,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    _require_authenticated(current)
    deleted = 0
    for fid in body.ids:
        row = db.get(SemanticFact, fid)
        if row and row.user_id == current.user_id:
            db.delete(row)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.delete("/semantic-facts/{fact_id}")
def delete_semantic_fact(
    fact_id: int,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    _require_authenticated(current)
    row = db.get(SemanticFact, fact_id)
    if not row or row.user_id != current.user_id:
        raise HTTPException(status_code=404, detail="No encontrado.")
    db.delete(row)
    db.commit()
    return {"deleted": True}


# ── Episodes ──────────────────────────────────────────────────────────────────


@router.get("/episodes")
def list_episodes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    _require_authenticated(current)
    uid = current.user_id
    total: int = db.exec(
        select(func.count()).select_from(Episode).where(Episode.user_id == uid)
    ).one()
    episodes = db.exec(
        select(Episode)
        .where(Episode.user_id == uid)
        .order_by(Episode.salience_total.desc())  # type: ignore[attr-defined]
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return {
        "items": [
            {
                "id": ep.id,
                "summary": ep.summary,
                "occurred_at": ep.occurred_at.isoformat(),
                "salience_total": round(ep.salience_total, 3),
            }
            for ep in episodes
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/episodes/batch")
def batch_delete_episodes(
    body: BatchDeleteBody,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    _require_authenticated(current)
    deleted = 0
    for eid in body.ids:
        row = db.get(Episode, eid)
        if row and row.user_id == current.user_id:
            db.delete(row)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.delete("/episodes/{episode_id}")
def delete_episode(
    episode_id: int,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict:
    _require_authenticated(current)
    row = db.get(Episode, episode_id)
    if not row or row.user_id != current.user_id:
        raise HTTPException(status_code=404, detail="No encontrado.")
    db.delete(row)
    db.commit()
    return {"deleted": True}


# ── SelfBeliefs (admin only) ──────────────────────────────────────────────────


@router.get("/self-beliefs")
def list_self_beliefs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _current: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_session),
) -> dict:
    total: int = db.exec(
        select(func.count()).select_from(SelfBelief).where(SelfBelief.is_active == True)  # noqa: E712
    ).one()
    beliefs = db.exec(
        select(SelfBelief)
        .where(SelfBelief.is_active == True)  # noqa: E712
        .order_by(SelfBelief.confidence.desc())  # type: ignore[attr-defined]
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    def _counts(b: SelfBelief) -> tuple[int, int]:
        trail = json.loads(b.evidence_trail_json) if b.evidence_trail_json else []
        rein = sum(1 for e in trail if e.get("relation") == "support")
        cont = sum(1 for e in trail if e.get("relation") == "contradict")
        return rein, cont

    return {
        "items": [
            {
                "id": b.id,
                "proposition": b.proposition,
                "confidence": round(b.confidence, 3),
                "source": b.source,
                "reinforcement_count": _counts(b)[0],
                "contradiction_count": _counts(b)[1],
                "created_at": b.created_at.isoformat(),
            }
            for b in beliefs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/self-beliefs/batch")
def batch_delete_self_beliefs(
    body: BatchDeleteBody,
    _current: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_session),
) -> dict:
    deleted = 0
    for bid in body.ids:
        row = db.get(SelfBelief, bid)
        if row:
            db.delete(row)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.delete("/self-beliefs/{belief_id}")
def delete_self_belief(
    belief_id: int,
    _current: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_session),
) -> dict:
    row = db.get(SelfBelief, belief_id)
    if not row:
        raise HTTPException(status_code=404, detail="No encontrado.")
    db.delete(row)
    db.commit()
    return {"deleted": True}

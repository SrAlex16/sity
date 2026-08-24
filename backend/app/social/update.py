"""social/update.py — background social profile update job (Fase 4, Paso 3).

Called from build_final_ai_response after each turn for user: sessions.
When pending_loads_json reaches the configured threshold, a daemon thread
runs _run_social_update which atomically:
  1. Claims the pending batch with BEGIN IMMEDIATE (write lock from start).
  2. Computes new opinion/trust.
  3. Clears pending_loads_json, updates the profile, inserts OpinionSnapshot.
  4. Commits — releasing the lock so any queued _append_pending_load calls proceed.

The BEGIN IMMEDIATE lock guarantees that any _append_pending_load arriving
while the update runs is queued (not lost): it will append to the cleared
'[]' after commit, entering the next batch.
"""
from __future__ import annotations

import json
import os
import statistics
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from app.memory.db import engine
from app.trace.logger import write_log

# Per-user locks: non-blocking acquire prevents double-processing.
_update_locks: dict[int, threading.Lock] = {}
_update_locks_meta = threading.Lock()

_DEFAULT_THRESHOLD = 10


def _get_threshold() -> int:
    try:
        from app.settings.config_loader import load_default_config
        cfg = load_default_config()
        return int(cfg.get("social", {}).get("update_threshold_turns", _DEFAULT_THRESHOLD))
    except Exception:
        return _DEFAULT_THRESHOLD


def _get_user_lock(user_id: int) -> threading.Lock:
    with _update_locks_meta:
        if user_id not in _update_locks:
            _update_locks[user_id] = threading.Lock()
        return _update_locks[user_id]


def _parse_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_batch_opinion(loads: list[int]) -> float:
    """Weighted average of turn loads, normalized to [-1, +1].

    weight(load) = 1 + |load|
    batch_opinion_raw = Σ(load_i × weight_i) / Σ(weight_i)   → [-2, +2]
    return batch_opinion_raw / 2                                → [-1, +1]
    """
    if not loads:
        return 0.0
    total_weight = sum(1 + abs(load) for load in loads)
    weighted_sum = sum(load * (1 + abs(load)) for load in loads)
    return (weighted_sum / total_weight) / 2.0


def compute_trust(
    *,
    created_at_str: str,
    snapshot_opinions: list[float],
    now: datetime,
) -> float:
    """Trust score in [0, 1].

    time_factor = min(1.0, days_known / 365)
    stability_factor = max(0.0, 1.0 - pstdev(all opinion snapshots))
    trust = time_factor × (0.5 + 0.5 × stability_factor)
    """
    created_at = _parse_utc(created_at_str)
    days_known = max(0, (now - created_at).days)
    time_factor = min(1.0, days_known / 365.0)

    if len(snapshot_opinions) <= 1:
        stability_factor = 1.0
    else:
        std_dev = statistics.pstdev(snapshot_opinions)
        stability_factor = max(0.0, 1.0 - std_dev)

    return time_factor * (0.5 + 0.5 * stability_factor)


_REFLECTION_MIN_NEW_MESSAGES = 20
_REFLECTION_MIN_OPINION_DELTA = 0.15
_REFLECTION_MAX_AGE_DAYS = 30
_REFLECTION_MAX_EVIDENCE_MESSAGES = 15

_REFLECTION_SYSTEM = (
    "Eres un observador que lee un extracto de conversación y escribe una reflexión breve "
    "sobre el patrón de interacción observado.\n\n"
    "REGLAS:\n"
    "- Escribe 2-4 frases en español.\n"
    "- Describe solo lo que observas: temas frecuentes, estilo comunicativo, tipo de preguntas, actitud general.\n"
    "- NO menciones valores numéricos de ningún tipo.\n"
    "- NO uses las palabras «opinión», «trust», «confianza» como concepto abstracto.\n"
    "- NO hagas predicciones ni recomendaciones.\n"
    "- NO superes 100 palabras."
)


def _get_reflection_config() -> dict:
    try:
        from app.settings.config_loader import load_default_config
        cfg = load_default_config().get("social", {})
        return {
            "reflection_min_new_messages": int(cfg.get("reflection_min_new_messages", _REFLECTION_MIN_NEW_MESSAGES)),
            "reflection_min_opinion_delta": float(cfg.get("reflection_min_opinion_delta", _REFLECTION_MIN_OPINION_DELTA)),
            "reflection_max_age_days": int(cfg.get("reflection_max_age_days", _REFLECTION_MAX_AGE_DAYS)),
            "reflection_max_evidence_messages": int(cfg.get("reflection_max_evidence_messages", _REFLECTION_MAX_EVIDENCE_MESSAGES)),
        }
    except Exception:
        return {
            "reflection_min_new_messages": _REFLECTION_MIN_NEW_MESSAGES,
            "reflection_min_opinion_delta": _REFLECTION_MIN_OPINION_DELTA,
            "reflection_max_age_days": _REFLECTION_MAX_AGE_DAYS,
            "reflection_max_evidence_messages": _REFLECTION_MAX_EVIDENCE_MESSAGES,
        }


def _get_latest_active_reflection(profile_id: int, db: Session) -> Optional[object]:
    from app.memory.models import SocialReflection, utc_now
    now = utc_now()
    return db.exec(
        select(SocialReflection)
        .where(SocialReflection.profile_id == profile_id)
        .where(SocialReflection.superseded_at == None)  # noqa: E711
        .where(SocialReflection.expires_at > now)
        .order_by(SocialReflection.created_at.desc())
        .limit(1)
    ).first()


def _has_sufficient_signal(
    *,
    user_id: int,
    latest_reflection: Optional[object],
    new_opinion: float,
    cfg: dict,
    db: Session,
) -> bool:
    session_id = f"user:{user_id}"
    min_new = cfg["reflection_min_new_messages"]
    min_delta = cfg["reflection_min_opinion_delta"]

    if latest_reflection is None:
        count = db.execute(
            sa_text("SELECT COUNT(*) FROM chatmessage WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar() or 0
        return count >= min_new

    count = db.execute(
        sa_text(
            "SELECT COUNT(*) FROM chatmessage"
            " WHERE session_id = :sid AND created_at > :since"
        ),
        {"sid": session_id, "since": latest_reflection.created_at.isoformat()},
    ).scalar() or 0

    opinion_delta = abs(new_opinion - latest_reflection.opinion_at_gen)
    return count >= min_new or opinion_delta >= min_delta


def _generate_reflection_content(messages: list[dict]) -> Optional[str]:
    """Call the LLM to produce a brief narrative reflection from recent messages.

    Returns the generated text, or None if the provider returned empty.
    Raises on provider/network error — caller handles via outer try/except.
    """
    if not messages:
        return None

    from app.cortex.providers.factory import build_ai_provider
    from app.cortex.schemas import AIRequest

    formatted = "\n".join(f"{m['role']}: {m['text'][:300]}" for m in messages)
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    provider = build_ai_provider(provider_name, model="claude-haiku-4-5-20251001")
    request = AIRequest(
        trace_id="social_reflection",
        task_type="social_reflection",
        system_prompt=_REFLECTION_SYSTEM,
        user_message=f"Mensajes recientes:\n{formatted}",
        max_tokens=150,
        tools_enabled=False,
    )
    response = provider.generate(request)
    if not response.ok or not response.text:
        return None
    return response.text.strip() or None


def _maybe_generate_reflection(
    *,
    user_id: int,
    profile_id: int,
    new_opinion: float,
    new_trust: float,
) -> None:
    """Steps 7-10: check signal → gather evidence → call LLM → persist.

    Opens its own Session (never touches the raw_conn write lock).
    Raises on unrecoverable error; _run_social_update catches and logs.
    """
    from app.memory.models import SocialReflection, utc_now

    cfg = _get_reflection_config()
    evidence_ids: list[int] = []
    latest_ref = None

    with Session(engine) as db:
        # Step 7: sufficient signal?
        latest_ref = _get_latest_active_reflection(profile_id, db)
        if not _has_sufficient_signal(
            user_id=user_id,
            latest_reflection=latest_ref,
            new_opinion=new_opinion,
            cfg=cfg,
            db=db,
        ):
            return

        # Step 8: gather evidence — most recent N messages, chronological
        session_id = f"user:{user_id}"
        rows = db.execute(
            sa_text(
                "SELECT id, role, text FROM chatmessage"
                " WHERE session_id = :sid"
                " ORDER BY created_at DESC LIMIT :n"
            ),
            {"sid": session_id, "n": cfg["reflection_max_evidence_messages"]},
        ).fetchall()
        rows = list(reversed(rows))
        evidence_ids = [r[0] for r in rows]
        messages_for_llm = [{"role": r[1], "text": r[2]} for r in rows]

        # Step 9: generate content (may raise — propagates to caller)
        content = _generate_reflection_content(messages_for_llm)
        if not content:
            return

        # Step 10: supersede active reflection, insert new
        now = utc_now()
        if latest_ref is not None:
            latest_ref.superseded_at = now
            db.add(latest_ref)

        db.add(SocialReflection(
            profile_id=profile_id,
            category="general",
            content=content,
            evidence_json=json.dumps(evidence_ids),
            opinion_at_gen=new_opinion,
            trust_at_gen=new_trust,
            expires_at=now + timedelta(days=cfg["reflection_max_age_days"]),
        ))
        db.commit()

    write_log(
        level="INFO",
        module="social",
        event="social_reflection_created",
        payload={
            "user_id": user_id,
            "profile_id": profile_id,
            "evidence_count": len(evidence_ids),
            "superseded_previous": latest_ref is not None,
        },
    )


def _run_social_update(
    user_id: int,
    trace_id: str,
    *,
    _test_hook_after_read: Callable[[], None] | None = None,
    _test_hook_before_commit: Callable[[], None] | None = None,
) -> None:
    """Process pending loads for a user: compute new opinion/trust, update profile.

    Uses raw DBAPI connection with BEGIN IMMEDIATE so any concurrent
    _append_pending_load is serialised after our commit, not lost.

    Private _test_hook_* parameters are used only in tests for deterministic
    concurrency simulation and atomicity verification.
    """
    lock = _get_user_lock(user_id)
    if not lock.acquire(blocking=False):
        write_log(
            level="INFO",
            module="social",
            event="social_update_skipped_locked",
            payload={"user_id": user_id},
        )
        return

    raw_conn = engine.raw_connection()
    committed = False
    try:
        raw_conn.execute("BEGIN IMMEDIATE")

        row = raw_conn.execute(
            "SELECT id, opinion, trust, pending_loads_json, created_at"
            " FROM socialprofile WHERE user_id = :uid",
            {"uid": user_id},
        ).fetchone()

        if row is None:
            raw_conn.rollback()
            return

        profile_id, old_opinion, old_trust, loads_json, created_at_str = row
        loads: list[int] = json.loads(loads_json or "[]")
        if not loads:
            raw_conn.rollback()
            return

        # Hook runs AFTER read, while write lock is held.
        # In tests: fires a concurrent _append_pending_load which blocks here.
        if _test_hook_after_read is not None:
            _test_hook_after_read()

        batch_opinion_norm = compute_batch_opinion(loads)
        new_opinion = max(-1.0, min(1.0, 0.3 * batch_opinion_norm + 0.7 * old_opinion))

        snap_rows = raw_conn.execute(
            "SELECT opinion_value FROM opinionsnapshot WHERE profile_id = :pid",
            {"pid": profile_id},
        ).fetchall()
        all_opinions = [r[0] for r in snap_rows] + [new_opinion]

        now = datetime.now(timezone.utc)
        new_trust = compute_trust(
            created_at_str=created_at_str,
            snapshot_opinions=all_opinions,
            now=now,
        )
        now_str = now.isoformat()

        raw_conn.execute(
            "UPDATE socialprofile"
            " SET opinion = :op, trust = :tr, pending_loads_json = '[]', last_updated_at = :now"
            " WHERE user_id = :uid",
            {"op": new_opinion, "tr": new_trust, "now": now_str, "uid": user_id},
        )
        raw_conn.execute(
            "INSERT INTO opinionsnapshot (profile_id, opinion_value, trust_value, computed_at)"
            " VALUES (:pid, :op, :tr, :now)",
            {"pid": profile_id, "op": new_opinion, "tr": new_trust, "now": now_str},
        )

        # Hook before commit: raises in atomicity tests to simulate a mid-job crash.
        if _test_hook_before_commit is not None:
            _test_hook_before_commit()

        raw_conn.commit()  # releases write lock; queued writers proceed
        committed = True

        write_log(
            level="INFO",
            module="social",
            event="social_profile_updated",
            payload={
                "user_id": user_id,
                "batch_size": len(loads),
                "old_opinion": old_opinion,
                "new_opinion": new_opinion,
                "old_trust": old_trust,
                "new_trust": new_trust,
            },
        )

        # Steps 7-10: narrative reflection (own Session, own try/except — never
        # blocks the write lock; BEGIN IMMEDIATE was released at commit above).
        try:
            _maybe_generate_reflection(
                user_id=user_id,
                profile_id=profile_id,
                new_opinion=new_opinion,
                new_trust=new_trust,
            )
        except Exception as refl_exc:
            write_log(
                level="WARN",
                module="social",
                event="social_reflection_generation_failed",
                payload={"user_id": user_id, "error": str(refl_exc)[:200]},
            )

    except Exception as exc:
        if not committed:
            try:
                raw_conn.rollback()
            except Exception:
                pass
        write_log(
            level="WARN",
            module="social",
            event="social_update_failed",
            payload={
                "user_id": user_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
    finally:
        raw_conn.close()
        lock.release()


def maybe_trigger_social_update(session: Session, session_id: str, trace_id: str) -> None:
    """Fire a background social update if pending_loads reached threshold.

    Called from build_final_ai_response after save_message commits.
    The pending-count check is a single SELECT; the update runs in a daemon thread.
    """
    try:
        user_id = int(session_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return

    from sqlalchemy import text

    row = session.execute(
        text(
            "SELECT json_array_length(COALESCE(pending_loads_json, '[]'))"
            " FROM socialprofile WHERE user_id = :uid"
        ),
        {"uid": user_id},
    ).fetchone()

    if row is None:
        return

    pending_count: int = row[0] or 0
    threshold = _get_threshold()
    if pending_count < threshold:
        return

    write_log(
        level="INFO",
        module="social",
        event="social_update_triggered",
        payload={"user_id": user_id, "pending_count": pending_count, "threshold": threshold},
    )
    threading.Thread(
        target=_run_social_update,
        args=(user_id, trace_id),
        daemon=True,
    ).start()

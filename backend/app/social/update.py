"""social/update.py — background social snapshot + reflection + narrative job (Remake Fase 3-4).

Called from build_final_ai_response after each turn for user: sessions.
When pending_loads_json reaches the configured threshold, a daemon thread runs
_run_social_update which atomically:
  1. Claims the pending batch with BEGIN IMMEDIATE (write lock from start).
  2. Reads current SocialProfile dimensions (already updated per-turn by Appraisal).
  3. Inserts a RelationshipSnapshot (affinity, conflict, trust_avg).
  4. Clears pending_loads_json and updates last_updated_at.
  5. Commits — releasing the lock so any queued _append_pending_load calls proceed.
  6. (After commit) Possibly generates a SocialReflection via Haiku.
  7. (After commit) Possibly generates an AutobiographicalNarrative via Haiku.

Per-turn relationship dimension updates are handled in turn_cognition.py
(apply_appraisal_to_social_profile). This job only does periodic snapshotting
and narrative generation.

Reflection trigger condition (conservative AND/OR — approved Fase 3 Paso 1):
  No prior reflection:  message_count >= 20
  Prior reflection:     (message_count >= 20 AND Δcombined >= 0.08)
                        OR Δcombined >= 0.20 (override for large changes)

  Δcombined = 0.35*|Δaffinity| + 0.30*|Δconflict| + 0.25*|Δtrust_avg| + 0.10*|Δattachment|

AutobiographicalNarrative trigger condition (Fase 4 Paso 3):
  No prior narrative:   muy_alta_episode_count >= narrative_min_muy_alta_episodes
  Prior narrative:      age_days >= narrative_min_days_since_last
                        AND new_muy_alta_since_last >= narrative_min_muy_alta_episodes
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from app.memory.models import AutobiographicalNarrative, SocialReflection

from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from app.memory.db import engine
from app.trace.logger import write_log

_update_locks: dict[int, threading.Lock] = {}
_update_locks_meta = threading.Lock()

_DEFAULT_THRESHOLD = 10

# Reflection trigger thresholds
_REFLECTION_MIN_NEW_MESSAGES = 20
_REFLECTION_MIN_COMBINED_DELTA = 0.08   # required alongside message count
_REFLECTION_LARGE_COMBINED_DELTA = 0.20  # override: triggers even with fewer messages
_REFLECTION_MAX_AGE_DAYS = 30
_REFLECTION_MAX_EVIDENCE_MESSAGES = 15

# AutobiographicalNarrative trigger thresholds
_NARRATIVE_MIN_EPISODES = 3    # min muy_alta episodes required (new since last narrative)
_NARRATIVE_MIN_DAYS = 7        # min days since last narrative before regenerating
_NARRATIVE_MAX_EPISODES = 10   # max episode summaries passed to Haiku as evidence
_SALIENCE_MUY_ALTA = 0.70      # salience_total threshold that defines "muy_alta"


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


def _get_reflection_config() -> dict:
    try:
        from app.settings.config_loader import load_default_config
        cfg = load_default_config().get("social", {})
        return {
            "reflection_min_new_messages":    int(cfg.get("reflection_min_new_messages",    _REFLECTION_MIN_NEW_MESSAGES)),
            "reflection_min_combined_delta":  float(cfg.get("reflection_min_combined_delta",  _REFLECTION_MIN_COMBINED_DELTA)),
            "reflection_large_combined_delta":float(cfg.get("reflection_large_combined_delta",_REFLECTION_LARGE_COMBINED_DELTA)),
            "reflection_max_age_days":        int(cfg.get("reflection_max_age_days",        _REFLECTION_MAX_AGE_DAYS)),
            "reflection_max_evidence_messages":int(cfg.get("reflection_max_evidence_messages",_REFLECTION_MAX_EVIDENCE_MESSAGES)),
        }
    except Exception:
        return {
            "reflection_min_new_messages":    _REFLECTION_MIN_NEW_MESSAGES,
            "reflection_min_combined_delta":  _REFLECTION_MIN_COMBINED_DELTA,
            "reflection_large_combined_delta": _REFLECTION_LARGE_COMBINED_DELTA,
            "reflection_max_age_days":        _REFLECTION_MAX_AGE_DAYS,
            "reflection_max_evidence_messages":_REFLECTION_MAX_EVIDENCE_MESSAGES,
        }


def _combined_delta(
    affinity: float,    conflict: float,    trust_avg: float,    attachment: float,
    aff_ref: float,     con_ref: float,     ta_ref: float,       att_ref: float,
) -> float:
    """Weighted combined change magnitude across the 4 most relationship-relevant dimensions."""
    return (
        0.35 * abs(affinity   - aff_ref)
        + 0.30 * abs(conflict   - con_ref)
        + 0.25 * abs(trust_avg  - ta_ref)
        + 0.10 * abs(attachment - att_ref)
    )


def _get_latest_active_reflection(profile_id: int, db: Session) -> Optional[SocialReflection]:
    from app.memory.models import SocialReflection, utc_now
    from sqlmodel import col
    now = utc_now()
    return db.exec(
        select(SocialReflection)
        .where(SocialReflection.profile_id == profile_id)
        .where(SocialReflection.superseded_at == None)  # noqa: E711
        .where(SocialReflection.expires_at > now)
        .order_by(col(SocialReflection.created_at).desc())
        .limit(1)
    ).first()


def _has_sufficient_signal(
    *,
    user_id: int,
    latest_reflection: Optional[SocialReflection],
    affinity: float,
    conflict: float,
    trust_avg: float,
    attachment: float,
    cfg: dict,
    db: Session,
) -> bool:
    """Conservative AND/OR trigger condition for SocialReflection generation.

    No prior reflection: message count alone decides.
    Prior reflection:    (count >= min AND Δ >= min_delta) OR Δ >= large_delta.
    """
    session_id = f"user:{user_id}"
    min_new   = cfg["reflection_min_new_messages"]
    min_delta = cfg["reflection_min_combined_delta"]
    big_delta = cfg["reflection_large_combined_delta"]

    if latest_reflection is None:
        count = db.execute(
            sa_text("SELECT COUNT(*) FROM chatmessage WHERE session_id = :sid"),
            {"sid": session_id},
        ).scalar() or 0
        return int(count) >= min_new

    count = db.execute(
        sa_text(
            "SELECT COUNT(*) FROM chatmessage"
            " WHERE session_id = :sid AND created_at > :since"
        ),
        {"sid": session_id, "since": latest_reflection.created_at.isoformat()},
    ).scalar() or 0

    delta = _combined_delta(
        affinity, conflict, trust_avg, attachment,
        latest_reflection.affinity_at_gen,
        latest_reflection.conflict_at_gen,
        latest_reflection.trust_avg_at_gen,
        latest_reflection.attachment_at_gen,
    )
    return (int(count) >= min_new and delta >= min_delta) or delta >= big_delta


def _generate_reflection_content(messages: list[dict]) -> Optional[str]:
    if not messages:
        return None

    from app.cortex.providers.factory import build_ai_provider

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

    formatted = "\n".join(f"{m['role']}: {m['text'][:300]}" for m in messages)
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    provider = build_ai_provider(provider_name, model="claude-haiku-4-5-20251001")
    from app.cortex.schemas import AIRequest as _AIRequest
    request = _AIRequest(
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


def _get_narrative_config() -> dict:
    try:
        from app.settings.config_loader import load_default_config
        cfg = load_default_config().get("social", {})
        return {
            "narrative_min_muy_alta_episodes": int(cfg.get("narrative_min_muy_alta_episodes", _NARRATIVE_MIN_EPISODES)),
            "narrative_min_days_since_last":   int(cfg.get("narrative_min_days_since_last",   _NARRATIVE_MIN_DAYS)),
            "narrative_max_episodes":          int(cfg.get("narrative_max_episodes",          _NARRATIVE_MAX_EPISODES)),
        }
    except Exception:
        return {
            "narrative_min_muy_alta_episodes": _NARRATIVE_MIN_EPISODES,
            "narrative_min_days_since_last":   _NARRATIVE_MIN_DAYS,
            "narrative_max_episodes":          _NARRATIVE_MAX_EPISODES,
        }


def _get_current_quarter(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def _get_latest_active_narrative(user_id: int, db: Session) -> Optional["AutobiographicalNarrative"]:
    from app.memory.models import AutobiographicalNarrative
    from sqlmodel import col
    return db.exec(
        select(AutobiographicalNarrative)
        .where(AutobiographicalNarrative.user_id == user_id)
        .where(AutobiographicalNarrative.superseded_at == None)  # noqa: E711
        .order_by(col(AutobiographicalNarrative.created_at).desc())
        .limit(1)
    ).first()


def _has_narrative_signal(
    user_id: int,
    latest_narrative: Optional["AutobiographicalNarrative"],
    cfg: dict,
    db: Session,
) -> bool:
    """True when enough muy_alta episodes exist and the age gate has passed."""
    min_episodes = cfg["narrative_min_muy_alta_episodes"]
    min_days = cfg["narrative_min_days_since_last"]

    now = datetime.now(timezone.utc)

    if latest_narrative is not None:
        created = latest_narrative.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        if age_days < min_days:
            return False
        count = db.execute(
            sa_text(
                "SELECT COUNT(*) FROM episode"
                " WHERE user_id = :uid AND salience_total >= :thr"
                " AND occurred_at > :since"
            ),
            {
                "uid": user_id,
                "thr": _SALIENCE_MUY_ALTA,
                "since": latest_narrative.created_at.isoformat(),
            },
        ).scalar() or 0
    else:
        count = db.execute(
            sa_text(
                "SELECT COUNT(*) FROM episode"
                " WHERE user_id = :uid AND salience_total >= :thr"
            ),
            {"uid": user_id, "thr": _SALIENCE_MUY_ALTA},
        ).scalar() or 0

    return int(count) >= min_episodes


def _generate_narrative_content(episodes: list[dict]) -> Optional[str]:
    """Call Haiku to synthesize an autobiographical narrative from episode summaries."""
    if not episodes:
        return None

    _NARRATIVE_SYSTEM = (
        "Eres un observador que lee un conjunto de momentos conversacionales significativos "
        "y sintetiza una narrativa autobiográfica breve.\n\n"
        "REGLAS:\n"
        "- Escribe 3-5 frases en español.\n"
        "- Describe patrones observados: qué temas preocupan al interlocutor, sus motivaciones, "
        "su estado emocional recurrente, lo que parece importarle.\n"
        "- Usa un tono reflexivo y neutro — como si Sity describiera su impresión acumulada.\n"
        "- NO menciones fechas, valores numéricos, ni información literal de las conversaciones.\n"
        "- NO hagas predicciones ni recomendaciones.\n"
        "- NO superes 150 palabras."
    )

    from app.cortex.providers.factory import build_ai_provider
    from app.cortex.schemas import AIRequest as _AIRequest

    formatted = "\n".join(f"- {ep['summary']}" for ep in episodes)
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    provider = build_ai_provider(provider_name, model="claude-haiku-4-5-20251001")
    request = _AIRequest(
        trace_id="autobiographical_narrative",
        task_type="autobiographical_narrative",
        system_prompt=_NARRATIVE_SYSTEM,
        user_message=f"Momentos significativos:\n{formatted}",
        max_tokens=200,
        tools_enabled=False,
    )
    response = provider.generate(request)
    if not response.ok or not response.text:
        return None
    return response.text.strip() or None


def _maybe_generate_narrative(*, user_id: int) -> None:
    """Check signal → gather muy_alta episodes → call Haiku → persist AutobiographicalNarrative.

    Opens its own Session (never touches the raw_conn write lock).
    Raises on unrecoverable error; _run_social_update catches and logs.
    """
    from app.memory.models import AutobiographicalNarrative, utc_now

    cfg = _get_narrative_config()
    episode_ids: list[int] = []
    latest_narrative = None

    with Session(engine) as db:
        latest_narrative = _get_latest_active_narrative(user_id, db)
        if not _has_narrative_signal(user_id, latest_narrative, cfg, db):
            return

        if latest_narrative is not None:
            rows = db.execute(
                sa_text(
                    "SELECT id, summary FROM episode"
                    " WHERE user_id = :uid AND salience_total >= :thr"
                    " AND occurred_at > :since"
                    " ORDER BY occurred_at DESC LIMIT :n"
                ),
                {
                    "uid": user_id,
                    "thr": _SALIENCE_MUY_ALTA,
                    "since": latest_narrative.created_at.isoformat(),
                    "n": cfg["narrative_max_episodes"],
                },
            ).fetchall()
        else:
            rows = db.execute(
                sa_text(
                    "SELECT id, summary FROM episode"
                    " WHERE user_id = :uid AND salience_total >= :thr"
                    " ORDER BY occurred_at DESC LIMIT :n"
                ),
                {"uid": user_id, "thr": _SALIENCE_MUY_ALTA, "n": cfg["narrative_max_episodes"]},
            ).fetchall()

        episode_ids = [r[0] for r in rows]
        episodes_for_llm = [{"summary": r[1]} for r in rows]

        content = _generate_narrative_content(episodes_for_llm)
        if not content:
            return

        now = utc_now()
        if latest_narrative is not None:
            latest_narrative.superseded_at = now
            db.add(latest_narrative)

        db.add(AutobiographicalNarrative(
            user_id=user_id,
            period=_get_current_quarter(now),
            narrative=content,
            identity_effects_json="[]",
            important_episode_ids_json=json.dumps(episode_ids),
            created_at=now,
        ))
        db.commit()

    write_log(
        level="INFO",
        module="social",
        event="autobiographical_narrative_created",
        payload={
            "user_id": user_id,
            "episode_count": len(episode_ids),
            "superseded_previous": latest_narrative is not None,
        },
    )


def _maybe_generate_reflection(
    *,
    user_id: int,
    profile_id: int,
    affinity: float,
    conflict: float,
    trust_avg: float,
    attachment: float,
) -> None:
    """Check signal → gather evidence → call Haiku → persist SocialReflection.

    Opens its own Session (never touches the raw_conn write lock).
    Raises on unrecoverable error; _run_social_update catches and logs.
    """
    from app.memory.models import SocialReflection, utc_now

    cfg = _get_reflection_config()
    evidence_ids: list[int] = []
    latest_ref = None

    with Session(engine) as db:
        latest_ref = _get_latest_active_reflection(profile_id, db)
        if not _has_sufficient_signal(
            user_id=user_id,
            latest_reflection=latest_ref,
            affinity=affinity,
            conflict=conflict,
            trust_avg=trust_avg,
            attachment=attachment,
            cfg=cfg,
            db=db,
        ):
            return

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

        content = _generate_reflection_content(messages_for_llm)
        if not content:
            return

        now = utc_now()
        if latest_ref is not None:
            latest_ref.superseded_at = now
            db.add(latest_ref)

        db.add(SocialReflection(
            profile_id=profile_id,
            category="general",
            content=content,
            evidence_json=json.dumps(evidence_ids),
            affinity_at_gen=affinity,
            conflict_at_gen=conflict,
            trust_avg_at_gen=trust_avg,
            attachment_at_gen=attachment,
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
    """Process pending loads for a user: insert RelationshipSnapshot, clear batch.

    Uses raw DBAPI connection with BEGIN IMMEDIATE so any concurrent
    _append_pending_load is serialised after our commit, not lost.
    Per-turn dimension updates already happened in turn_cognition.py via
    apply_appraisal_to_social_profile. This job only does periodic snapshotting
    and reflection generation.
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
            "SELECT id, familiarity, trust_honesty, trust_intentions,"
            " trust_competence, trust_reliability, affinity, conflict, attachment,"
            " pending_loads_json"
            " FROM socialprofile WHERE user_id = :uid",
            {"uid": user_id},
        ).fetchone()

        if row is None:
            raw_conn.rollback()
            return

        (profile_id, familiarity, trust_honesty, trust_intentions,
         trust_competence, trust_reliability, affinity, conflict, attachment,
         loads_json) = row

        loads: list[int] = json.loads(loads_json or "[]")
        if not loads:
            raw_conn.rollback()
            return

        if _test_hook_after_read is not None:
            _test_hook_after_read()

        trust_avg = (trust_honesty + trust_intentions + trust_competence + trust_reliability) / 4.0
        now_str = datetime.now(timezone.utc).isoformat()

        raw_conn.execute(
            "UPDATE socialprofile"
            " SET pending_loads_json = '[]', last_updated_at = :now"
            " WHERE user_id = :uid",
            {"now": now_str, "uid": user_id},
        )
        raw_conn.execute(
            "INSERT INTO relationshipsnapshot (profile_id, affinity, conflict, trust_avg, computed_at)"
            " VALUES (:pid, :af, :co, :ta, :now)",
            {"pid": profile_id, "af": affinity, "co": conflict, "ta": trust_avg, "now": now_str},
        )

        if _test_hook_before_commit is not None:
            _test_hook_before_commit()

        raw_conn.commit()
        committed = True

        write_log(
            level="INFO",
            module="social",
            event="social_snapshot_taken",
            payload={
                "user_id": user_id,
                "batch_size": len(loads),
                "affinity": round(affinity, 3),
                "conflict": round(conflict, 3),
                "trust_avg": round(trust_avg, 3),
            },
        )

        try:
            _maybe_generate_reflection(
                user_id=user_id,
                profile_id=profile_id,
                affinity=affinity,
                conflict=conflict,
                trust_avg=trust_avg,
                attachment=attachment,
            )
        except Exception as refl_exc:
            write_log(
                level="WARN",
                module="social",
                event="social_reflection_generation_failed",
                payload={"user_id": user_id, "error": str(refl_exc)[:200]},
            )

        try:
            _maybe_generate_narrative(user_id=user_id)
        except Exception as narr_exc:
            write_log(
                level="WARN",
                module="social",
                event="autobiographical_narrative_generation_failed",
                payload={"user_id": user_id, "error": str(narr_exc)[:200]},
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

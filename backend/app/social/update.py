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
import statistics
import threading
from datetime import datetime, timezone
from typing import Callable

from sqlmodel import Session

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

"""time_context.py — snapshot temporal para el turno de chat.

Pure module: no DB access, no side-effects, no opinion.
All functions are deterministic given the same inputs.

Usage in prompt assembly:
    from app.chat.time_context import build_time_context, render_time_context

    snapshot = build_time_context(raw_db_messages, now=datetime.now(UTC))
    time_block = render_time_context(snapshot)
    # → prepend to user_message_with_history
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimeContextSnapshot:
    """Immutable temporal snapshot for a single chat turn."""

    now_utc: datetime
    """Current moment in UTC (always tz-aware)."""

    now_local: datetime
    """Current moment in server local time (always tz-aware)."""

    secs_since_last_user: int | None
    """Seconds elapsed since the last message with role=='user'.
    None if no user message exists yet in this session."""

    secs_since_last_sity: int | None
    """Seconds elapsed since the last message with role=='sity'.
    None if no sity message exists yet in this session."""


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def _as_utc(dt: datetime) -> datetime:
    """Normalise a datetime to UTC.

    SQLite/SQLAlchemy returns naive datetimes even when the value was stored
    as UTC. We treat every naive datetime from the DB as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_time_context(
    db_messages: list[Any],
    *,
    now: datetime | None = None,
) -> TimeContextSnapshot:
    """Compute a TimeContextSnapshot from a list of DB message objects.

    Args:
        db_messages: Objects that expose ``.role`` (str) and ``.created_at``
            (datetime).  Only 'user' and 'sity' roles are considered.
            The list is iterated in order; the *last* entry for each role wins,
            so pass messages ordered oldest-first (as get_recent_db_messages
            already returns them).
        now:  Reference moment.  Defaults to ``datetime.now(timezone.utc)``.
            Override in tests for deterministic results.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_utc = _as_utc(now)
    now_local = now_utc.astimezone()   # server local timezone

    last_user_utc: datetime | None = None
    last_sity_utc: datetime | None = None

    for msg in db_messages:
        role = getattr(msg, "role", None)
        ts = getattr(msg, "created_at", None)
        if ts is None:
            continue
        if role == "user":
            last_user_utc = _as_utc(ts)
        elif role == "sity":
            last_sity_utc = _as_utc(ts)

    return TimeContextSnapshot(
        now_utc=now_utc,
        now_local=now_local,
        secs_since_last_user=(
            int((now_utc - last_user_utc).total_seconds())
            if last_user_utc is not None
            else None
        ),
        secs_since_last_sity=(
            int((now_utc - last_sity_utc).total_seconds())
            if last_sity_utc is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _format_delta(secs: int) -> str:
    """Format elapsed seconds as a compact, factual string (no opinion)."""
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60} min"
    h, remainder = divmod(secs, 3600)
    m = remainder // 60
    return f"{h}h {m}min" if m else f"{h}h"


def _utc_offset_label(local_dt: datetime) -> str:
    """Return a compact UTC offset string, e.g. 'UTC+2' or 'UTC+5:30'."""
    offset = local_dt.utcoffset()
    if offset is None:
        return "hora local"
    total_mins = int(offset.total_seconds()) // 60
    sign = "+" if total_mins >= 0 else "-"
    h, m = divmod(abs(total_mins), 60)
    return f"UTC{sign}{h}" if m == 0 else f"UTC{sign}{h}:{m:02d}"


def render_time_context(snapshot: TimeContextSnapshot) -> str:
    """Render a compact, factual time-context block for prompt injection.

    Format (stable — tests depend on this):

        [Contexto temporal: HH:MM UTC / HH:MM UTC+N]
        Último mensaje del usuario: hace Xs / N min / Nh Mmin.
        Última respuesta de Sity: hace Xs / N min / Nh Mmin.

    Or, when no prior messages:

        [Contexto temporal: HH:MM UTC / HH:MM UTC+N]
        Sin mensajes previos en esta sesión.
    """
    utc_str   = snapshot.now_utc.strftime("%H:%M UTC")
    local_str = snapshot.now_local.strftime("%H:%M")
    offset    = _utc_offset_label(snapshot.now_local)

    header = f"[Contexto temporal: {utc_str} / {local_str} {offset}]"

    no_user = snapshot.secs_since_last_user is None
    no_sity = snapshot.secs_since_last_sity is None

    if no_user and no_sity:
        return f"{header}\nSin mensajes previos en esta sesión."

    lines = [header]
    if not no_user:
        lines.append(
            f"Último mensaje del usuario: hace {_format_delta(snapshot.secs_since_last_user)}."
        )
    if not no_sity:
        lines.append(
            f"Última respuesta de Sity: hace {_format_delta(snapshot.secs_since_last_sity)}."
        )
    return "\n".join(lines)

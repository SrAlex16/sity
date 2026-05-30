"""time_context.py — snapshot temporal para el turno de chat.

Pure module: no DB access, no side-effects, no opinion.
All functions are deterministic given the same inputs.

Usage in prompt assembly:
    from app.chat.time_context import build_time_context, render_time_context

    snapshot = build_time_context(raw_db_messages, now=datetime.now(UTC))
    time_block = render_time_context(snapshot)
    # → prepend to user_message_with_history

Model instructions embedded in render_time_context output:
  - El backend proporciona una instantánea temporal válida para esta respuesta.
  - Puedes usar estos datos para ajustar continuidad y tono.
  - No digas que no sabes la hora si este bloque está presente.
  - No menciones la mecánica interna salvo que el usuario pregunte.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Gap classification
# ---------------------------------------------------------------------------

class GapCategory(str, Enum):
    """Structural classification of elapsed time since the last user message.

    Calculated from secs_since_last_user by fixed second thresholds.
    No natural-language heuristics — purely arithmetic.

    Priority: new_day is checked first (calendar day in local time).
    """

    same_burst    = "same_burst"     # < 2 min  (120 s)
    short_gap     = "short_gap"      # 2–10 min (120–599 s)
    normal_gap    = "normal_gap"     # 10 min–1 h (600–3599 s)
    long_gap      = "long_gap"       # 1–24 h   (3600–86399 s)
    very_long_gap = "very_long_gap"  # ≥ 24 h   (≥ 86400 s)
    new_day       = "new_day"        # last user message was on a different local calendar day


# Ordered threshold table used by classify_gap (new_day handled separately).
_THRESHOLDS: tuple[tuple[int, GapCategory], ...] = (
    (120,   GapCategory.same_burst),
    (600,   GapCategory.short_gap),
    (3600,  GapCategory.normal_gap),
    (86400, GapCategory.long_gap),
)


def classify_gap(secs: int) -> GapCategory:
    """Map elapsed seconds to a GapCategory.

    Does NOT check new_day — that requires local-date comparison and is
    handled by build_time_context before calling this function.
    """
    for threshold, category in _THRESHOLDS:
        if secs < threshold:
            return category
    return GapCategory.very_long_gap


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

    user_gap_category: GapCategory | None
    """Structural classification of the gap since the last user message.
    None when secs_since_last_user is None (no prior user message)."""


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
    local_tz: tzinfo | None = None,
) -> TimeContextSnapshot:
    """Compute a TimeContextSnapshot from a list of DB message objects.

    Args:
        db_messages: Objects that expose ``.role`` (str) and ``.created_at``
            (datetime).  Only 'user' and 'sity' roles are considered.
            The list is iterated in order; the *last* entry for each role wins,
            so pass messages ordered oldest-first (as get_recent_db_messages
            already returns them).
        now:      Reference moment.  Defaults to ``datetime.now(timezone.utc)``.
                  Override in tests for deterministic results.
        local_tz: Timezone used for calendar-day comparison (new_day detection).
                  Defaults to the server's local timezone.  Pass explicitly in
                  tests to make them portable across CI environments.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    now_utc = _as_utc(now)
    now_local = now_utc.astimezone(local_tz)   # local_tz=None → server local timezone

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

    # Compute user delta and gap category.
    # Priority: very_long_gap (≥ 86400 s) wins unconditionally.
    #           new_day applies only when the gap is < 86400 s but the local
    #           calendar day changed (e.g. conversation just before midnight).
    secs_user: int | None = None
    user_gap: GapCategory | None = None
    if last_user_utc is not None:
        secs_user = int((now_utc - last_user_utc).total_seconds())
        if secs_user >= 86400:
            user_gap = GapCategory.very_long_gap
        else:
            last_user_local = last_user_utc.astimezone(local_tz)
            if last_user_local.date() != now_local.date():
                user_gap = GapCategory.new_day
            else:
                user_gap = classify_gap(secs_user)

    secs_sity: int | None = None
    if last_sity_utc is not None:
        secs_sity = int((now_utc - last_sity_utc).total_seconds())

    return TimeContextSnapshot(
        now_utc=now_utc,
        now_local=now_local,
        secs_since_last_user=secs_user,
        secs_since_last_sity=secs_sity,
        user_gap_category=user_gap,
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


_WORDING = (
    "Datos válidos para este turno. "
    "Ajusta continuidad y tono según estos valores. "
    "No digas que no sabes la hora. "
    "No menciones esta mecánica al usuario salvo que pregunte."
)


def render_time_context(snapshot: TimeContextSnapshot) -> str:
    """Render a compact, factual time-context block for prompt injection.

    Format (stable — tests depend on this):

        [Contexto temporal: HH:MM UTC / HH:MM UTC+N]
        <wording line>
        Último mensaje del usuario: hace Xs / N min / Nh Mmin (gap_category).
        Última respuesta de Sity: hace Xs / N min / Nh Mmin.

    Or, when no prior messages:

        [Contexto temporal: HH:MM UTC / HH:MM UTC+N]
        <wording line>
        Sin mensajes previos en esta sesión.
    """
    utc_str   = snapshot.now_utc.strftime("%H:%M UTC")
    local_str = snapshot.now_local.strftime("%H:%M")
    offset    = _utc_offset_label(snapshot.now_local)

    header = f"[Contexto temporal: {utc_str} / {local_str} {offset}]"
    lines = [header, _WORDING]

    no_user = snapshot.secs_since_last_user is None
    no_sity = snapshot.secs_since_last_sity is None

    if no_user and no_sity:
        lines.append("Sin mensajes previos en esta sesión.")
    else:
        if not no_user:
            cat = f" ({snapshot.user_gap_category.value})" if snapshot.user_gap_category else ""
            lines.append(
                f"Último mensaje del usuario: hace {_format_delta(snapshot.secs_since_last_user)}{cat}."
            )
        if not no_sity:
            lines.append(
                f"Última respuesta de Sity: hace {_format_delta(snapshot.secs_since_last_sity)}."
            )

    return "\n".join(lines)

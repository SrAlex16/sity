"""Tests for app.chat.time_context — pure, no DB, fully deterministic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.chat.time_context import (
    GapCategory,
    TimeContextSnapshot,
    _format_delta,
    _utc_offset_label,
    build_time_context,
    classify_gap,
    render_time_context,
)

UTC = timezone.utc
FIXED_NOW = datetime(2024, 6, 15, 14, 35, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Msg:
    """Minimal stand-in for ChatMessage (needs .role, .created_at, and .text)."""

    def __init__(self, role: str, created_at: datetime, text: str = "") -> None:
        self.role = role
        self.created_at = created_at
        self.text = text


def _user(ago_secs: int) -> _Msg:
    return _Msg("user", FIXED_NOW - timedelta(seconds=ago_secs))


def _sity(ago_secs: int) -> _Msg:
    return _Msg("sity", FIXED_NOW - timedelta(seconds=ago_secs))


# ---------------------------------------------------------------------------
# build_time_context — no messages
# ---------------------------------------------------------------------------

def test_no_messages_user_delta_is_none() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    assert snap.secs_since_last_user is None


def test_no_messages_sity_delta_is_none() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    assert snap.secs_since_last_sity is None


def test_no_messages_now_utc_matches_input() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    assert snap.now_utc == FIXED_NOW


# ---------------------------------------------------------------------------
# build_time_context — last user message
# ---------------------------------------------------------------------------

def test_last_user_3_minutes_ago() -> None:
    snap = build_time_context([_user(180)], now=FIXED_NOW)
    assert snap.secs_since_last_user == 180


def test_last_user_only_sity_is_none() -> None:
    snap = build_time_context([_user(60)], now=FIXED_NOW)
    assert snap.secs_since_last_sity is None


# ---------------------------------------------------------------------------
# build_time_context — last sity message
# ---------------------------------------------------------------------------

def test_last_sity_7_minutes_ago() -> None:
    snap = build_time_context([_sity(420)], now=FIXED_NOW)
    assert snap.secs_since_last_sity == 420


def test_last_sity_only_user_is_none() -> None:
    snap = build_time_context([_sity(60)], now=FIXED_NOW)
    assert snap.secs_since_last_user is None


# ---------------------------------------------------------------------------
# build_time_context — both roles
# ---------------------------------------------------------------------------

def test_both_roles_correct_deltas() -> None:
    msgs = [_user(300), _sity(120)]
    snap = build_time_context(msgs, now=FIXED_NOW)
    assert snap.secs_since_last_user == 300
    assert snap.secs_since_last_sity == 120


def test_picks_last_per_role_in_list() -> None:
    """The last occurrence of each role in the list wins."""
    msgs = [_user(1800), _user(90)]  # 30 min ago, then 90 s ago
    snap = build_time_context(msgs, now=FIXED_NOW)
    assert snap.secs_since_last_user == 90


def test_interleaved_messages_correct() -> None:
    msgs = [_user(600), _sity(300), _user(60)]  # user 60s is most recent
    snap = build_time_context(msgs, now=FIXED_NOW)
    assert snap.secs_since_last_user == 60
    assert snap.secs_since_last_sity == 300


# ---------------------------------------------------------------------------
# build_time_context — naive datetime treated as UTC
# ---------------------------------------------------------------------------

def test_naive_created_at_treated_as_utc() -> None:
    naive_ts = datetime(2024, 6, 15, 14, 30, 0)  # naive — 5 min before FIXED_NOW
    msg = _Msg("user", naive_ts)
    snap = build_time_context([msg], now=FIXED_NOW)
    assert snap.secs_since_last_user == 300


# ---------------------------------------------------------------------------
# _format_delta
# ---------------------------------------------------------------------------

def test_format_delta_under_60s() -> None:
    assert _format_delta(45) == "45s"


def test_format_delta_exactly_60s() -> None:
    assert _format_delta(60) == "1 min"


def test_format_delta_minutes() -> None:
    assert _format_delta(180) == "3 min"


def test_format_delta_59_min() -> None:
    assert _format_delta(3540) == "59 min"


def test_format_delta_exact_hours() -> None:
    assert _format_delta(7200) == "2h"


def test_format_delta_hours_and_minutes() -> None:
    assert _format_delta(7260) == "2h 1min"


def test_format_delta_hours_and_minutes_large() -> None:
    assert _format_delta(3 * 3600 + 45 * 60) == "3h 45min"


# ---------------------------------------------------------------------------
# render_time_context — no messages
# ---------------------------------------------------------------------------

def test_render_no_messages_contains_sin_mensajes() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "Sin mensajes previos" in rendered


def test_render_no_messages_contains_utc_time() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    # FIXED_NOW is 14:35 UTC
    assert "14:35" in rendered
    assert "UTC" in rendered


def test_render_no_messages_no_user_delta_line() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "Último mensaje del usuario" not in rendered


# ---------------------------------------------------------------------------
# render_time_context — with last user message
# ---------------------------------------------------------------------------

def test_render_last_user_minutes_present() -> None:
    snap = build_time_context([_user(180)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "3 min" in rendered


def test_render_last_user_label_present() -> None:
    snap = build_time_context([_user(60)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "usuario" in rendered.lower()


def test_render_last_user_no_sin_mensajes() -> None:
    snap = build_time_context([_user(60)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "Sin mensajes previos" not in rendered


# ---------------------------------------------------------------------------
# render_time_context — with last sity message
# ---------------------------------------------------------------------------

def test_render_last_sity_minutes_present() -> None:
    snap = build_time_context([_sity(420)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "7 min" in rendered


def test_render_last_sity_label_present() -> None:
    snap = build_time_context([_sity(60)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "sity" in rendered.lower()


# ---------------------------------------------------------------------------
# render_time_context — factual, no opinion
# ---------------------------------------------------------------------------

def test_render_contains_no_opinion_words() -> None:
    """Time context must be purely factual — no subjective assessment."""
    snap = build_time_context([_user(7200)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    opinion_words = [
        "mucho", "poco", "bastante", "rápido", "lento",
        "tarde", "pronto", "demasiado", "suficiente",
    ]
    for word in opinion_words:
        assert word not in rendered.lower(), (
            f"Opinion word {word!r} found in rendered time context: {rendered!r}"
        )


def test_render_seconds_format_in_output() -> None:
    snap = build_time_context([_user(30)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "30s" in rendered


def test_render_hours_format_in_output() -> None:
    snap = build_time_context([_user(2 * 3600 + 15 * 60)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "2h" in rendered


# ---------------------------------------------------------------------------
# render_time_context — both roles
# ---------------------------------------------------------------------------

def test_render_both_roles_all_lines_present() -> None:
    msgs = [_user(300), _sity(120)]
    snap = build_time_context(msgs, now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "usuario" in rendered.lower()
    assert "sity" in rendered.lower()
    assert "5 min" in rendered   # user: 300s
    assert "2 min" in rendered   # sity: 120s


# ---------------------------------------------------------------------------
# render_time_context — prompt context integration
# ---------------------------------------------------------------------------

def test_prompt_context_builder_injects_time_block() -> None:
    """PromptContextBuilder.build() must prepend the time block to user_message_with_history."""
    from app.chat.prompt_context import PromptContextBuilder

    msgs = [_user(180), _sity(60)]  # 3 min user, 1 min sity

    def _get_messages(_session, limit: int):
        return msgs[-limit:] if limit < len(msgs) else msgs

    builder = PromptContextBuilder(get_recent_messages=_get_messages)
    ctx = builder.build(
        session=None,
        message="hola",
        history_limit=4,
        planner_history_limit=4,
    )

    assert "[Contexto temporal" in ctx.user_message_with_history
    # Planner message must NOT contain time context
    assert "[Contexto temporal" not in ctx.planner_user_message


def test_prompt_context_builder_no_messages_sin_previos() -> None:
    """When there are no prior messages, the block says so."""
    from app.chat.prompt_context import PromptContextBuilder

    def _get_messages(_session, limit: int):
        return []

    builder = PromptContextBuilder(get_recent_messages=_get_messages)
    ctx = builder.build(
        session=None,
        message="hola",
        history_limit=4,
        planner_history_limit=4,
    )

    assert "Sin mensajes previos" in ctx.user_message_with_history


# ---------------------------------------------------------------------------
# classify_gap — threshold boundaries
# ---------------------------------------------------------------------------

def test_classify_gap_same_burst_zero() -> None:
    assert classify_gap(0) == GapCategory.same_burst


def test_classify_gap_same_burst_upper() -> None:
    assert classify_gap(119) == GapCategory.same_burst


def test_classify_gap_short_gap_lower() -> None:
    assert classify_gap(120) == GapCategory.short_gap


def test_classify_gap_short_gap_upper() -> None:
    assert classify_gap(599) == GapCategory.short_gap


def test_classify_gap_normal_gap_lower() -> None:
    assert classify_gap(600) == GapCategory.normal_gap


def test_classify_gap_normal_gap_upper() -> None:
    assert classify_gap(3599) == GapCategory.normal_gap


def test_classify_gap_long_gap_lower() -> None:
    assert classify_gap(3600) == GapCategory.long_gap


def test_classify_gap_long_gap_upper() -> None:
    assert classify_gap(86399) == GapCategory.long_gap


def test_classify_gap_very_long_gap_boundary() -> None:
    assert classify_gap(86400) == GapCategory.very_long_gap


def test_classify_gap_very_long_gap_large() -> None:
    assert classify_gap(7 * 86400) == GapCategory.very_long_gap


# ---------------------------------------------------------------------------
# build_time_context — user_gap_category field
# ---------------------------------------------------------------------------

def test_snapshot_user_gap_category_none_no_messages() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    assert snap.user_gap_category is None


def test_snapshot_user_gap_same_burst() -> None:
    snap = build_time_context([_user(60)], now=FIXED_NOW)
    assert snap.user_gap_category == GapCategory.same_burst


def test_snapshot_user_gap_short_gap() -> None:
    snap = build_time_context([_user(300)], now=FIXED_NOW)
    assert snap.user_gap_category == GapCategory.short_gap


def test_snapshot_user_gap_normal_gap() -> None:
    snap = build_time_context([_user(1800)], now=FIXED_NOW)
    assert snap.user_gap_category == GapCategory.normal_gap


def test_snapshot_user_gap_long_gap() -> None:
    snap = build_time_context([_user(7200)], now=FIXED_NOW)
    assert snap.user_gap_category == GapCategory.long_gap


def test_snapshot_user_gap_very_long_gap() -> None:
    snap = build_time_context([_user(90000)], now=FIXED_NOW)
    assert snap.user_gap_category == GapCategory.very_long_gap


# ---------------------------------------------------------------------------
# build_time_context — new_day detection (local calendar day change)
# ---------------------------------------------------------------------------

def test_new_day_detected_across_midnight() -> None:
    """Message sent at 23:55 local, now is 00:05 local next day → new_day."""
    # Use a fixed-offset timezone so the test is portable (UTC+2).
    from datetime import timezone, timedelta
    TZ_PLUS2 = timezone(timedelta(hours=2))

    # now = 2024-06-16 00:05 local (UTC+2) = 2024-06-15 22:05 UTC
    now_utc = datetime(2024, 6, 15, 22, 5, tzinfo=UTC)
    now_local = now_utc.astimezone(TZ_PLUS2)  # 2024-06-16 00:05 +02:00

    # last user message = 2024-06-15 23:55 local (10 min ago in local time)
    # = 2024-06-15 21:55 UTC
    last_user_utc = datetime(2024, 6, 15, 21, 55, tzinfo=UTC)

    class _MsgWithTZ:
        role = "user"
        created_at = last_user_utc

    snap = build_time_context([_MsgWithTZ()], now=now_utc, local_tz=TZ_PLUS2)
    # 10 minutes elapsed — would be short_gap by seconds alone,
    # but calendar day changed in local time → new_day
    assert snap.user_gap_category == GapCategory.new_day
    assert snap.secs_since_last_user == 600  # delta still computed correctly


def test_same_day_long_gap_not_new_day() -> None:
    """Large gap within same calendar day must NOT be new_day."""
    snap = build_time_context([_user(7200)], now=FIXED_NOW)  # 2 hours ago, same day
    assert snap.user_gap_category == GapCategory.long_gap
    assert snap.user_gap_category != GapCategory.new_day


# ---------------------------------------------------------------------------
# render_time_context — gap category in output
# ---------------------------------------------------------------------------

def test_render_includes_gap_category_value() -> None:
    snap = build_time_context([_user(7200)], now=FIXED_NOW)  # long_gap
    rendered = render_time_context(snap)
    assert "long_gap" in rendered


def test_render_same_burst_category_present() -> None:
    snap = build_time_context([_user(30)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "same_burst" in rendered


def test_render_new_day_category_present() -> None:
    from datetime import timezone, timedelta
    TZ_PLUS2 = timezone(timedelta(hours=2))
    now_utc = datetime(2024, 6, 15, 22, 5, tzinfo=UTC)

    class _Msg:
        role = "user"
        created_at = datetime(2024, 6, 15, 21, 55, tzinfo=UTC)
        text = ""

    snap = build_time_context([_Msg()], now=now_utc, local_tz=TZ_PLUS2)
    rendered = render_time_context(snap)
    assert "new_day" in rendered


def test_render_no_category_when_no_user_messages() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    # None of the category names should appear when there are no messages
    for cat in GapCategory:
        assert cat.value not in rendered, f"Unexpected category {cat.value!r} in no-message render"


# ---------------------------------------------------------------------------
# render_time_context — wording instructions present
# ---------------------------------------------------------------------------

def test_render_contains_no_digas_hora() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "no sabes la hora" in rendered.lower()


def test_render_contains_no_menciones_mecanica() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "mecánica" in rendered.lower()


def test_render_contains_continuidad_y_tono() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "continuidad" in rendered.lower()
    assert "tono" in rendered.lower()


# ---------------------------------------------------------------------------
# render_time_context — still factual after new fields
# ---------------------------------------------------------------------------

def test_render_still_contains_no_opinion_words_with_gap() -> None:
    snap = build_time_context([_user(7200)], now=FIXED_NOW)
    rendered = render_time_context(snap)
    opinion_words = ["mucho", "poco", "bastante", "rápido", "lento", "tarde", "pronto", "demasiado"]
    for word in opinion_words:
        assert word not in rendered.lower(), (
            f"Opinion word {word!r} found: {rendered!r}"
        )

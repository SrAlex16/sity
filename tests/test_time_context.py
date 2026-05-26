"""Tests for app.chat.time_context — pure, no DB, fully deterministic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.chat.time_context import (
    TimeContextSnapshot,
    _format_delta,
    _utc_offset_label,
    build_time_context,
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


def test_render_no_messages_no_user_line() -> None:
    snap = build_time_context([], now=FIXED_NOW)
    rendered = render_time_context(snap)
    assert "usuario" not in rendered.lower()


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

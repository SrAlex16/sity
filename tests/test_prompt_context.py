"""
Tests for PromptContextBuilder — history injection and multi-topic continuity.

Regression: topics discussed a few turns earlier (anime, music) must still
appear in the context sent to the provider even when a technical topic fills
the most recent turns.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.chat.prompt_context import PromptContextBuilder
from app.chat.toolset_selector import history_limit_for_message


# ---------------------------------------------------------------------------
# Minimal ChatMessage stand-in (mirrors the one in test_time_context.py)
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)


class _Msg:
    def __init__(self, role: str, text: str, ago_secs: int = 0) -> None:
        self.role = role
        self.text = text
        self.created_at = _NOW - timedelta(seconds=ago_secs)


def _make_conversation() -> list[_Msg]:
    """
    10-message conversation that exercises the continuity bug:

    Turn 1  hola / Hola.
    Turn 2  anime  / Sity opinion on anime
    Turn 3  music  / Sity opinion on music
    Turn 4  fine-tuning  / Sity explains fine-tuning
    Turn 5  more fine-tuning / Sity responds

    With old default limit=4 only turns 4-5 (fine-tuning) are visible.
    With new default limit=10 all 5 turns are visible.
    """
    ago = 600  # oldest message was 10 min ago
    step = 60  # 1 min between messages
    msgs = [
        _Msg("user", "hola", ago),
        _Msg("sity", "Hola.", ago - step),
        _Msg("user", "qué opinas del anime?", ago - 2 * step),
        _Msg("sity", "El anime tiene una estética visual muy característica.", ago - 3 * step),
        _Msg("user", "y de la música electrónica?", ago - 4 * step),
        _Msg("sity", "La música electrónica me parece minimalista.", ago - 5 * step),
        _Msg("user", "vamos a hablar de fine-tuning", ago - 6 * step),
        _Msg("sity", "El fine-tuning permite adaptar modelos preentrenados.", ago - 7 * step),
        _Msg("user", "¿necesita muchos datos?", ago - 8 * step),
        _Msg("sity", "Generalmente sí, al menos varios cientos de ejemplos.", ago - 9 * step),
    ]
    return msgs


def _make_getter(msgs: list[_Msg]):
    def _get(_session, limit: int) -> list[_Msg]:
        # Mimic get_recent_db_messages: newest-first limit, then reverse.
        return msgs[-limit:] if limit < len(msgs) else msgs[:]
    return _get


# ---------------------------------------------------------------------------
# 1. history_limit_for_message — regression on default value
# ---------------------------------------------------------------------------

def test_history_limit_default_is_at_least_ten() -> None:
    """Default limit must cover at least 5 turns (10 messages)."""
    limit = history_limit_for_message("qué opinas de esto?")
    assert limit >= 10, f"Default history limit too low: {limit} (expected >= 10)"


def test_history_limit_single_action_stays_small() -> None:
    """Single-action messages must keep a small window to avoid context bloat."""
    assert history_limit_for_message("reinicia el backend") <= 4
    assert history_limit_for_message("saca una foto") <= 4


def test_history_limit_hemos_hablado_is_large() -> None:
    """'hemos hablado' must trigger the deep context window."""
    limit = history_limit_for_message("¿de qué temas hemos hablado?")
    assert limit >= 16, f"'hemos hablado' should trigger large limit, got {limit}"


def test_history_limit_qué_temas_is_large() -> None:
    limit = history_limit_for_message("¿qué temas hemos tratado?")
    assert limit >= 16


def test_history_limit_mencionaste_is_large() -> None:
    limit = history_limit_for_message("antes mencionaste algo de música")
    assert limit >= 16


def test_history_limit_recuerdas_still_large() -> None:
    """Previously-supported terms must still trigger the large window."""
    limit = history_limit_for_message("¿recuerdas lo que dijiste?")
    assert limit >= 16


# ---------------------------------------------------------------------------
# 2. PromptContextBuilder — multi-topic continuity regression
# ---------------------------------------------------------------------------

def test_multi_topic_history_includes_anime_and_music() -> None:
    """
    Regression test for the continuity bug.

    Given a 10-message conversation (anime, music, fine-tuning in that order),
    the context built for the next message must contain both 'anime' and 'música'
    regardless of what the last few messages were about.
    """
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="¿de qué temas hemos hablado?",
        history_limit=10,       # the new default
        planner_history_limit=4,
    )

    assert "anime" in ctx.user_message_with_history, (
        "Topic 'anime' missing from injected history — continuity bug not fixed"
    )
    assert "música" in ctx.user_message_with_history, (
        "Topic 'música' missing from injected history — continuity bug not fixed"
    )
    assert "fine-tuning" in ctx.user_message_with_history


def test_old_limit_4_would_miss_anime() -> None:
    """
    Documents the pre-fix behavior: limit=4 drops anime from context.
    This test must PASS (documenting the broken state with limit=4).
    """
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="¿de qué temas hemos hablado?",
        history_limit=4,        # old broken default
        planner_history_limit=4,
    )

    # With limit=4, only the last 4 messages (fine-tuning turns) are injected.
    assert "anime" not in ctx.user_message_with_history, (
        "Expected anime to be absent with limit=4 — this documents the bug"
    )


def test_history_injects_in_chronological_order() -> None:
    """History must arrive oldest-first so the model sees the natural flow."""
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="siguiente pregunta",
        history_limit=10,
        planner_history_limit=4,
    )

    history_text = ctx.user_message_with_history
    idx_anime = history_text.find("anime")
    idx_finetuning = history_text.find("fine-tuning")

    assert idx_anime < idx_finetuning, (
        "anime should appear before fine-tuning in the injected history "
        f"(anime at {idx_anime}, fine-tuning at {idx_finetuning})"
    )


def test_planner_history_stays_small() -> None:
    """Planner gets a compact window regardless of the main history limit."""
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="y ahora qué?",
        history_limit=10,
        planner_history_limit=4,
    )

    assert len(ctx.planner_history) <= 4


def test_operational_messages_are_filtered() -> None:
    """Guard messages (budget exhausted, local-only) must not appear in history."""
    msgs = [
        _Msg("user", "hola", 300),
        _Msg("sity", "Presupuesto diario de IA agotado.", 240),
        _Msg("user", "cuéntame algo", 180),
        _Msg("sity", "Aquí estoy.", 120),
    ]
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="siguiente",
        history_limit=10,
        planner_history_limit=4,
    )

    assert "Presupuesto diario" not in ctx.user_message_with_history


def test_empty_history_builds_without_error() -> None:
    builder = PromptContextBuilder(get_recent_messages=lambda _s, limit: [])
    ctx = builder.build(session=None, message="hola", history_limit=10, planner_history_limit=4)
    assert "hola" in ctx.user_message_with_history
    assert len(ctx.recent_history) == 0

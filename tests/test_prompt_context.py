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

def test_history_limit_default_matches_config() -> None:
    """Default limit must come from tokens.max_recent_turns in config (currently 4)."""
    from app.settings.config_loader import load_default_config
    base = int(load_default_config().get("tokens", {}).get("max_recent_turns", 4))
    limit = history_limit_for_message("qué opinas de esto?")
    assert limit == base, f"Default history limit {limit} doesn't match config base {base}"


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
    prior_messages must contain all topics regardless of what the last turns covered.
    """
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="¿de qué temas hemos hablado?",
        history_limit=10,
        planner_history_limit=4,
    )

    all_prior = " ".join(m["content"] for m in ctx.prior_messages)
    assert "anime" in all_prior, (
        "Topic 'anime' missing from prior_messages — continuity bug not fixed"
    )
    assert "música" in all_prior, (
        "Topic 'música' missing from prior_messages — continuity bug not fixed"
    )
    assert "fine-tuning" in all_prior


def test_small_limit_misses_early_topics() -> None:
    """
    With limit=4, only the 4 most recent messages go into prior_messages —
    topics from 5+ turns ago are absent and require search_conversation_history.
    """
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="¿de qué temas hemos hablado?",
        history_limit=4,
        planner_history_limit=4,
    )

    all_prior = " ".join(m["content"] for m in ctx.prior_messages)
    assert "anime" not in all_prior, (
        "Expected anime to be absent from prior_messages with limit=4"
    )


def test_history_injects_in_chronological_order() -> None:
    """prior_messages must be ordered oldest-first so the model sees the natural flow."""
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))

    ctx = builder.build(
        session=None,
        message="siguiente pregunta",
        history_limit=10,
        planner_history_limit=4,
    )

    all_prior = " ".join(m["content"] for m in ctx.prior_messages)
    idx_anime = all_prior.find("anime")
    idx_finetuning = all_prior.find("fine-tuning")

    assert idx_anime < idx_finetuning, (
        "anime should appear before fine-tuning in prior_messages "
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

    all_prior = " ".join(m["content"] for m in ctx.prior_messages)
    assert "Presupuesto diario" not in all_prior


def test_empty_history_builds_without_error() -> None:
    builder = PromptContextBuilder(get_recent_messages=lambda _s, limit: [])
    ctx = builder.build(session=None, message="hola", history_limit=10, planner_history_limit=4)
    assert "hola" in ctx.user_message_with_history
    assert len(ctx.recent_history) == 0


# ---------------------------------------------------------------------------
# 3. Structural memory context in planner_user_message
# ---------------------------------------------------------------------------

def test_planner_message_includes_structural_memory_fields() -> None:
    """planner_user_message must contain all structural memory context fields."""
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))
    ctx = builder.build(
        session=None,
        message="qué fue lo primero que hablamos?",
        history_limit=10,
        planner_history_limit=4,
    )
    for field in ("total_messages", "visible_history_count", "history_limit", "long_memory_tool_available"):
        assert field in ctx.planner_user_message, (
            f"Structural memory field {field!r} missing from planner_user_message"
        )


def test_planner_message_includes_user_message() -> None:
    """planner_user_message must still include the original user message."""
    msgs = _make_conversation()
    builder = PromptContextBuilder(get_recent_messages=_make_getter(msgs))
    ctx = builder.build(
        session=None,
        message="siguiente pregunta sobre anime",
        history_limit=10,
        planner_history_limit=4,
    )
    assert "siguiente pregunta sobre anime" in ctx.planner_user_message

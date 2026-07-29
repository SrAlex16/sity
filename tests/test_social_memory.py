"""Tests for Social Memory — turn_load tag extraction pipeline (Fase 4, Paso 2).

Verified properties:
1. <R:N> tag is always stripped before save_message and before user delivery.
2. Valid tag stores load value in SocialProfile.pending_loads_json.
3. Missing tag logs WARN for user: sessions; silent for guest:/other sessions.
4. Out-of-range value (<R:99>) logs WARN and still strips the malformed tag.
5. Guest session never gets a SocialProfile row.
6. Persona prompt includes turn_load_instruction for user: sessions only.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from app.chat.final_response_builder import (
    _append_pending_load,
    _strip_turn_load_tag,
    build_final_ai_response,
)
from app.core.persona_engine import PersonaEngine
from app.cortex.schemas import AIResponse, AIUsageData
from app.memory.models import SocialProfile


# ---------------------------------------------------------------------------
# Unit tests for _strip_turn_load_tag
# ---------------------------------------------------------------------------

def test_strip_removes_tag_at_end() -> None:
    text, raw = _strip_turn_load_tag("Hola mundo.<R:+1>")
    assert raw == "+1"
    assert text == "Hola mundo."
    assert "<R:" not in text


def test_strip_removes_tag_with_trailing_whitespace() -> None:
    text, raw = _strip_turn_load_tag("Texto aquí.<R:0>  \n")
    assert raw == "0"
    assert "<R:" not in text


def test_strip_removes_negative_tag() -> None:
    text, raw = _strip_turn_load_tag("Respuesta difícil.<R:-2>")
    assert raw == "-2"
    assert "<R:" not in text


def test_strip_no_match_returns_text_unchanged() -> None:
    original = "Sin tag aquí."
    text, raw = _strip_turn_load_tag(original)
    assert raw is None
    assert text == original


def test_strip_tag_mid_sentence_not_matched() -> None:
    # Tag NOT at end of string should not match
    original = "Texto <R:+1> más texto."
    text, raw = _strip_turn_load_tag(original)
    assert raw is None
    assert text == original


def test_strip_out_of_range_value_still_stripped() -> None:
    # <R:99> is invalid but should still be stripped from text
    text, raw = _strip_turn_load_tag("Respuesta.<R:99>")
    assert raw == "99"
    assert "<R:" not in text


# ---------------------------------------------------------------------------
# Unit tests for _append_pending_load
# ---------------------------------------------------------------------------

def _clear_profile(session: Session, user_id: int) -> None:
    profile = session.exec(select(SocialProfile).where(SocialProfile.user_id == user_id)).first()
    if profile:
        session.delete(profile)
        session.commit()


def test_append_creates_profile_if_missing(db_session: Session) -> None:
    _clear_profile(db_session, 9901)
    _append_pending_load(db_session, "user:9901", 1)
    db_session.commit()
    profile = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == 9901)).first()
    assert profile is not None
    assert json.loads(profile.pending_loads_json) == [1]


def test_append_accumulates_loads(db_session: Session) -> None:
    _clear_profile(db_session, 9902)
    _append_pending_load(db_session, "user:9902", 1)
    db_session.commit()
    _append_pending_load(db_session, "user:9902", -1)
    db_session.commit()
    _append_pending_load(db_session, "user:9902", 0)
    db_session.commit()
    profile = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == 9902)).first()
    assert json.loads(profile.pending_loads_json) == [1, -1, 0]


def test_append_invalid_session_id_is_silent(db_session: Session) -> None:
    # Should not raise, should not create any row
    _append_pending_load(db_session, "guest:abc", 1)
    db_session.commit()
    _append_pending_load(db_session, "malformed", 0)
    db_session.commit()
    # No SocialProfile created for these
    row = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == 0)).first()
    assert row is None


# ---------------------------------------------------------------------------
# Integration: build_final_ai_response strips tag before save and return
# ---------------------------------------------------------------------------

def _make_response(text: str) -> AIResponse:
    return AIResponse(
        ok=True,
        provider="mock",
        model="mock-model",
        text=text,
        usage=AIUsageData(input_tokens=10, output_tokens=5),
        latency_ms=100,
        fallback_used=False,
    )


def _run_build_final(
    db_session: Session,
    response_text: str,
    session_id: str = "user:1",
    captured_saves: list[str] | None = None,
) -> tuple[Any, list[str]]:
    """Call build_final_ai_response with a minimal mock context."""
    saved: list[str] = captured_saves if captured_saves is not None else []

    def _save(*, role: str, text: str, **_kwargs: Any) -> None:
        saved.append(text)

    result = build_final_ai_response(
        session=db_session,
        trace_id="trc_test_social",
        response=_make_response(response_text),
        daily_budget=100_000,
        warning_threshold=0.7,
        critical_threshold=0.9,
        get_today_token_usage=lambda s: 0,
        save_message=_save,
        refusal_mode=False,
        user_message="hola",
        updated_parameters=[],
        artifacts=[],
        session_id=session_id,
    )
    return result, saved


def test_tag_stripped_from_returned_response_text(db_session: Session) -> None:
    result, _ = _run_build_final(db_session, "Respuesta normal.<R:+1>")
    assert "<R:" not in result.text
    assert result.text == "Respuesta normal."


def test_tag_stripped_from_saved_message(db_session: Session) -> None:
    _, saved = _run_build_final(db_session, "Texto guardado.<R:0>")
    sity_text = saved[-1]  # last save is the sity message
    assert "<R:" not in sity_text


def test_tag_stripped_even_when_value_invalid(db_session: Session) -> None:
    result, saved = _run_build_final(db_session, "Respuesta.<R:99>")
    assert "<R:" not in result.text
    assert all("<R:" not in s for s in saved)


def test_valid_tag_creates_pending_load(db_session: Session) -> None:
    uid = 9910
    _clear_profile(db_session, uid)
    _run_build_final(db_session, "Respuesta.<R:+2>", session_id=f"user:{uid}")
    profile = db_session.exec(select(SocialProfile).where(SocialProfile.user_id == uid)).first()
    assert profile is not None
    assert 2 in json.loads(profile.pending_loads_json)


def test_guest_session_no_profile_created(db_session: Session) -> None:
    result, _ = _run_build_final(db_session, "Hola guest.<R:+1>", session_id="guest:abc123")
    # Guest: tag is stripped but no SocialProfile created
    assert "<R:" not in result.text
    # There should be no SocialProfile for any user matching guest session
    # (guest: prefix → _append_pending_load bails early)
    all_profiles = db_session.exec(select(SocialProfile)).all()
    for p in all_profiles:
        # Any existing profile should not correspond to a "guest:" session parse
        assert p.user_id > 0


# ---------------------------------------------------------------------------
# Logging: WARN emitted for missing or invalid tags
# ---------------------------------------------------------------------------

def test_missing_tag_logs_warning_for_user_session(db_session: Session) -> None:
    with patch("app.chat.final_response_builder.write_log") as mock_log:
        _run_build_final(db_session, "Sin tag aquí.", session_id="user:1")

    warn_calls = [
        call for call in mock_log.call_args_list
        if call.kwargs.get("event") == "turn_load_tag_missing"
    ]
    assert len(warn_calls) == 1
    assert warn_calls[0].kwargs["level"] == "WARN"
    assert warn_calls[0].kwargs["payload"]["session_id"] == "user:1"


def test_missing_tag_no_warning_for_guest_session(db_session: Session) -> None:
    with patch("app.chat.final_response_builder.write_log") as mock_log:
        _run_build_final(db_session, "Sin tag.", session_id="guest:abc")

    social_warns = [
        call for call in mock_log.call_args_list
        if call.kwargs.get("module") == "social"
    ]
    assert len(social_warns) == 0


def test_invalid_tag_value_logs_warning(db_session: Session) -> None:
    with patch("app.chat.final_response_builder.write_log") as mock_log:
        _run_build_final(db_session, "Respuesta.<R:99>", session_id="user:1")

    invalid_calls = [
        call for call in mock_log.call_args_list
        if call.kwargs.get("event") == "turn_load_tag_invalid"
    ]
    assert len(invalid_calls) == 1
    assert invalid_calls[0].kwargs["payload"]["raw_value"] == "99"


# ---------------------------------------------------------------------------
# Persona prompt: turn_load_instruction injected only for user: sessions
# ---------------------------------------------------------------------------

def test_turn_load_instruction_in_user_prompt() -> None:
    engine = PersonaEngine()
    result = engine.build_persona_prompt({}, "hola", session_id="user:1")
    assert "INSTRUCCIÓN INTERNA — ETIQUETA DE CARGA CONVERSACIONAL" in result.system_prompt
    assert "<R:N>" in result.system_prompt


def test_turn_load_instruction_absent_for_guest_prompt() -> None:
    engine = PersonaEngine()
    result = engine.build_persona_prompt({}, "hola", session_id="guest:abc")
    assert "ETIQUETA DE CARGA CONVERSACIONAL" not in result.system_prompt
    assert "<R:N>" not in result.system_prompt


def test_turn_load_instruction_absent_for_default_session() -> None:
    engine = PersonaEngine()
    result = engine.build_persona_prompt({}, "hola", session_id="")
    assert "ETIQUETA DE CARGA CONVERSACIONAL" not in result.system_prompt

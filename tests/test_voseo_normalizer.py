"""Tests for Haiku-based voseo normalizer and its integration in build_final_ai_response.

Covers:
  - Pre-filter: text with no voseo markers → Haiku not called (zero cost)
  - Pre-filter: text over _MAX_VOSEO_NORM_CHARS → Haiku not called
  - Haiku corrects known voseo form ("querés" → "quieres")
  - Haiku corrects a form the old 17-verb list would have missed ("comés")
  - Haiku returns original when text has no actual voseo (pre-filter false positive)
  - API failure → original text returned (fallback, never blocks the turn)
  - Integration: builder applies normalization for es-ES
  - Integration: es-419 and other languages never normalized
  - Logging: voseo_normalized event emitted exactly when correction occurs
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.chat.final_response_builder import _normalize_voseo_haiku, _VOSEO_DETECT_RE


# ---------------------------------------------------------------------------
# Pre-filter (_VOSEO_DETECT_RE)
# ---------------------------------------------------------------------------

def test_prefilter_matches_vos_pronoun():
    assert _VOSEO_DETECT_RE.search("¿Qué querés hacer vos?")


def test_prefilter_matches_accented_verb():
    assert _VOSEO_DETECT_RE.search("Si querés, podemos hablar.")


def test_prefilter_matches_sos_copula():
    assert _VOSEO_DETECT_RE.search("Sos muy inteligente.")


def test_prefilter_no_match_clean_text():
    assert not _VOSEO_DETECT_RE.search("Claro que puedes hacerlo si quieres.")


# ---------------------------------------------------------------------------
# _normalize_voseo_haiku — pre-filter skips Haiku
# ---------------------------------------------------------------------------

def _mock_provider(corrected_text: str):
    """Return a mock provider that responds with corrected_text."""
    resp = MagicMock()
    resp.ok = True
    resp.text = corrected_text
    provider = MagicMock()
    provider.generate.return_value = resp
    return provider


def test_no_voseo_no_haiku_call():
    """Text without voseo markers must not call the provider."""
    text = "Claro que puedes hacerlo cuando quieras."
    with patch("app.cortex.providers.factory.build_ai_provider") as mock_build:
        result = _normalize_voseo_haiku(text, trace_id="t")
    mock_build.assert_not_called()
    assert result == text


def test_long_text_skips_haiku():
    """Text exceeding _MAX_VOSEO_NORM_CHARS must not call the provider even with voseo."""
    from app.chat.final_response_builder import _MAX_VOSEO_NORM_CHARS
    long_text = "Querés saber algo. " * (_MAX_VOSEO_NORM_CHARS // 18 + 5)
    assert len(long_text) > _MAX_VOSEO_NORM_CHARS
    with patch("app.cortex.providers.factory.build_ai_provider") as mock_build:
        result = _normalize_voseo_haiku(long_text, trace_id="t")
    mock_build.assert_not_called()
    assert result == long_text


# ---------------------------------------------------------------------------
# _normalize_voseo_haiku — Haiku corrects voseo
# ---------------------------------------------------------------------------

def test_haiku_corrects_known_voseo_form():
    """Haiku corrects a known voseo form (querés → quieres)."""
    original = "¿Qué querés hacer hoy?"
    corrected = "¿Qué quieres hacer hoy?"
    with patch("app.cortex.providers.factory.build_ai_provider",
               return_value=_mock_provider(corrected)):
        result = _normalize_voseo_haiku(original, trace_id="t")
    assert result == corrected


def test_haiku_corrects_verb_not_in_old_list():
    """Haiku corrects voseo forms the old 17-verb hardcoded list would have missed.

    'comés' (comer), 'bebés' (beber) were never in _VOSEO_SUBS.
    """
    original = "¿Comés mucho o poco?"
    corrected = "¿Comes mucho o poco?"
    with patch("app.cortex.providers.factory.build_ai_provider",
               return_value=_mock_provider(corrected)):
        result = _normalize_voseo_haiku(original, trace_id="t")
    assert result == corrected


def test_haiku_returns_original_when_no_actual_voseo():
    """Pre-filter false positive (e.g. 'más'): Haiku returns original → unchanged."""
    text = "Quiero saber más sobre este tema."
    with patch("app.cortex.providers.factory.build_ai_provider",
               return_value=_mock_provider(text)):
        result = _normalize_voseo_haiku(text, trace_id="t")
    assert result == text


def test_api_failure_returns_original():
    """Provider failure must not block the turn — original text returned."""
    original = "Querés saber algo importante."
    with patch("app.cortex.providers.factory.build_ai_provider",
               side_effect=RuntimeError("connection refused")):
        result = _normalize_voseo_haiku(original, trace_id="t")
    assert result == original


def test_provider_returns_empty_falls_back():
    """Empty provider response → fallback to original."""
    original = "¿Tenés tiempo esta tarde?"
    resp = MagicMock()
    resp.ok = True
    resp.text = ""
    provider = MagicMock()
    provider.generate.return_value = resp
    with patch("app.cortex.providers.factory.build_ai_provider", return_value=provider):
        result = _normalize_voseo_haiku(original, trace_id="t")
    assert result == original


# ---------------------------------------------------------------------------
# Integration — build_final_ai_response calls normalizer for es-ES only
# ---------------------------------------------------------------------------

def _make_mock_response(text: str):
    r = MagicMock()
    r.ok = True
    r.text = text
    r.provider = "anthropic"
    r.model = "claude-haiku-4-5-20251001"
    r.latency_ms = 100
    r.fallback_used = False
    r.error_type = None
    r.usage = MagicMock(
        input_tokens=100, output_tokens=20,
        cache_creation_tokens=0, cache_read_tokens=0,
    )
    return r


def _make_session():
    from sqlmodel import SQLModel, Session, create_engine
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _call_builder(text: str, language_override: str) -> str:
    from app.chat.final_response_builder import build_final_ai_response
    response = _make_mock_response(text)

    with _make_session() as session:
        result = build_final_ai_response(
            session=session,
            trace_id="trc_test_voseo",
            response=response,
            daily_budget=1_000_000,
            warning_threshold=0.8,
            critical_threshold=0.95,
            get_today_token_usage=lambda s: 0,
            save_message=MagicMock(),
            refusal_mode=False,
            user_message="hola",
            updated_parameters=[],
            artifacts=[],
            session_id="user:1",
            language_override=language_override,
        )
    return result.text


def test_builder_normalizes_voseo_for_es_es():
    corrected = "¿Qué quieres hacer hoy?"
    with patch("app.cortex.providers.factory.build_ai_provider",
               return_value=_mock_provider(corrected)):
        result = _call_builder("¿Qué querés hacer hoy?", language_override="es-ES")
    assert result == corrected


def test_builder_does_not_normalize_for_es_419():
    """es-419 (Rioplatense): voseo must be preserved — normalizer never called."""
    original = "¿Qué querés hacer hoy?"
    with patch("app.cortex.providers.factory.build_ai_provider") as mock_build:
        result = _call_builder(original, language_override="es-419")
    mock_build.assert_not_called()
    assert result == original


def test_builder_does_not_normalize_for_auto():
    original = "Querés ir al parque."
    with patch("app.cortex.providers.factory.build_ai_provider") as mock_build:
        result = _call_builder(original, language_override="auto")
    mock_build.assert_not_called()
    assert result == original


def test_builder_does_not_normalize_for_en_us():
    original = "Do you want to go?"
    with patch("app.cortex.providers.factory.build_ai_provider") as mock_build:
        result = _call_builder(original, language_override="en-US")
    mock_build.assert_not_called()
    assert result == original


# ---------------------------------------------------------------------------
# Logging — voseo_normalized event emitted exactly when correction occurs
# ---------------------------------------------------------------------------

def test_voseo_normalized_event_logged_when_changed():
    corrected = "¿Qué quieres hacer?"
    logged_events: list[dict] = []

    def capture_log(**kwargs):
        logged_events.append(kwargs)

    with patch("app.chat.final_response_builder.write_log", side_effect=capture_log), \
         patch("app.cortex.providers.factory.build_ai_provider",
               return_value=_mock_provider(corrected)):
        _call_builder("¿Qué querés hacer?", language_override="es-ES")

    events = [e for e in logged_events if e.get("event") == "voseo_normalized"]
    assert len(events) == 1
    assert events[0]["module"] == "persona"
    assert events[0]["level"] == "INFO"


def test_voseo_normalized_event_not_logged_when_no_change():
    text = "Puedes hacer lo que quieras."
    logged_events: list[dict] = []

    def capture_log(**kwargs):
        logged_events.append(kwargs)

    with patch("app.chat.final_response_builder.write_log", side_effect=capture_log):
        _call_builder(text, language_override="es-ES")

    events = [e for e in logged_events if e.get("event") == "voseo_normalized"]
    assert len(events) == 0


def test_voseo_normalized_event_not_logged_for_es_419():
    logged_events: list[dict] = []

    def capture_log(**kwargs):
        logged_events.append(kwargs)

    with patch("app.chat.final_response_builder.write_log", side_effect=capture_log):
        _call_builder("Vos querés saber.", language_override="es-419")

    events = [e for e in logged_events if e.get("event") == "voseo_normalized"]
    assert len(events) == 0

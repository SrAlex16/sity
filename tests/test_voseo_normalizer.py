"""Tests for normalize_registro_es_es and its integration in build_final_ai_response.

Covers:
  - Each known voseo form → correct tuteo replacement
  - False-positive safety (estás, más, etc. untouched)
  - es-419 and other languages never normalized
  - Integration: normalization happens in build_final_ai_response for es-ES
  - Logging: voseo_normalized event emitted when correction occurs
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.chat.final_response_builder import normalize_registro_es_es


# ---------------------------------------------------------------------------
# normalize_registro_es_es — known voseo forms
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("voseo,tuteo", [
    ("vos",      "tú"),
    ("querés",   "quieres"),
    ("tenés",    "tienes"),
    ("podés",    "puedes"),
    ("hacés",    "haces"),
    ("sos",      "eres"),
    ("sabés",    "sabes"),
    ("venís",    "vienes"),
    ("decís",    "dices"),
    ("conocés",  "conoces"),
    ("entendés", "entiendes"),
])
def test_known_voseo_form_replaced(voseo: str, tuteo: str):
    text = f"Claro que {voseo} lo sabes."
    result, changed = normalize_registro_es_es(text)
    assert tuteo in result, f"Expected {tuteo!r} in {result!r}"
    assert voseo not in result, f"Voseo form {voseo!r} must not remain in {result!r}"
    assert changed is True


def test_multiple_voseo_forms_in_one_text():
    text = "Vos querés saber y tenés razón."
    result, changed = normalize_registro_es_es(text)
    assert "Tú" in result
    assert "quieres" in result
    assert "tienes" in result
    assert "vos" not in result.lower().split()
    assert changed is True


def test_voseo_at_start_of_sentence_capitalized():
    text = "Querés conocer las consecuencias sin que te controlen."
    result, changed = normalize_registro_es_es(text)
    assert result.startswith("Quieres"), f"Got: {result!r}"
    assert changed is True


def test_voseo_capitalized_mid_text():
    """Capitalized form mid-sentence — should be replaced with capital tuteo."""
    text = "Pero Vos podés elegir."
    result, changed = normalize_registro_es_es(text)
    assert "Tú" in result
    assert changed is True


def test_no_voseo_returns_unchanged():
    text = "Claro que puedes hacerlo si quieres."
    result, changed = normalize_registro_es_es(text)
    assert result == text
    assert changed is False


def test_empty_string():
    result, changed = normalize_registro_es_es("")
    assert result == ""
    assert changed is False


# ---------------------------------------------------------------------------
# False-positive safety — words that must NOT be touched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("safe_word,context", [
    ("estás",    "¿Cómo estás hoy?"),
    ("más",      "Quiero saber más sobre esto."),
    ("vas",      "¿Adónde vas esta tarde?"),
    ("das",      "¿Me das un ejemplo?"),
    ("SOS",      "Envió una señal SOS desde el barco."),
    ("vosotros", "Vosotros tenéis razón."),
    ("hacéis",   "Lo hacéis muy bien."),
    ("estáis",   "¿Estáis listos?"),
    ("queréis",  "¿Qué queréis comer?"),
    ("ves",      "¿Lo ves desde ahí?"),
    ("tomás",    "Tomás llegó tarde."),     # nombre propio que termina en -ás
    ("demás",    "Los demás están aquí."),
    ("después",  "Lo haré después."),
])
def test_false_positive_not_touched(safe_word: str, context: str):
    result, changed = normalize_registro_es_es(context)
    assert result == context, (
        f"Text was unexpectedly modified.\n  Before: {context!r}\n  After:  {result!r}"
    )
    assert changed is False


def test_vosotros_not_matched_as_vos():
    """'vosotros' contains 'vos' but must NOT be changed."""
    text = "Vosotros sois el futuro."
    result, changed = normalize_registro_es_es(text)
    assert "vosotros" in result.lower()
    assert "tú" not in result.lower()
    assert changed is False


# ---------------------------------------------------------------------------
# Integration — build_final_ai_response applies normalization for es-ES only
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
    result = _call_builder(
        "Querés conocer las consecuencias sin que te controlen.",
        language_override="es-ES",
    )
    assert "Quieres" in result
    assert "Querés" not in result


def test_builder_does_not_normalize_for_es_419():
    """es-419 (Rioplatense): voseo must be preserved."""
    result = _call_builder(
        "Querés conocer las consecuencias.",
        language_override="es-419",
    )
    assert "Querés" in result


def test_builder_does_not_normalize_for_auto():
    result = _call_builder(
        "Querés ir al parque.",
        language_override="auto",
    )
    assert "Querés" in result


def test_builder_does_not_normalize_for_en_us():
    result = _call_builder(
        "Do you want to go?",
        language_override="en-US",
    )
    assert "Do you want to go?" in result


# ---------------------------------------------------------------------------
# Logging — voseo_normalized event emitted exactly when correction occurs
# ---------------------------------------------------------------------------

def test_voseo_normalized_event_logged_when_changed():
    logged_events: list[dict] = []

    def capture_log(**kwargs):
        logged_events.append(kwargs)

    with patch("app.chat.final_response_builder.write_log", side_effect=capture_log):
        _call_builder("Vos querés saber.", language_override="es-ES")

    events = [e for e in logged_events if e.get("event") == "voseo_normalized"]
    assert len(events) == 1
    assert events[0]["module"] == "persona"
    assert events[0]["level"] == "INFO"


def test_voseo_normalized_event_not_logged_when_no_change():
    logged_events: list[dict] = []

    def capture_log(**kwargs):
        logged_events.append(kwargs)

    with patch("app.chat.final_response_builder.write_log", side_effect=capture_log):
        _call_builder("Puedes hacer lo que quieras.", language_override="es-ES")

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

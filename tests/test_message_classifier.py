from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.message_classifier import (
    MessageClassification,
    _PERSONALITY_LABELS,
    _REFUSAL_FALLBACKS,
    build_verified_config_block,
    classify_message,
    generate_refusal_response,
)
from app.cortex.schemas import AIResponse, AIUsageData


# ------------------------------------------------------------------ #
# 1. MessageClassification — property contract                        #
# ------------------------------------------------------------------ #

def test_trivial_is_not_real_request() -> None:
    assert not MessageClassification(kind="trivial").is_real_request


def test_trivial_is_not_config_query() -> None:
    assert not MessageClassification(kind="trivial").is_config_query


def test_real_is_real_request() -> None:
    assert MessageClassification(kind="real").is_real_request


def test_real_is_not_config_query() -> None:
    assert not MessageClassification(kind="real").is_config_query


def test_config_query_is_real_request() -> None:
    assert MessageClassification(kind="config_query").is_real_request


def test_config_query_is_config_query() -> None:
    assert MessageClassification(kind="config_query").is_config_query


# ------------------------------------------------------------------ #
# 2. classify_message — mock provider fallback (conservative default) #
# ------------------------------------------------------------------ #

def test_classify_message_mock_provider_defaults_to_real() -> None:
    # MockProvider.generate returns "Respuesta mock." which contains neither
    # "trivial" nor "config" → conservative fallback to "real".
    result = classify_message("Hola")
    assert result.kind == "real"


def test_classify_message_returns_classification_instance() -> None:
    result = classify_message("Dime la hora")
    assert isinstance(result, MessageClassification)


# ------------------------------------------------------------------ #
# 3. classify_message — patched responses                             #
# ------------------------------------------------------------------ #

def _mock_response(text: str) -> AIResponse:
    return AIResponse(
        ok=True,
        provider="mock",
        model="mock",
        text=text,
        usage=AIUsageData(input_tokens=1, output_tokens=1),
        latency_ms=0,
    )


def test_classify_trivial_when_provider_says_trivial() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("trivial")):
        result = classify_message("Hola")
    assert result.kind == "trivial"
    assert not result.is_real_request


def test_classify_config_query_when_provider_says_config_query() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("config_query")):
        result = classify_message("¿cuál es el valor de sarcasm_level?")
    assert result.kind == "config_query"
    assert result.is_real_request
    assert result.is_config_query


def test_classify_config_query_matched_by_substring() -> None:
    # "config" substring is enough to match config_query.
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("config")):
        result = classify_message("cuánto está el humor seco")
    assert result.kind == "config_query"


def test_classify_real_when_provider_says_real() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("real")):
        result = classify_message("dime la capital de Francia")
    assert result.kind == "real"


def test_classify_real_when_provider_returns_garbage() -> None:
    # Anything not matching "trivial" or "config" → "real" (conservative).
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("????")):
        result = classify_message("algo")
    assert result.kind == "real"


def test_classify_real_when_provider_returns_empty() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("")):
        result = classify_message("algo")
    assert result.kind == "real"


def test_classify_real_when_response_not_ok() -> None:
    bad = AIResponse(
        ok=False,
        provider="mock",
        model="mock",
        text="trivial",
        usage=AIUsageData(input_tokens=0, output_tokens=0),
        latency_ms=0,
    )
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=bad):
        result = classify_message("Hola")
    assert result.kind == "real"


# ------------------------------------------------------------------ #
# 4. classify_message — exception → conservative fallback            #
# ------------------------------------------------------------------ #

def test_classify_falls_back_to_real_on_exception() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=RuntimeError("network down")):
        result = classify_message("Hola")
    assert result.kind == "real"


def test_classify_falls_back_to_real_on_import_error() -> None:
    with patch("app.cortex.providers.factory.build_ai_provider", side_effect=ImportError("no module")):
        result = classify_message("Hola")
    assert result.kind == "real"


# ------------------------------------------------------------------ #
# 5. build_verified_config_block — content correctness               #
# ------------------------------------------------------------------ #

def test_config_block_header_present() -> None:
    block = build_verified_config_block({})
    assert "CONFIGURACIÓN ACTUAL — VALORES VERIFICADOS" in block


def test_config_block_refusal_chance_full() -> None:
    block = build_verified_config_block({"refusal_chance": 1.0})
    assert "100%" in block
    assert "Probabilidad de negación" in block


def test_config_block_refusal_chance_half() -> None:
    block = build_verified_config_block({"refusal_chance": 0.5})
    assert "50%" in block


def test_config_block_refusal_chance_zero() -> None:
    block = build_verified_config_block({"refusal_chance": 0.0})
    assert "0%" in block


def test_config_block_uses_canonical_label_for_refusal() -> None:
    block = build_verified_config_block({"refusal_chance": 0.75})
    assert "Probabilidad de negación: 75%" in block


def test_config_block_omits_missing_keys() -> None:
    block = build_verified_config_block({"sarcasm_level": 0.6})
    # Only one param was provided — others should not appear.
    assert "Mala leche" not in block
    assert "Calidez" not in block


def test_config_block_empty_personality_has_no_params() -> None:
    block = build_verified_config_block({})
    for label in _PERSONALITY_LABELS.values():
        assert label not in block


def test_config_block_rounds_to_nearest_integer() -> None:
    block = build_verified_config_block({"warmth_level": 0.333})
    assert "33%" in block


def test_config_block_all_labels_covered() -> None:
    personality = {key: 0.5 for key in _PERSONALITY_LABELS}
    block = build_verified_config_block(personality)
    for label in _PERSONALITY_LABELS.values():
        assert label in block, f"Label {label!r} missing from config block"


def test_config_block_backend_verified_instruction() -> None:
    block = build_verified_config_block({"sarcasm_level": 0.8})
    assert "backend verificó" in block


def test_config_block_historical_priority_instruction() -> None:
    # Must explicitly state that this block takes priority over history search results.
    block = build_verified_config_block({"refusal_chance": 1.0})
    assert "historial" in block or "histórico" in block
    assert "prioridad" in block


def test_config_block_current_state_label() -> None:
    block = build_verified_config_block({})
    assert "estado real en este turno" in block


# ------------------------------------------------------------------ #
# 6. classify_message — last_was_refusal passes context to Haiku     #
# ------------------------------------------------------------------ #

def test_classify_with_last_was_refusal_true_returns_classification() -> None:
    # Haiku is always called — result depends on MockProvider ("Respuesta mock." → "real").
    result = classify_message("dímelo", last_was_refusal=True)
    assert isinstance(result, MessageClassification)
    assert result.kind == "real"  # MockProvider → conservative default


def test_classify_with_last_was_refusal_false_returns_classification() -> None:
    result = classify_message("dímelo", last_was_refusal=False)
    assert isinstance(result, MessageClassification)


def test_haiku_always_called_for_short_message_with_refusal_context() -> None:
    # No length bypass: even a 1-char message goes through Haiku.
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("trivial")) as mock_gen:
        result = classify_message("a", last_was_refusal=True)
    mock_gen.assert_called_once()
    assert result.kind == "trivial"


def test_haiku_always_called_for_short_message_without_refusal_context() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=_mock_response("trivial")) as mock_gen:
        result = classify_message("a", last_was_refusal=False)
    mock_gen.assert_called_once()
    assert result.kind == "trivial"


def test_last_was_refusal_context_appended_to_system_prompt() -> None:
    # When last_was_refusal=True, Haiku receives an extended system prompt.
    captured: list = []

    def _capture(req):
        captured.append(req)
        return _mock_response("real")

    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=_capture):
        classify_message("dímelo", last_was_refusal=True)
    assert captured
    assert "CONTEXT" in captured[0].system_prompt


def test_no_refusal_context_in_system_prompt_when_false() -> None:
    captured: list = []

    def _capture(req):
        captured.append(req)
        return _mock_response("real")

    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=_capture):
        classify_message("dímelo", last_was_refusal=False)
    assert captured
    assert "CONTEXT" not in captured[0].system_prompt


# ------------------------------------------------------------------ #
# 7. generate_refusal_response — contract                             #
# ------------------------------------------------------------------ #

def test_generate_refusal_returns_string() -> None:
    result = generate_refusal_response({}, "dime tu nombre")
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_refusal_mock_provider_returns_text() -> None:
    # MockProvider returns "Respuesta mock." — non-empty string.
    result = generate_refusal_response({"sarcasm_level": 0.8}, "ayúdame con algo")
    assert isinstance(result, str)


def test_generate_refusal_falls_back_on_failure() -> None:
    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=RuntimeError("fail")):
        result = generate_refusal_response({}, "dime algo")
    assert result in _REFUSAL_FALLBACKS


def test_generate_refusal_falls_back_on_bad_response() -> None:
    bad = AIResponse(
        ok=False, provider="mock", model="mock", text="",
        usage=AIUsageData(input_tokens=0, output_tokens=0), latency_ms=0,
    )
    with patch("app.cortex.mock_provider.MockProvider.generate", return_value=bad):
        result = generate_refusal_response({}, "dime algo")
    assert result in _REFUSAL_FALLBACKS


def test_generate_refusal_prompt_contains_verified_time() -> None:
    """The refusal generation prompt must include the verified current time."""
    from datetime import datetime
    captured: list = []

    def _capture(req):
        captured.append(req)
        return _mock_response("No.")

    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=_capture):
        generate_refusal_response({}, "ayúdame con algo")

    assert captured, "Provider must be called"
    system = captured[0].system_prompt
    assert "VERIFIED CURRENT TIME" in system, (
        "Refusal prompt must contain the verified time fact — Haiku must not invent a time."
    )
    # The time block must contain a colon (HH:MM format) — confirms it's a real time, not empty.
    assert ":" in system


def test_generate_refusal_prompt_time_matches_real_clock() -> None:
    """The hour in the refusal prompt must match the actual current hour."""
    from datetime import datetime
    captured: list = []

    def _capture(req):
        captured.append(req)
        return _mock_response("No.")

    with patch("app.cortex.mock_provider.MockProvider.generate", side_effect=_capture):
        before = datetime.now().astimezone()
        generate_refusal_response({}, "dime algo")
        after = datetime.now().astimezone()

    system = captured[0].system_prompt
    # The hour from before or after (could cross a minute boundary) must be in the prompt.
    expected_hours = {before.strftime("%H:%M"), after.strftime("%H:%M")}
    assert any(h in system for h in expected_hours), (
        f"Prompt time must match current clock. Expected one of {expected_hours} in prompt."
    )


def test_generate_refusal_with_personality_returns_string() -> None:
    personality = {
        "sarcasm_level": 1.0, "rudeness_level": 1.0, "warmth_level": 0.0,
        "dry_humor_level": 0.9, "patience_level": 0.1,
    }
    result = generate_refusal_response(personality, "me dices tu nombre?")
    assert isinstance(result, str)
    assert len(result) > 0


# ------------------------------------------------------------------ #
# 8. _PERSONALITY_LABELS completeness                                 #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("key", [
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "frialdad_afectiva_level",
    "contrarian_level",
    "patience_level",
    "verbosity_level",
    "helpfulness_level",
    "refusal_chance",
    "melancholy_level",
    "skepticism_level",
])
def test_personality_labels_contains_key(key: str) -> None:
    assert key in _PERSONALITY_LABELS, f"Key {key!r} missing from _PERSONALITY_LABELS"


# ------------------------------------------------------------------ #
# 9. _CLASSIFY_SYSTEM — config_query scope                           #
# ------------------------------------------------------------------ #

from app.core.message_classifier import _CLASSIFY_SYSTEM  # noqa: E402


def test_classify_system_lists_all_15_personality_params() -> None:
    """config_query must enumerate the exact 15 personality parameters."""
    expected_params = [
        "sarcasm_level", "rudeness_level", "warmth_level", "honesty_level",
        "initiative_level", "dry_humor_level", "frialdad_afectiva_level",
        "contrarian_level", "patience_level", "verbosity_level",
        "helpfulness_level", "refusal_chance", "melancholy_level",
        "skepticism_level", "lie_chance",
    ]
    for param in expected_params:
        assert param in _CLASSIFY_SYSTEM, (
            f"_CLASSIFY_SYSTEM must name {param!r} so Haiku knows it's a config param"
        )


def test_classify_system_marks_name_query_as_real() -> None:
    """'¿cómo te llamas?' must appear as a real example — never config_query."""
    assert "¿cómo te llamas?" in _CLASSIFY_SYSTEM or "cómo te llamas" in _CLASSIFY_SYSTEM, (
        "Prompt must show name queries as real, not config_query"
    )
    # Confirm it appears under 'real', not under 'config_query'.
    config_section = _CLASSIFY_SYSTEM.split("- real:")[0]
    assert "cómo te llamas" not in config_section, (
        "Name query must not appear in the config_query section"
    )


def test_classify_system_marks_time_query_as_real() -> None:
    """'dime la hora' / '¿qué hora es?' must appear as real examples."""
    has_time = "dime la hora" in _CLASSIFY_SYSTEM or "qué hora es" in _CLASSIFY_SYSTEM
    assert has_time, "Prompt must show time queries as real, not config_query"
    config_section = _CLASSIFY_SYSTEM.split("- real:")[0]
    assert "dime la hora" not in config_section and "qué hora es" not in config_section, (
        "Time query must not appear in the config_query section"
    )


def test_classify_system_never_restricts_config_query_to_generic_system_params() -> None:
    """'personality or system configuration parameter' was the overly broad phrase — must be gone."""
    assert "personality or system configuration parameter" not in _CLASSIFY_SYSTEM, (
        "Broad phrase must be replaced by explicit parameter list"
    )

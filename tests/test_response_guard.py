"""Tests for response_guard module."""
from __future__ import annotations

import pytest

from app.chat.response_guard import ResponseGuard, has_narrated_search


# ---------------------------------------------------------------------------
# has_narrated_search
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "acabo de buscar en la memoria pero no encontré nada",
    "He buscado en el historial y no hay resultados",
    "busco en mis registros internos pero no veo nada",
    "intento buscar pero la búsqueda no arroja resultados",
    "no encuentro en el historial lo que me pides",
])
def test_has_narrated_search_detects_phrases(text: str) -> None:
    assert has_narrated_search(text), f"Expected narrated search detected in: {text!r}"


@pytest.mark.parametrize("text", [
    "¿qué quieres que busque?",
    "voy a usar search_conversation_history ahora",
    "no recuerdo eso",
    "",
    None,  # type: ignore[arg-type]
])
def test_has_narrated_search_rejects_false_positives(text) -> None:
    assert not has_narrated_search(text), f"Expected no narrated search in: {text!r}"


# ---------------------------------------------------------------------------
# ResponseGuard — basic smoke tests
# ---------------------------------------------------------------------------

def test_response_guard_allows_clean_text() -> None:
    result = ResponseGuard().validate_final_text("Hola, ¿en qué puedo ayudarte?")
    assert result.allowed
    assert result.text == "Hola, ¿en qué puedo ayudarte?"


def test_response_guard_blocks_invalid_confirmation() -> None:
    result = ResponseGuard().validate_final_text("confirmo ejecutar git_fetch_readme")
    assert not result.allowed
    assert result.reason == "invalid_model_generated_confirmation"


def test_response_guard_allows_valid_action_id() -> None:
    result = ResponseGuard().validate_final_text("Confirmo: confirmo ejecutar act_1a2b3c4d")
    assert result.allowed


def test_response_guard_blocks_pseudo_tool_call() -> None:
    result = ResponseGuard().validate_final_text("<function_calls>foo</function_calls>")
    assert not result.allowed
    assert result.reason == "pseudo_tool_call_in_final_text"

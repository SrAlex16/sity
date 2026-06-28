"""Tests unitarios para build_ai_turn_prep y _should_synthesize.

build_ai_turn_prep requiere Session real, ProviderCallRunner, AIGateway y
PersonaDecision, lo que lo hace frágil de testear en aislamiento puro.
Está cubierto indirectamente por los tests de integración del chat
(test_chat_tool_registry_integration.sh) y por test_ai_orchestrator.py,
que ejercita el prep como parte del flujo completo.

Este módulo cubre _should_synthesize, que sí es un helper puro.
"""
from __future__ import annotations

from app.chat.ai_turn_prep import _should_synthesize


def test_should_synthesize_always_mode() -> None:
    """_should_synthesize devuelve True cuando voice_response_mode='always'."""
    assert _should_synthesize("always", "text") is True
    assert _should_synthesize("always", "voice") is True


def test_should_synthesize_never_mode() -> None:
    """_should_synthesize devuelve False cuando voice_response_mode='never'."""
    assert _should_synthesize("never", "text") is False
    assert _should_synthesize("never", "voice") is False


def test_should_synthesize_symmetric_voice_input() -> None:
    """_should_synthesize devuelve True en modo simétrico con input_mode='voice'."""
    assert _should_synthesize("symmetric", "voice") is True


def test_should_synthesize_symmetric_text_input() -> None:
    """_should_synthesize devuelve False en modo simétrico con input_mode='text'."""
    assert _should_synthesize("symmetric", "text") is False

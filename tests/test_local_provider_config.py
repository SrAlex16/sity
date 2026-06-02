"""Unit tests for local_provider_config.resolve_local_provider_model.

Verifies the three-way gate:
  1. local_ai_enabled must be True
  2. local_ai_provider must be "ollama" or "local"
  3. SITY_OLLAMA_MODEL must be set and non-empty
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.chat.local_provider_config import resolve_local_provider_model
from app.core.runtime_config import RuntimeConfig


def _cfg(**kwargs) -> RuntimeConfig:
    defaults: dict = dict(
        project_root=Path("/tmp"),
        platform="test",
        profile="test",
        ai_provider="mock",
        daily_token_hard_cap=False,
        local_only=False,
        local_ai_enabled=False,
        local_ai_provider="ollama",
    )
    defaults.update(kwargs)
    return RuntimeConfig(**defaults)


# ---------------------------------------------------------------------------
# Gate 1: local_ai_enabled=False → always None regardless of other settings
# ---------------------------------------------------------------------------

def test_local_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "gemma3:4b-it-qat")
    cfg = _cfg(local_ai_enabled=False, local_ai_provider="ollama")
    assert resolve_local_provider_model(cfg) is None


# ---------------------------------------------------------------------------
# Gate 2: provider not in {ollama, local} → None
# ---------------------------------------------------------------------------

def test_non_ollama_provider_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "gemma3:4b-it-qat")
    cfg = _cfg(local_ai_enabled=True, local_ai_provider="vllm")
    assert resolve_local_provider_model(cfg) is None


# ---------------------------------------------------------------------------
# Gate 3: SITY_OLLAMA_MODEL missing or empty → None
# ---------------------------------------------------------------------------

def test_local_enabled_ollama_missing_model_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SITY_OLLAMA_MODEL", raising=False)
    cfg = _cfg(local_ai_enabled=True, local_ai_provider="ollama")
    assert resolve_local_provider_model(cfg) is None


def test_local_enabled_ollama_blank_model_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "   ")
    cfg = _cfg(local_ai_enabled=True, local_ai_provider="ollama")
    assert resolve_local_provider_model(cfg) is None


# ---------------------------------------------------------------------------
# Happy path: all three gates pass → model name returned
# ---------------------------------------------------------------------------

def test_local_enabled_ollama_model_set_returns_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "gemma3:4b-it-qat")
    cfg = _cfg(local_ai_enabled=True, local_ai_provider="ollama")
    assert resolve_local_provider_model(cfg) == "gemma3:4b-it-qat"


def test_local_enabled_local_provider_also_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider_name='local' is an alias for ollama and must also be accepted."""
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "gemma3:4b-it-qat")
    cfg = _cfg(local_ai_enabled=True, local_ai_provider="local")
    assert resolve_local_provider_model(cfg) == "gemma3:4b-it-qat"


def test_model_name_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITY_OLLAMA_MODEL", "  gemma3:4b-it-qat  ")
    cfg = _cfg(local_ai_enabled=True, local_ai_provider="ollama")
    assert resolve_local_provider_model(cfg) == "gemma3:4b-it-qat"

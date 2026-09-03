"""Tests for app.chat.model_router — proposal lifecycle and expiry."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.chat.model_router import (
    LocalFlowSignal,
    ModelUpgradeProposal,
    clear_proposal,
    get_proposal,
    set_proposal,
)


def _fresh_proposal(**kwargs) -> ModelUpgradeProposal:
    defaults = dict(original_message="msg", strong_model="claude-sonnet-4-6", reason="test")
    defaults.update(kwargs)
    return ModelUpgradeProposal(**defaults)


def setup_function():
    clear_proposal()


def teardown_function():
    clear_proposal()


def test_set_and_get_proposal():
    p = _fresh_proposal()
    set_proposal(p)
    assert get_proposal() is p


def test_clear_proposal_removes_it():
    set_proposal(_fresh_proposal())
    clear_proposal()
    assert get_proposal() is None


def test_get_proposal_returns_none_when_empty():
    assert get_proposal() is None


def test_proposal_not_expired_initially():
    p = _fresh_proposal()
    assert not p.is_expired()


def test_proposal_is_expired_after_expires_at():
    p = _fresh_proposal()
    p = ModelUpgradeProposal(
        original_message=p.original_message,
        strong_model=p.strong_model,
        reason=p.reason,
        created_at=datetime.utcnow() - timedelta(minutes=10),
        expires_at=datetime.utcnow() - timedelta(minutes=5),
    )
    assert p.is_expired()


def test_get_proposal_returns_none_after_expiry():
    expired = ModelUpgradeProposal(
        original_message="msg",
        strong_model="claude-sonnet-4-6",
        reason="r",
        created_at=datetime.utcnow() - timedelta(minutes=10),
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    set_proposal(expired)
    assert get_proposal() is None


def test_set_proposal_replaces_previous():
    p1 = _fresh_proposal(original_message="first")
    p2 = _fresh_proposal(original_message="second")
    set_proposal(p1)
    set_proposal(p2)
    assert get_proposal().original_message == "second"


# ---------------------------------------------------------------------------
# Per-session accepted upgrade type tracking
# ---------------------------------------------------------------------------

from app.chat.model_router import (
    _categorize_upgrade_reason,
    get_accepted_upgrade_category,
    record_accepted_upgrade,
    _session_accepted_upgrade_types,
)


def _clear_accepted():
    _session_accepted_upgrade_types.clear()


def test_categorize_personality_reason():
    assert _categorize_upgrade_reason("ajuste de personalidad — sarcasmo y calidez") == "personality"
    assert _categorize_upgrade_reason("requiere cambio en parámetros del sistema") == "personality"
    assert _categorize_upgrade_reason("Esta tarea requiere ajustar los sliders de verbosidad") == "personality"


def test_categorize_code_reason():
    assert _categorize_upgrade_reason("análisis de código complejo con múltiple archivos") == "code"
    assert _categorize_upgrade_reason("refactor de arquitectura con trazas largas") == "code"


def test_categorize_other_reason():
    result = _categorize_upgrade_reason("Esta tarea específica requiere más contexto")
    assert len(result) <= 50


def test_get_accepted_returns_none_when_no_record():
    _clear_accepted()
    assert get_accepted_upgrade_category("session_x") is None


def test_record_and_get_accepted_upgrade():
    _clear_accepted()
    record_accepted_upgrade("session_a", "ajuste de sarcasmo y personalidad")
    assert get_accepted_upgrade_category("session_a") == "personality"


def test_accepted_upgrade_is_per_session():
    _clear_accepted()
    record_accepted_upgrade("session_a", "ajuste de personalidad")
    assert get_accepted_upgrade_category("session_b") is None


def test_local_flow_signal_default_skip_history_turns():
    sig = LocalFlowSignal(kind="model_upgrade_accepted", original_message="m", strong_model="s")
    assert sig.skip_history_turns == 3


def test_local_flow_signal_custom_skip_history_turns():
    sig = LocalFlowSignal(kind="model_upgrade_accepted", original_message="m", strong_model="s",
                          skip_history_turns=0)
    assert sig.skip_history_turns == 0

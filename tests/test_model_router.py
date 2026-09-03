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

from unittest.mock import patch

from app.chat.model_router import (
    _DEFAULT_UPGRADE_TTL_HOURS,
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


def test_default_ttl_is_4_hours():
    assert _DEFAULT_UPGRADE_TTL_HOURS == 4


def test_entry_not_expired_within_ttl():
    _clear_accepted()
    record_accepted_upgrade("session_ttl", "ajuste de personalidad", ttl_hours=4)
    # Immediately after recording it must still be valid
    assert get_accepted_upgrade_category("session_ttl") == "personality"


def test_entry_expires_after_ttl():
    _clear_accepted()
    record_accepted_upgrade("session_exp", "ajuste de personalidad", ttl_hours=2)
    # Simulate time passing beyond TTL
    from datetime import datetime, timedelta
    future = datetime.utcnow() + timedelta(hours=3)
    with patch("app.chat.model_router.datetime") as mock_dt:
        mock_dt.utcnow.return_value = future
        result = get_accepted_upgrade_category("session_exp")
    assert result is None


def test_entry_still_valid_just_before_expiry():
    _clear_accepted()
    record_accepted_upgrade("session_before", "ajuste de personalidad", ttl_hours=4)
    from datetime import datetime, timedelta
    just_before = datetime.utcnow() + timedelta(hours=3, minutes=59)
    with patch("app.chat.model_router.datetime") as mock_dt:
        mock_dt.utcnow.return_value = just_before
        result = get_accepted_upgrade_category("session_before")
    assert result == "personality"


def test_expired_entry_removed_from_dict():
    _clear_accepted()
    record_accepted_upgrade("session_clean", "personalidad", ttl_hours=1)
    from datetime import datetime, timedelta
    future = datetime.utcnow() + timedelta(hours=2)
    with patch("app.chat.model_router.datetime") as mock_dt:
        mock_dt.utcnow.return_value = future
        get_accepted_upgrade_category("session_clean")
    assert "session_clean" not in _session_accepted_upgrade_types


def test_custom_ttl_2h_respected():
    _clear_accepted()
    record_accepted_upgrade("session_2h", "personalidad", ttl_hours=2)
    from datetime import datetime, timedelta
    # Should be present at 1h59m
    just_before = datetime.utcnow() + timedelta(hours=1, minutes=59)
    with patch("app.chat.model_router.datetime") as mock_dt:
        mock_dt.utcnow.return_value = just_before
        assert get_accepted_upgrade_category("session_2h") == "personality"


def test_local_flow_signal_default_skip_history_turns():
    sig = LocalFlowSignal(kind="model_upgrade_accepted", original_message="m", strong_model="s")
    assert sig.skip_history_turns == 3


def test_local_flow_signal_custom_skip_history_turns():
    sig = LocalFlowSignal(kind="model_upgrade_accepted", original_message="m", strong_model="s",
                          skip_history_turns=0)
    assert sig.skip_history_turns == 0

"""Tests for app.chat.model_router — proposal lifecycle and expiry."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.chat.model_router import (
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

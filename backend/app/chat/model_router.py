"""model_router.py — in-memory state for the semi-automatic model upgrade proposal.

Haiku calls propose_model_upgrade when a task exceeds its capability.
routes_chat stores a ModelUpgradeProposal here. On the next turn local_flow
checks for a pending proposal and, if the user responds affirmatively, signals
routes_chat to re-run the original message with the strong model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class ModelUpgradeProposal:
    original_message: str
    strong_model: str
    reason: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(
        default_factory=lambda: datetime.utcnow() + timedelta(minutes=5)
    )

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


@dataclass
class LocalFlowSignal:
    """Non-HTTP signal returned from ChatLocalFlow.try_handle to routes_chat."""
    kind: str
    original_message: str
    strong_model: str


_pending_proposal: Optional[ModelUpgradeProposal] = None


def set_proposal(proposal: ModelUpgradeProposal) -> None:
    global _pending_proposal
    _pending_proposal = proposal


def get_proposal() -> Optional[ModelUpgradeProposal]:
    global _pending_proposal
    if _pending_proposal and _pending_proposal.is_expired():
        _pending_proposal = None
    return _pending_proposal


def clear_proposal() -> None:
    global _pending_proposal
    _pending_proposal = None

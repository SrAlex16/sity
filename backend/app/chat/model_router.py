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
    selected_tools: list[dict] = field(default_factory=list)
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
    selected_tools: list[dict] = field(default_factory=list)
    skip_history_turns: int = 3


_pending_proposal: Optional[ModelUpgradeProposal] = None

# Per-session record of already-accepted upgrade task categories, with expiry.
# Key: session_id. Value: (category, expires_at).
# TTL is configurable per user (default 4h); on expiry get_accepted_upgrade_category returns None.
_DEFAULT_UPGRADE_TTL_HOURS: int = 4


@dataclass
class _AcceptedUpgradeEntry:
    category: str
    expires_at: datetime


_session_accepted_upgrade_types: dict[str, _AcceptedUpgradeEntry] = {}


def _categorize_upgrade_reason(reason: str) -> str:
    """Map a free-text upgrade reason to a normalized task category for dedup."""
    r = reason.lower()
    if any(w in r for w in ("personalidad", "personality", "parámetr", "slider",
                             "sarcas", "verbos", "calidez", "rudeness", "warmth")):
        return "personality"
    if any(w in r for w in ("código", "code", "refactor", "debug", "arquitect",
                             "análisis de múltiple", "multiple files")):
        return "code"
    return reason[:50].lower().strip()


def get_accepted_upgrade_category(session_id: str) -> str | None:
    """Return the accepted task category for this session, or None if absent/expired."""
    entry = _session_accepted_upgrade_types.get(session_id)
    if entry is None:
        return None
    if datetime.utcnow() >= entry.expires_at:
        del _session_accepted_upgrade_types[session_id]
        return None
    return entry.category


def record_accepted_upgrade(session_id: str, reason: str, ttl_hours: int = _DEFAULT_UPGRADE_TTL_HOURS) -> None:
    """Record that the user accepted an upgrade for this task category."""
    _session_accepted_upgrade_types[session_id] = _AcceptedUpgradeEntry(
        category=_categorize_upgrade_reason(reason),
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )


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

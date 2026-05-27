"""routing_decision.py — structural chat routing decision.

Pure module: no DB, no side-effects, no NLP on the user message.
The decision is derived from already-selected tools and explicit flags.

Usage:
    from app.chat.routing_decision import build_chat_routing_decision

    decision = build_chat_routing_decision(
        message=request.message,
        selected_tools=selected_tools,
        local_ai_enabled=False,
    )
    # decision.mode: ProviderMode
    # decision.has_action_tools: bool
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Provider mode
# ---------------------------------------------------------------------------

class ProviderMode(str, Enum):
    """Which execution path to use for this chat turn.

    cloud_chat:
        Conversational turn — no action tools selected.
        Use cloud provider (Claude) in chat mode.

    cloud_tools:
        At least one action tool is selected (file, git, system, senses, etc.).
        Must use cloud provider: local models don't support tool calls.

    local_chat_candidate:
        Conversational turn AND local_ai_enabled=True.
        Eligible to route to a local LLM worker via SITY_OLLAMA_BASE_URL.
        Caller is responsible for checking worker availability before routing.
    """

    cloud_chat           = "cloud_chat"
    cloud_tools          = "cloud_tools"
    local_chat_candidate = "local_chat_candidate"


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChatRoutingDecision:
    """Immutable routing decision for a single chat turn."""

    mode: ProviderMode
    """Execution path selected for this turn."""

    has_action_tools: bool
    """True if selected_tools contains any tool beyond the conversational base."""

    local_ai_enabled: bool
    """Value of the local_ai_enabled flag passed by the caller."""

    reason: str
    """Human-readable explanation of the decision (for logging)."""


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

# Tools that belong to the conversational base and carry no side-effects.
# Any tool NOT in this set is considered an "action tool" that requires cloud.
_CONVERSATIONAL_TOOL_NAMES: frozenset[str] = frozenset({"no_action_required"})


def _has_action_tools(selected_tools: list[dict]) -> bool:
    """Return True if *selected_tools* contains any non-conversational tool.

    Purely structural — checks tool names, not the user message.
    """
    return any(
        t.get("name") not in _CONVERSATIONAL_TOOL_NAMES
        for t in selected_tools
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_chat_routing_decision(
    *,
    message: str,  # noqa: ARG001 — accepted for future use / logging context
    selected_tools: list[dict],
    local_ai_enabled: bool,
) -> ChatRoutingDecision:
    """Derive a ChatRoutingDecision from already-selected tools and flags.

    Args:
        message:        The raw user message. Not parsed for routing logic —
                        accepted for future extensibility and caller context.
        selected_tools: Output of select_toolset_for_message (or equivalent).
                        Routing is based solely on the tool list structure.
        local_ai_enabled: Whether a local LLM worker is configured and active.
                        Does NOT override the cloud_tools requirement.

    Priority:
        1. action tools present  → cloud_tools  (always, regardless of local flag)
        2. local_ai_enabled      → local_chat_candidate
        3. default               → cloud_chat
    """
    action_tools = _has_action_tools(selected_tools)

    if action_tools:
        return ChatRoutingDecision(
            mode=ProviderMode.cloud_tools,
            has_action_tools=True,
            local_ai_enabled=local_ai_enabled,
            reason="action tools selected — cloud provider required for tool calling",
        )

    if local_ai_enabled:
        return ChatRoutingDecision(
            mode=ProviderMode.local_chat_candidate,
            has_action_tools=False,
            local_ai_enabled=True,
            reason="conversational turn, local AI enabled — eligible for local worker",
        )

    return ChatRoutingDecision(
        mode=ProviderMode.cloud_chat,
        has_action_tools=False,
        local_ai_enabled=False,
        reason="conversational turn, local AI disabled — using cloud chat",
    )

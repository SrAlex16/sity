"""routing_decision.py — structural chat routing decision.

Pure module: no DB, no side-effects, no NLP on the user message.
The decision is derived from the ToolsetSelection metadata (activated_domains)
and explicit flags — never from len(tools) or keyword matching.

Usage:
    from app.chat.toolset_selector import select_toolset_with_metadata
    from app.chat.routing_decision import build_chat_routing_decision

    selection = select_toolset_with_metadata(request.message)
    decision  = build_chat_routing_decision(
        message=request.message,
        selection=selection,
        local_ai_enabled=False,
    )
    # decision.provider_mode: ProviderMode
    # decision.tools:         list[dict]  — same as selection.tools
    # decision.reason:        str
    # decision.local_ai_enabled: bool
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.chat.toolset_selector import ToolsetSelection


# ---------------------------------------------------------------------------
# Provider mode
# ---------------------------------------------------------------------------

class ProviderMode(str, Enum):
    """Which execution path to use for this chat turn.

    cloud_chat:
        Conversational turn — no action domains activated.
        Use cloud provider (Claude) in plain chat mode.

    cloud_tools:
        At least one action domain was activated (file, git, system, …).
        Must use cloud provider: local models don't support tool calling.

    local_chat_candidate:
        Conversational turn AND local_ai_enabled=True.
        Eligible to route to a local LLM worker via SITY_OLLAMA_BASE_URL.
        Caller is responsible for checking worker availability before routing.
    """

    cloud_chat            = "cloud_chat"
    cloud_tools           = "cloud_tools"
    local_chat_candidate  = "local_chat_candidate"


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChatRoutingDecision:
    """Immutable routing decision for a single chat turn."""

    provider_mode: ProviderMode
    """Execution path selected for this turn."""

    tools: list[dict]
    """Tool list for this turn (same as ToolsetSelection.tools)."""

    reason: str
    """Human-readable explanation of the decision (for logging)."""

    local_ai_enabled: bool
    """Value of the local_ai_enabled flag passed by the caller."""


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_chat_routing_decision(
    *,
    message: str,  # accepted for caller context / future extensibility; not parsed
    selection: ToolsetSelection,
    local_ai_enabled: bool,
) -> ChatRoutingDecision:
    """Derive a ChatRoutingDecision from a ToolsetSelection and flags.

    Args:
        message:          Raw user message — not used for routing logic.
        selection:        Output of select_toolset_with_metadata().
                          Routing uses *activated_domains*, never len(tools).
        local_ai_enabled: Whether a local LLM worker is configured and active.
                          Does NOT override the cloud_tools requirement.

    Priority:
        1. activated_domains non-empty → cloud_tools  (always, ignores local flag)
        2. local_ai_enabled             → local_chat_candidate
        3. default                      → cloud_chat
    """
    has_action_domains = bool(selection.activated_domains)

    if has_action_domains:
        domain_list = ", ".join(sorted(selection.activated_domains))
        return ChatRoutingDecision(
            provider_mode=ProviderMode.cloud_tools,
            tools=selection.tools,
            reason=f"action domains activated: {domain_list}",
            local_ai_enabled=local_ai_enabled,
        )

    if local_ai_enabled:
        return ChatRoutingDecision(
            provider_mode=ProviderMode.local_chat_candidate,
            tools=selection.tools,
            reason="conversational turn, local AI enabled — eligible for local worker",
            local_ai_enabled=True,
        )

    return ChatRoutingDecision(
        provider_mode=ProviderMode.cloud_chat,
        tools=selection.tools,
        reason="conversational turn, local AI disabled — using cloud chat",
        local_ai_enabled=False,
    )

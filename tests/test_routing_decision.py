"""Tests for app.chat.routing_decision and ToolsetSelection metadata.

Routing logic is based on ToolsetSelection.activated_domains — never on
len(tools) or message NLP.  Tests verify this invariant explicitly.
"""
from __future__ import annotations

import pytest

from app.chat.routing_decision import (
    ChatRoutingDecision,
    ProviderMode,
    build_chat_routing_decision,
)
from app.chat.toolset_selector import (
    ToolsetSelection,
    select_toolset_for_message,
    select_toolset_with_metadata,
)
from app.cortex.tool_schemas import (
    BASE_TOOLSET,
    FILE_AGENT_TOOLSET,
    GIT_TOOLSET,
    PENDING_ACTION_TOOLSET,
    SENSES_TOOLSET,
    SERVICE_CONTROL_TOOLSET,
    SYSTEM_TOOLSET,
)


# ---------------------------------------------------------------------------
# ToolsetSelection factory helpers
# ---------------------------------------------------------------------------

def _conversational_selection() -> ToolsetSelection:
    """Simulates a turn with only BASE_TOOLSET — no action domains."""
    return ToolsetSelection(
        tools=list(BASE_TOOLSET),
        activated_domains=frozenset(),
        reasons=[],
    )


def _action_selection(*domains: str) -> ToolsetSelection:
    """Simulates a turn where the given domains were activated."""
    tools = list(BASE_TOOLSET) + list(FILE_AGENT_TOOLSET)
    return ToolsetSelection(
        tools=tools,
        activated_domains=frozenset(domains),
        reasons=[f"test:{d}" for d in domains],
    )


def _decision(
    selection: ToolsetSelection,
    *,
    local_ai_enabled: bool = False,
    message: str = "test",
) -> ChatRoutingDecision:
    return build_chat_routing_decision(
        message=message,
        selection=selection,
        local_ai_enabled=local_ai_enabled,
    )


# ---------------------------------------------------------------------------
# ProviderMode constants
# ---------------------------------------------------------------------------

def test_provider_mode_cloud_chat_value() -> None:
    assert ProviderMode.cloud_chat.value == "cloud_chat"


def test_provider_mode_cloud_tools_value() -> None:
    assert ProviderMode.cloud_tools.value == "cloud_tools"


def test_provider_mode_local_chat_candidate_value() -> None:
    assert ProviderMode.local_chat_candidate.value == "local_chat_candidate"


def test_provider_mode_is_str_enum() -> None:
    assert isinstance(ProviderMode.cloud_chat, str)


# ---------------------------------------------------------------------------
# cloud_chat — conversational + local disabled
# ---------------------------------------------------------------------------

def test_cloud_chat_mode_conversational_local_disabled() -> None:
    d = _decision(_conversational_selection(), local_ai_enabled=False)
    assert d.provider_mode == ProviderMode.cloud_chat


def test_cloud_chat_local_ai_enabled_false() -> None:
    d = _decision(_conversational_selection(), local_ai_enabled=False)
    assert d.local_ai_enabled is False


def test_cloud_chat_reason_not_empty() -> None:
    assert _decision(_conversational_selection()).reason


def test_cloud_chat_tools_matches_selection() -> None:
    sel = _conversational_selection()
    d = _decision(sel)
    assert d.tools is sel.tools


# ---------------------------------------------------------------------------
# local_chat_candidate — conversational + local enabled
# ---------------------------------------------------------------------------

def test_local_chat_candidate_conversational_local_enabled() -> None:
    d = _decision(_conversational_selection(), local_ai_enabled=True)
    assert d.provider_mode == ProviderMode.local_chat_candidate


def test_local_chat_candidate_local_ai_enabled_true() -> None:
    assert _decision(_conversational_selection(), local_ai_enabled=True).local_ai_enabled is True


def test_local_chat_candidate_reason_not_empty() -> None:
    assert _decision(_conversational_selection(), local_ai_enabled=True).reason


# ---------------------------------------------------------------------------
# cloud_tools — action domains activated (local flag irrelevant)
# ---------------------------------------------------------------------------

def test_cloud_tools_when_file_domain_activated_local_disabled() -> None:
    d = _decision(_action_selection("file"), local_ai_enabled=False)
    assert d.provider_mode == ProviderMode.cloud_tools


def test_cloud_tools_when_file_domain_activated_local_enabled() -> None:
    """local_ai_enabled=True must NOT override cloud_tools when actions present."""
    d = _decision(_action_selection("file"), local_ai_enabled=True)
    assert d.provider_mode == ProviderMode.cloud_tools


def test_cloud_tools_when_git_domain_activated() -> None:
    d = _decision(_action_selection("git"))
    assert d.provider_mode == ProviderMode.cloud_tools


def test_cloud_tools_when_pending_action_domain_activated() -> None:
    d = _decision(_action_selection("pending_action"))
    assert d.provider_mode == ProviderMode.cloud_tools


def test_cloud_tools_when_multiple_domains_activated() -> None:
    d = _decision(_action_selection("file", "git"))
    assert d.provider_mode == ProviderMode.cloud_tools


def test_cloud_tools_reason_mentions_domain() -> None:
    d = _decision(_action_selection("file"))
    assert "file" in d.reason


def test_cloud_tools_tools_matches_selection() -> None:
    sel = _action_selection("file")
    d = _decision(sel)
    assert d.tools is sel.tools


# ---------------------------------------------------------------------------
# Routing uses activated_domains — NOT len(tools)
# ---------------------------------------------------------------------------

def test_base_toolset_routes_cloud_chat() -> None:
    """BASE_TOOLSET has no non-base tools (activated_domains empty) → cloud_chat.
    Proves routing ignores len(tools) and uses activated_domains instead.
    """
    # BASE_TOOLSET may contain base tools (e.g. no_action_required, search_conversation_history)
    # but none of them activate a non-base domain → routing stays cloud_chat.
    sel = _conversational_selection()
    assert sel.activated_domains == frozenset(), (
        f"Conversational message should activate no domains, got: {sel.activated_domains}"
    )
    d = _decision(sel, local_ai_enabled=False)
    assert d.provider_mode == ProviderMode.cloud_chat


def test_empty_activated_domains_always_conversational() -> None:
    """Any ToolsetSelection with empty activated_domains is conversational."""
    large_tool_list = list(BASE_TOOLSET) * 5  # many tools, but all same base tool
    sel = ToolsetSelection(
        tools=large_tool_list,
        activated_domains=frozenset(),
        reasons=[],
    )
    assert _decision(sel).provider_mode == ProviderMode.cloud_chat


def test_single_domain_enough_for_cloud_tools() -> None:
    """One activated domain → cloud_tools regardless of tool list size."""
    sel = ToolsetSelection(
        tools=list(BASE_TOOLSET),       # minimal tool list
        activated_domains=frozenset({"file"}),
        reasons=["test"],
    )
    assert _decision(sel).provider_mode == ProviderMode.cloud_tools


# ---------------------------------------------------------------------------
# ChatRoutingDecision is a frozen dataclass
# ---------------------------------------------------------------------------

def test_returns_chat_routing_decision_instance() -> None:
    assert isinstance(_decision(_conversational_selection()), ChatRoutingDecision)


def test_is_frozen_dataclass() -> None:
    d = _decision(_conversational_selection())
    with pytest.raises((AttributeError, TypeError)):
        d.provider_mode = ProviderMode.cloud_tools  # type: ignore[misc]


# ---------------------------------------------------------------------------
# select_toolset_with_metadata — ToolsetSelection fields
# ---------------------------------------------------------------------------

def test_conversational_message_empty_activated_domains() -> None:
    sel = select_toolset_with_metadata("hola")
    assert sel.activated_domains == frozenset()


def test_conversational_message_empty_reasons() -> None:
    sel = select_toolset_with_metadata("hola")
    assert sel.reasons == []


def test_file_path_activates_file_domain() -> None:
    sel = select_toolset_with_metadata("lee backend/app/main.py")
    assert "file" in sel.activated_domains


def test_file_path_reason_recorded() -> None:
    sel = select_toolset_with_metadata("lee backend/app/main.py")
    assert any("file" in r for r in sel.reasons)


def test_git_keyword_activates_git_domain() -> None:
    sel = select_toolset_with_metadata("muéstrame el git status")
    assert "git" in sel.activated_domains


def test_git_keyword_reason_recorded() -> None:
    sel = select_toolset_with_metadata("muéstrame el git status")
    assert any("git" in r for r in sel.reasons)


def test_explicit_tool_name_read_file_activates_file_domain() -> None:
    sel = select_toolset_with_metadata("usa read_file en config/")
    assert "file" in sel.activated_domains


def test_explicit_tool_name_reason_format() -> None:
    sel = select_toolset_with_metadata("usa read_file en config/")
    assert any(r.startswith("explicit_tool_name:") for r in sel.reasons)


def test_action_id_activates_pending_action_domain() -> None:
    sel = select_toolset_with_metadata("cancela act_a1b2c3d4")
    assert "pending_action" in sel.activated_domains


def test_action_id_reason_recorded() -> None:
    sel = select_toolset_with_metadata("cancela act_a1b2c3d4")
    assert "action_id_detected" in sel.reasons


def test_returns_toolset_selection_instance() -> None:
    assert isinstance(select_toolset_with_metadata("hola"), ToolsetSelection)


def test_tools_identical_to_select_toolset_for_message() -> None:
    """ToolsetSelection.tools must match select_toolset_for_message exactly."""
    msg = "usa list_directory en scripts/ y muéstrame el git status"
    assert select_toolset_with_metadata(msg).tools == select_toolset_for_message(msg)


def test_activated_domains_is_frozenset() -> None:
    sel = select_toolset_with_metadata("hola")
    assert isinstance(sel.activated_domains, frozenset)


def test_reasons_is_list() -> None:
    sel = select_toolset_with_metadata("hola")
    assert isinstance(sel.reasons, list)


# ---------------------------------------------------------------------------
# Integration: routing consistent with metadata
# ---------------------------------------------------------------------------

def test_routing_cloud_chat_consistent_with_metadata_conversational() -> None:
    sel = select_toolset_with_metadata("hola")
    d = build_chat_routing_decision(message="hola", selection=sel, local_ai_enabled=False)
    assert not sel.activated_domains
    assert d.provider_mode == ProviderMode.cloud_chat


def test_routing_cloud_tools_consistent_with_metadata_file() -> None:
    sel = select_toolset_with_metadata("lee backend/app/main.py")
    d = build_chat_routing_decision(
        message="lee backend/app/main.py", selection=sel, local_ai_enabled=False
    )
    assert "file" in sel.activated_domains
    assert d.provider_mode == ProviderMode.cloud_tools


def test_routing_local_candidate_consistent_with_metadata() -> None:
    sel = select_toolset_with_metadata("qué hora es")
    d = build_chat_routing_decision(
        message="qué hora es", selection=sel, local_ai_enabled=True
    )
    assert not sel.activated_domains
    assert d.provider_mode == ProviderMode.local_chat_candidate

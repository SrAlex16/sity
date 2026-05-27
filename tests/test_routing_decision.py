"""Tests for app.chat.routing_decision — pure, deterministic, no DB."""
from __future__ import annotations

import pytest

from app.chat.routing_decision import (
    ChatRoutingDecision,
    ProviderMode,
    _CONVERSATIONAL_TOOL_NAMES,
    _has_action_tools,
    build_chat_routing_decision,
)
from app.chat.toolset_selector import (
    ToolsetSelection,
    select_toolset_with_metadata,
)
from app.cortex.tool_schemas import (
    BASE_TOOLSET,
    FILE_AGENT_TOOLSET,
    GIT_TOOLSET,
    PENDING_ACTION_TOOLSET,
    SENSES_TOOLSET,
    SYSTEM_TOOLSET,
    SERVICE_CONTROL_TOOLSET,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CONVERSATIONAL_TOOLS = list(BASE_TOOLSET)          # [no_action_required]
_FILE_TOOLS = list(BASE_TOOLSET) + list(FILE_AGENT_TOOLSET)
_GIT_TOOLS  = list(BASE_TOOLSET) + list(GIT_TOOLSET)


def _decision(
    tools: list[dict],
    *,
    local_ai_enabled: bool = False,
    message: str = "test",
) -> ChatRoutingDecision:
    return build_chat_routing_decision(
        message=message,
        selected_tools=tools,
        local_ai_enabled=local_ai_enabled,
    )


# ---------------------------------------------------------------------------
# _CONVERSATIONAL_TOOL_NAMES constant
# ---------------------------------------------------------------------------

def test_conversational_tool_names_contains_no_action_required() -> None:
    assert "no_action_required" in _CONVERSATIONAL_TOOL_NAMES


# ---------------------------------------------------------------------------
# _has_action_tools helper
# ---------------------------------------------------------------------------

def test_has_action_tools_false_for_empty_list() -> None:
    assert _has_action_tools([]) is False


def test_has_action_tools_false_for_base_toolset() -> None:
    assert _has_action_tools(list(BASE_TOOLSET)) is False


def test_has_action_tools_false_for_only_no_action_required() -> None:
    assert _has_action_tools([{"name": "no_action_required"}]) is False


def test_has_action_tools_true_for_file_tools() -> None:
    assert _has_action_tools(_FILE_TOOLS) is True


def test_has_action_tools_true_for_git_tools() -> None:
    assert _has_action_tools(_GIT_TOOLS) is True


def test_has_action_tools_true_for_pending_action_toolset() -> None:
    tools = list(BASE_TOOLSET) + list(PENDING_ACTION_TOOLSET)
    assert _has_action_tools(tools) is True


def test_has_action_tools_true_for_system_tools() -> None:
    assert _has_action_tools(list(SYSTEM_TOOLSET)) is True


def test_has_action_tools_true_for_sense_tools() -> None:
    assert _has_action_tools(list(SENSES_TOOLSET)) is True


def test_has_action_tools_true_for_service_control() -> None:
    assert _has_action_tools(list(SERVICE_CONTROL_TOOLSET)) is True


# ---------------------------------------------------------------------------
# ProviderMode — conversational + local disabled → cloud_chat
# ---------------------------------------------------------------------------

def test_cloud_chat_mode_conversational_local_disabled() -> None:
    assert _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=False).mode == ProviderMode.cloud_chat


def test_cloud_chat_has_action_tools_false() -> None:
    assert _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=False).has_action_tools is False


def test_cloud_chat_local_ai_enabled_is_false() -> None:
    d = _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=False)
    assert d.local_ai_enabled is False


def test_cloud_chat_reason_not_empty() -> None:
    assert _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=False).reason


# ---------------------------------------------------------------------------
# ProviderMode — conversational + local enabled → local_chat_candidate
# ---------------------------------------------------------------------------

def test_local_chat_candidate_mode_conversational_local_enabled() -> None:
    assert _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=True).mode == ProviderMode.local_chat_candidate


def test_local_chat_candidate_has_action_tools_false() -> None:
    assert _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=True).has_action_tools is False


def test_local_chat_candidate_local_ai_enabled_is_true() -> None:
    assert _decision(_CONVERSATIONAL_TOOLS, local_ai_enabled=True).local_ai_enabled is True


# ---------------------------------------------------------------------------
# ProviderMode — action tools present → cloud_tools (regardless of local flag)
# ---------------------------------------------------------------------------

def test_cloud_tools_mode_file_tools_local_disabled() -> None:
    assert _decision(_FILE_TOOLS, local_ai_enabled=False).mode == ProviderMode.cloud_tools


def test_cloud_tools_mode_file_tools_local_enabled() -> None:
    """local_ai_enabled=True does NOT override cloud_tools requirement."""
    assert _decision(_FILE_TOOLS, local_ai_enabled=True).mode == ProviderMode.cloud_tools


def test_cloud_tools_mode_git_tools() -> None:
    assert _decision(_GIT_TOOLS).mode == ProviderMode.cloud_tools


def test_cloud_tools_mode_system_tools() -> None:
    assert _decision(list(SYSTEM_TOOLSET)).mode == ProviderMode.cloud_tools


def test_cloud_tools_mode_sense_tools() -> None:
    assert _decision(list(SENSES_TOOLSET)).mode == ProviderMode.cloud_tools


def test_cloud_tools_has_action_tools_true() -> None:
    assert _decision(_FILE_TOOLS).has_action_tools is True


def test_cloud_tools_reason_not_empty() -> None:
    assert _decision(_FILE_TOOLS).reason


# ---------------------------------------------------------------------------
# Return type is always ChatRoutingDecision
# ---------------------------------------------------------------------------

def test_returns_chat_routing_decision_instance() -> None:
    result = _decision(_CONVERSATIONAL_TOOLS)
    assert isinstance(result, ChatRoutingDecision)


def test_is_frozen_dataclass() -> None:
    d = _decision(_CONVERSATIONAL_TOOLS)
    with pytest.raises((AttributeError, TypeError)):
        d.mode = ProviderMode.cloud_tools  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty tool list — treated as conversational (no action tools)
# ---------------------------------------------------------------------------

def test_empty_tools_local_disabled_gives_cloud_chat() -> None:
    assert _decision([]).mode == ProviderMode.cloud_chat


def test_empty_tools_local_enabled_gives_local_chat_candidate() -> None:
    assert _decision([], local_ai_enabled=True).mode == ProviderMode.local_chat_candidate


# ---------------------------------------------------------------------------
# ProviderMode is a str Enum (serialisable)
# ---------------------------------------------------------------------------

def test_provider_mode_cloud_chat_value() -> None:
    assert ProviderMode.cloud_chat.value == "cloud_chat"


def test_provider_mode_cloud_tools_value() -> None:
    assert ProviderMode.cloud_tools.value == "cloud_tools"


def test_provider_mode_local_chat_candidate_value() -> None:
    assert ProviderMode.local_chat_candidate.value == "local_chat_candidate"


def test_provider_mode_is_str() -> None:
    assert isinstance(ProviderMode.cloud_chat, str)


# ---------------------------------------------------------------------------
# select_toolset_with_metadata
# ---------------------------------------------------------------------------

def test_select_toolset_with_metadata_returns_toolset_selection() -> None:
    result = select_toolset_with_metadata("hola")
    assert isinstance(result, ToolsetSelection)


def test_select_toolset_with_metadata_conversational_no_action_tools() -> None:
    result = select_toolset_with_metadata("hola")
    assert result.has_action_tools is False


def test_select_toolset_with_metadata_file_path_has_action_tools() -> None:
    result = select_toolset_with_metadata("lee backend/app/main.py")
    assert result.has_action_tools is True


def test_select_toolset_with_metadata_tools_matches_select_toolset() -> None:
    from app.chat.toolset_selector import select_toolset_for_message
    msg = "lee backend/app/main.py"
    assert select_toolset_with_metadata(msg).tools == select_toolset_for_message(msg)


def test_select_toolset_with_metadata_git_keyword_has_action_tools() -> None:
    result = select_toolset_with_metadata("muéstrame el git status")
    assert result.has_action_tools is True


# ---------------------------------------------------------------------------
# Integration: routing_decision consistent with select_toolset_with_metadata
# ---------------------------------------------------------------------------

def test_routing_consistent_with_toolset_metadata_conversational() -> None:
    sel = select_toolset_with_metadata("hola")
    d = build_chat_routing_decision(
        message="hola",
        selected_tools=sel.tools,
        local_ai_enabled=False,
    )
    assert d.has_action_tools == sel.has_action_tools
    assert d.mode == ProviderMode.cloud_chat


def test_routing_consistent_with_toolset_metadata_action() -> None:
    sel = select_toolset_with_metadata("lee backend/app/main.py")
    d = build_chat_routing_decision(
        message="lee backend/app/main.py",
        selected_tools=sel.tools,
        local_ai_enabled=False,
    )
    assert d.has_action_tools == sel.has_action_tools
    assert d.mode == ProviderMode.cloud_tools

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import app.tools.handlers  # noqa: F401
from app.cortex import tool_schemas
from app.tools.registry import registered_tool_names

BACKEND = Path(__file__).resolve().parents[1] / "backend"
TOOL_EXECUTOR_PATH = BACKEND / "app" / "core" / "tool_executor.py"

# Tools that appear in the schema but are intentionally NOT dispatched through
# the registry. Each entry must be explained.
SCHEMA_ONLY_TOOLS: set[str] = {
    # Intercepted in routes_chat.py before reaching the dispatcher: when the
    # model calls this tool the planner loop makes a second Claude call for
    # the conversational response. It never reaches ToolExecutor.
    "no_action_required",
    # Handled in routes_chat.py at the planner-response level (same as
    # no_action_required). Stores a ModelUpgradeProposal and returns a local
    # response; never reaches ToolExecutor.
    "propose_model_upgrade",
}


def collect_schema_tools() -> set[str]:
    tools: set[str] = set()
    for name, value in inspect.getmembers(tool_schemas):
        if name.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            tools.add(value["name"])
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    tools.add(item["name"])
    return tools


def test_no_dispatcher_branches_in_tool_executor() -> None:
    source = TOOL_EXECUTOR_PATH.read_text(encoding="utf-8")
    branches = re.findall(r'if\s+tool_name\s*==\s*["\']([^"\']+)["\']', source)
    assert not branches, (
        f"ToolExecutor still has dispatcher branches for tool_name: {branches}"
    )


def test_schema_tools_have_handlers() -> None:
    schema_tools = collect_schema_tools()
    handler_tools = registered_tool_names()
    missing = sorted((schema_tools - handler_tools) - SCHEMA_ONLY_TOOLS)
    assert not missing, f"Tools in schema without registry handler: {missing}"


def test_handlers_have_schema_tools() -> None:
    schema_tools = collect_schema_tools()
    handler_tools = registered_tool_names()
    extra = sorted(handler_tools - schema_tools)
    assert not extra, f"Registry handlers without exposed schema tool: {extra}"


def test_schema_and_registry_are_non_empty() -> None:
    schema_tools = collect_schema_tools()
    handler_tools = registered_tool_names()
    assert schema_tools, "No schema tools detected"
    assert handler_tools, "No registry handlers detected"

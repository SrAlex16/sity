#!/usr/bin/env python3
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import app.tools.handlers  # noqa: F401,E402
from app.cortex import tool_schemas  # noqa: E402
from app.tools.registry import registered_tool_names  # noqa: E402


TOOL_EXECUTOR_PATH = BACKEND / "app" / "core" / "tool_executor.py"

# Tools that appear in the schema but are intentionally NOT dispatched through
# the registry. Each entry must be explained.
SCHEMA_ONLY_TOOLS: set[str] = {
    # Intercepted in routes_chat.py before reaching the dispatcher: when the
    # model calls this tool the planner loop makes a second Claude call for
    # the conversational response. It never reaches ToolExecutor.
    "no_action_required",
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


def main() -> None:
    source = TOOL_EXECUTOR_PATH.read_text(encoding="utf-8")
    dispatcher_branches = re.findall(r'if\s+tool_name\s*==\s*["\']([^"\']+)["\']', source)

    assert not dispatcher_branches, (
        "ToolExecutor still has dispatcher branches for tool_name: "
        f"{dispatcher_branches}"
    )
    print("  [OK] no dispatcher branches in ToolExecutor")

    schema_tools = collect_schema_tools()
    handler_tools = registered_tool_names()

    missing_handlers = sorted((schema_tools - handler_tools) - SCHEMA_ONLY_TOOLS)
    extra_handlers = sorted(handler_tools - schema_tools)

    if missing_handlers:
        print(f"  [FAIL] tools in schema without handler: {missing_handlers}")
    if extra_handlers:
        print(f"  [FAIL] handlers without schema tool: {extra_handlers}")

    assert not missing_handlers, (
        f"Tools exposed in schema without registry handler: {missing_handlers}"
    )
    assert not extra_handlers, (
        f"Registry handlers without exposed schema tool: {extra_handlers}"
    )

    assert schema_tools, "No schema tools detected"
    assert handler_tools, "No registry handlers detected"

    print(
        f"tool registry completeness ok "
        f"({len(schema_tools)} schema tools, {len(handler_tools)} handlers)"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


from app.cortex import tool_schemas  # noqa: E402
from app.chat.toolset_selector import (  # noqa: E402
    message_mentions_action_id,
    select_structural_toolsets_for_message,
    select_toolset_for_message,
)


# Tools that appear in the schema but are intentionally NOT dispatched through
# the toolset selector (handled elsewhere in the request pipeline).
SELECTOR_EXEMPT_TOOLS: set[str] = {
    # Intercepted in routes_chat.py before reaching the tool loop.
    "no_action_required",
}


def schema_tool_names() -> set[str]:
    tools: set[str] = set()

    for value in vars(tool_schemas).values():
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            tools.add(value["name"])

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    tools.add(item["name"])

    return tools


def selected_tool_names(message: str, *, structural: bool = False) -> set[str]:
    selector = (
        select_structural_toolsets_for_message
        if structural
        else select_toolset_for_message
    )
    return {
        str(tool.get("name", ""))
        for tool in selector(message)
        if tool.get("name")
    }


def assert_tool_name_detection_is_complete() -> None:
    """Every schema tool (except exempt ones) must appear in the structural
    selector when its name is mentioned verbatim in the message."""
    failures = []
    for tool_name in sorted(schema_tool_names() - SELECTOR_EXEMPT_TOOLS):
        message = f"usa la herramienta {tool_name}"
        found = selected_tool_names(message, structural=True)

        if tool_name not in found:
            failures.append((tool_name, sorted(found)))

    if failures:
        lines = [f"Structural selector missed {len(failures)} tool(s):"]
        for tool_name, found in failures:
            lines.append(f"  {tool_name!r} not in {found[:5]}...")
        raise AssertionError("\n".join(lines))


def main() -> None:
    assert_tool_name_detection_is_complete()
    print("[OK] every schema tool name is detected structurally")

    assert message_mentions_action_id("cancela act_1234abcd")
    assert not message_mentions_action_id("yo he descubierto que soy inmortal, tengo pruebas")
    print("[OK] action ID detection works")

    # Regression: casual message must not trigger specialized toolsets beyond BASE.
    # 'inmortal' contains 'ram' → original bug triggered SYSTEM_TOOLSET via substring.
    # BASE_TOOLSET is always included; what must NOT appear are tools from GIT,
    # SENSES, SYSTEM, SERVICE_CONTROL, etc.
    from app.cortex.tool_schemas import BASE_TOOLSET
    base_names = {t["name"] for t in BASE_TOOLSET}

    casual_all = selected_tool_names("yo he descubierto que soy inmortal, tengo pruebas")
    extra = casual_all - base_names
    assert not extra, (
        f"Casual message triggered specialized tools beyond BASE_TOOLSET: {sorted(extra)}"
    )
    print("[OK] casual message adds no tools beyond BASE_TOOLSET")

    print("\ntoolset selector local test ok")


if __name__ == "__main__":
    main()

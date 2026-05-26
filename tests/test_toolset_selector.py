from __future__ import annotations

import pytest

from app.cortex import tool_schemas
from app.cortex.tool_schemas import BASE_TOOLSET
from app.chat.toolset_selector import (
    message_mentions_action_id,
    select_structural_toolsets_for_message,
    select_toolset_for_message,
)

# Tools that are intentionally NOT dispatched through the toolset selector.
SELECTOR_EXEMPT_TOOLS: set[str] = {
    # Intercepted in routes_chat.py before reaching the tool loop.
    "no_action_required",
}

_FILE_TOOLS: set[str] = {
    "read_file",
    "list_directory",
    "write_file",
    "apply_text_patch",
    "apply_unified_diff",
    "apply_multi_file_unified_diff_plan",
    "list_file_changes",
    "find_latest_reversible_file_change",
    "rollback_latest_file_change",
    "rollback_file_change",
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


@pytest.mark.parametrize("tool_name", sorted(schema_tool_names() - SELECTOR_EXEMPT_TOOLS))
def test_structural_selector_detects_tool_by_name(tool_name: str) -> None:
    message = f"usa la herramienta {tool_name}"
    found = selected_tool_names(message, structural=True)
    assert tool_name in found, (
        f"Structural selector missed {tool_name!r}. Selected: {sorted(found)[:5]}"
    )


def test_action_id_detection_positive() -> None:
    assert message_mentions_action_id("cancela act_1234abcd")


def test_action_id_detection_negative() -> None:
    assert not message_mentions_action_id("yo he descubierto que soy inmortal, tengo pruebas")


def test_cancel_not_in_casual_message() -> None:
    found = selected_tool_names("yo he descubierto que soy inmortal, tengo pruebas")
    assert "cancel_pending_action" not in found


def test_cancel_triggered_by_action_id() -> None:
    found = selected_tool_names("cancela act_1234abcd")
    assert "cancel_pending_action" in found


def test_cancel_triggered_by_explicit_tool_name() -> None:
    found = selected_tool_names(
        "usa la herramienta cancel_pending_action para cancelar act_1234abcd"
    )
    assert "cancel_pending_action" in found


def test_casual_message_adds_no_tools_beyond_base() -> None:
    base_names = {t["name"] for t in BASE_TOOLSET}
    casual_all = selected_tool_names("yo he descubierto que soy inmortal, tengo pruebas")
    extra = casual_all - base_names
    assert not extra, f"Casual message triggered tools beyond BASE_TOOLSET: {sorted(extra)}"


def test_casual_esta_no_file_or_cancel_tools() -> None:
    casual_esta = selected_tool_names("estás ahí?")
    unexpected = casual_esta & (_FILE_TOOLS | {"cancel_pending_action"})
    assert not unexpected, (
        f"'estás ahí?' triggered unexpected tools: {sorted(unexpected)}"
    )


def test_explicit_file_tool_names_activate_file_agent() -> None:
    assert "read_file" in selected_tool_names("usa la herramienta read_file para leer README.md")
    assert "write_file" in selected_tool_names("usa la herramienta write_file")
    assert "list_directory" in selected_tool_names("usa la herramienta list_directory")


def test_file_path_in_message_activates_file_agent() -> None:
    assert "read_file" in selected_tool_names("¿qué hay en backend/app?")
    assert "read_file" in selected_tool_names("lee el archivo README.md")

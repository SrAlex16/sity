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
    # Injected in routes_chat.py conditionally (dataset_source == "debug_test").
    # Not part of the normal toolset selector flow.
    "read_own_trace",
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


# ---------------------------------------------------------------------------
# service_control — operational intent required (bug regression guard)
#
# Rule: bare technical nouns (backend, frontend, sistema, servicio, código)
# must NOT activate service_control domain without an operational verb or
# explicit service name.  Only action verbs (reinicia, arranca, detén, para)
# or explicit service names (sity-backend, systemctl, …) should trigger it.
# ---------------------------------------------------------------------------

_SERVICE_CONTROL_TOOLS: set[str] = {
    "start_service",
    "stop_service",
    "restart_service",
    "read_service_status",
}


def _has_service_control_tools(message: str) -> bool:
    return bool(selected_tool_names(message) & _SERVICE_CONTROL_TOOLS)


# Should NOT activate ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "voy a toquetear el backend",
    "el backend está raro",
    "mira que te follen, voy a toquetear el backend",
    "el frontend no carga",
    "tengo que mirar el frontend",
    "el backend está caído",
    "algo pasa con el servicio",
    "hay código raro en el backend",
    # NOTE: "el sistema va lento hoy" is NOT here because \bsistema\b in _SYSTEM_RE
    # activates SYSTEM_TOOLSET which also contains service control tools — that is a
    # separate pre-existing issue with toolset composition, not the _SERVICE_CONTROL_RE bug.
])
def test_bare_technical_nouns_do_not_activate_service_control(message: str) -> None:
    """Mentioning backend/frontend/servicio as nouns must not activate service_control.

    This guards specifically against \b(?:backend|frontend)\b having been in
    _SERVICE_CONTROL_RE (confirmed bug trc_019930f83cc1, 2026-05-27).
    """
    assert not _has_service_control_tools(message), (
        f"service_control tools activated for {message!r} — bare noun triggered cloud routing"
    )


# Should activate ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "reinicia sity-backend",
    "reinicia el servicio",
    "arranca sity-frontend",
    "detén el servicio",
    "detener el backend",
    "para el servidor",
    "systemctl restart sity-backend",
    "para el sity-test",
])
def test_operational_verb_activates_service_control(message: str) -> None:
    """Operational verbs or explicit service names must activate service_control."""
    assert _has_service_control_tools(message), (
        f"service_control tools NOT activated for {message!r} — operational verb missed"
    )


# Domain metadata ─────────────────────────────────────────────────────────────

def test_bare_backend_does_not_activate_service_control_domain() -> None:
    """select_toolset_with_metadata must not activate service_control domain for bare 'backend'."""
    from app.chat.toolset_selector import select_toolset_with_metadata
    sel = select_toolset_with_metadata("el backend está raro")
    assert "service_control" not in sel.activated_domains, (
        f"service_control domain activated for bare 'backend': reasons={sel.reasons}"
    )


def test_reinicia_activates_service_control_domain() -> None:
    """'reinicia' must activate service_control domain."""
    from app.chat.toolset_selector import select_toolset_with_metadata
    sel = select_toolset_with_metadata("reinicia sity-backend")
    assert "service_control" in sel.activated_domains

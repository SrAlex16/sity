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
    # Injected in routes_chat.py conditionally (model_router_enabled: true).
    # Handled at the planner-response level, never reaches the toolset selector.
    "propose_model_upgrade",
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


def selected_tool_names(message: str, *, structural: bool = False, is_admin: bool = False) -> set[str]:
    if structural:
        return {
            str(tool.get("name", ""))
            for tool in select_structural_toolsets_for_message(message)
            if tool.get("name")
        }
    return {
        str(tool.get("name", ""))
        for tool in select_toolset_for_message(message, is_admin=is_admin)
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
    assert "read_file" in selected_tool_names("usa la herramienta read_file para leer README.md", is_admin=True)
    assert "write_file" in selected_tool_names("usa la herramienta write_file", is_admin=True)
    assert "list_directory" in selected_tool_names("usa la herramienta list_directory", is_admin=True)


def test_file_path_in_message_activates_file_agent() -> None:
    assert "read_file" in selected_tool_names("¿qué hay en backend/app?", is_admin=True)
    assert "read_file" in selected_tool_names("lee el archivo README.md", is_admin=True)


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
    return bool(selected_tool_names(message, is_admin=True) & _SERVICE_CONTROL_TOOLS)


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
    """'reinicia' must activate service_control domain for admin."""
    from app.chat.toolset_selector import select_toolset_with_metadata
    sel = select_toolset_with_metadata("reinicia sity-backend", is_admin=True)
    assert "service_control" in sel.activated_domains


# ── Google tools always available ─────────────────────────────────────────────

def test_google_tools_available_without_keyword() -> None:
    """Google tools must be available even when the message contains no explicit
    keywords like 'agenda', 'correo' or 'drive'. The planner must always receive
    them so it can decide whether to use them based on natural phrasing."""
    from app.chat.toolset_selector import select_toolset_for_message
    tools = select_toolset_for_message("¿qué tengo hoy?")
    tool_names = {t["name"] for t in tools}
    assert "calendar_list_events" in tool_names
    assert "gmail_search" in tool_names
    assert "drive_search" in tool_names
    assert "calendar_create_event" in tool_names


def test_google_tools_available_for_any_message() -> None:
    """Google tools must be in the toolset for an unrelated conversational message."""
    from app.chat.toolset_selector import select_toolset_for_message
    tools = select_toolset_for_message("hola, ¿qué tal?")
    tool_names = {t["name"] for t in tools}
    assert "gmail_search" in tool_names
    assert "calendar_list_events" in tool_names


# ── Admin-only toolset gating (SEC-11/12) ──────────────────────────────────────

_GIT_TOOLS: set[str] = {"git_read_status", "git_read_log", "git_propose_action", "git_read_branches"}
_FILE_TOOLS_SET: set[str] = {"read_file", "write_file", "list_directory", "apply_text_patch"}


@pytest.mark.parametrize("message", [
    "haz un git pull",
    "commit con mensaje 'fix'",
    "git status",
    "muéstrame el diff",
])
def test_git_tools_blocked_for_non_admin(message: str) -> None:
    """Non-admin sessions must never receive GIT_TOOLSET tools."""
    names = selected_tool_names(message, is_admin=False)
    found = names & _GIT_TOOLS
    assert not found, f"Git tools {found} appeared for non-admin: {message!r}"


@pytest.mark.parametrize("message", [
    "haz un git pull",
    "commit con mensaje 'fix'",
    "git status",
])
def test_git_tools_available_for_admin(message: str) -> None:
    """Admin sessions must receive GIT_TOOLSET tools for git messages."""
    names = selected_tool_names(message, is_admin=True)
    found = names & _GIT_TOOLS
    assert found, f"No git tools for admin: {message!r}"


@pytest.mark.parametrize("message", [
    "lee el archivo backend/app/main.py",
    "¿qué hay en config/?",
    "usa la herramienta read_file",
])
def test_file_tools_blocked_for_non_admin(message: str) -> None:
    """Non-admin sessions must never receive FILE_AGENT_TOOLSET tools."""
    names = selected_tool_names(message, is_admin=False)
    found = names & _FILE_TOOLS_SET
    assert not found, f"File tools {found} appeared for non-admin: {message!r}"


@pytest.mark.parametrize("message", [
    "lee el archivo backend/app/main.py",
    "¿qué hay en config/?",
])
def test_file_tools_available_for_admin(message: str) -> None:
    """Admin sessions must receive FILE_AGENT_TOOLSET tools when file path detected."""
    names = selected_tool_names(message, is_admin=True)
    assert "read_file" in names, f"read_file not available for admin: {message!r}"


@pytest.mark.parametrize("message", [
    "reinicia sity-backend",
    "para el servicio",
    "arranca sity-frontend",
])
def test_service_control_tools_blocked_for_non_admin(message: str) -> None:
    """Non-admin sessions must never receive SERVICE_CONTROL_TOOLSET tools."""
    names = selected_tool_names(message, is_admin=False)
    found = names & _SERVICE_CONTROL_TOOLS
    assert not found, f"Service control tools {found} appeared for non-admin: {message!r}"


def test_admin_only_domains_absent_for_non_admin() -> None:
    """activated_domains must not include admin-only domains for non-admin sessions."""
    from app.chat.toolset_selector import select_toolset_with_metadata
    cases = [
        "git pull",
        "lee el archivo config/test.yaml",
        "reinicia sity-backend",
        "cuánta ram tiene el sistema",
        "dime el estado del sistema",
        "muéstrame los logs del backend",
        "dame los debug events",
    ]
    all_admin_domains = {"git", "file", "service_control", "system", "debug"}
    for message in cases:
        sel = select_toolset_with_metadata(message, is_admin=False)
        admin_found = sel.activated_domains & all_admin_domains
        assert not admin_found, (
            f"Admin-only domains {admin_found} in non-admin selection for {message!r}"
        )


def test_admin_only_domains_present_for_admin() -> None:
    """activated_domains must include admin-only domains for admin sessions."""
    from app.chat.toolset_selector import select_toolset_with_metadata
    sel = select_toolset_with_metadata("haz un git pull", is_admin=True)
    assert "git" in sel.activated_domains

    sel2 = select_toolset_with_metadata("lee el archivo config/test.yaml", is_admin=True)
    assert "file" in sel2.activated_domains

    sel3 = select_toolset_with_metadata("cuánta ram tiene el sistema", is_admin=True)
    assert "system" in sel3.activated_domains

    sel4 = select_toolset_with_metadata("muéstrame los logs del backend", is_admin=True)
    assert "debug" in sel4.activated_domains


# ---------------------------------------------------------------------------
# SYSTEM_TOOLSET — admin-only (SEC bug fix 2026-08-04)
# Exposes CPU/RAM/disk/processes and service control — must never reach Guest.
# ---------------------------------------------------------------------------

_SYSTEM_TOOLS: set[str] = {"read_system_status", "read_disk_usage", "read_processes"}


@pytest.mark.parametrize("message", [
    "cuánta ram tiene el sistema",
    "dime el estado del sistema",
    "cuánto disco queda",
    "qué procesos están corriendo",
    "muéstrame el estado de la raspberry",
])
def test_system_tools_blocked_for_non_admin(message: str) -> None:
    """Non-admin sessions must never receive SYSTEM_TOOLSET tools."""
    names = selected_tool_names(message, is_admin=False)
    found = names & _SYSTEM_TOOLS
    assert not found, f"System tools {found} appeared for non-admin: {message!r}"


@pytest.mark.parametrize("message", [
    "cuánta ram tiene el sistema",
    "dime el estado del sistema",
    "cuánto disco queda",
])
def test_system_tools_available_for_admin(message: str) -> None:
    """Admin sessions must receive SYSTEM_TOOLSET tools for system queries."""
    names = selected_tool_names(message, is_admin=True)
    found = names & _SYSTEM_TOOLS
    assert found, f"No system tools for admin: {message!r}"


# ---------------------------------------------------------------------------
# DEBUG_TOOLSET — admin-only (SEC bug fix 2026-08-04)
# Exposes internal traces and debug events — must never reach Guest.
# ---------------------------------------------------------------------------

_DEBUG_TOOLS: set[str] = {"read_recent_debug_events", "read_trace_events"}


@pytest.mark.parametrize("message", [
    "muéstrame los logs del backend",
    "dame los debug events",
    "qué errores hay en los logs",
    "muéstrame las trazas",
])
def test_debug_tools_blocked_for_non_admin(message: str) -> None:
    """Non-admin sessions must never receive DEBUG_TOOLSET tools."""
    names = selected_tool_names(message, is_admin=False)
    found = names & _DEBUG_TOOLS
    assert not found, f"Debug tools {found} appeared for non-admin: {message!r}"


@pytest.mark.parametrize("message", [
    "muéstrame los logs del backend",
    "dame los debug events",
])
def test_debug_tools_available_for_admin(message: str) -> None:
    """Admin sessions must receive DEBUG_TOOLSET tools for debug queries."""
    names = selected_tool_names(message, is_admin=True)
    found = names & _DEBUG_TOOLS
    assert found, f"No debug tools for admin: {message!r}"


# ---------------------------------------------------------------------------
# TIMERS_TOOLSET — keyword-activated (structural fix 2026-08-12)
# Moved from BASE_TOOLSET to TIMERS_TOOLSET: list_timers must NOT appear
# for generic messages even when session history contains timer context.
# ---------------------------------------------------------------------------

_TIMER_TOOLS: set[str] = {"set_timer", "set_alarm", "list_timers", "cancel_timer"}


def test_timer_tools_not_in_base_toolset() -> None:
    """Timer tools must not be in BASE_TOOLSET — they are gated by keyword."""
    base_names = {t["name"] for t in BASE_TOOLSET}
    found = base_names & _TIMER_TOOLS
    assert not found, f"Timer tools leaked into BASE_TOOLSET: {sorted(found)}"


@pytest.mark.parametrize("message", [
    "¿Cómo estamos ahora?",
    "cuéntame algo",
    "¿qué hay?",
    "estás ahí?",
    "¿cómo vas?",
    "¿qué pasa?",
])
def test_generic_messages_do_not_activate_timer_tools(message: str) -> None:
    """Regression: generic/ambiguous messages must never trigger list_timers.

    This is the exact pattern that caused the bug (trc_33d668065f91 / trc_8c1f888e764f):
    the model called list_timers for '¿Cómo estamos ahora?' because timer tools
    were always available in BASE_TOOLSET and session history contained timer context.
    """
    names = selected_tool_names(message)
    found = names & _TIMER_TOOLS
    assert not found, f"Timer tools appeared for generic message {message!r}: {sorted(found)}"


@pytest.mark.parametrize("message,expected_tool", [
    ("ponme un temporizador de 10 minutos", "set_timer"),
    ("avísame en 30 segundos", "set_timer"),
    ("¿tengo temporizadores activos?", "list_timers"),
    ("cancela el temporizador", "cancel_timer"),
    ("ponme una alarma para mañana", "set_alarm"),
    ("recuérdame mañana a las 9", "set_alarm"),
    ("¿cuántas alarmas tengo?", "list_timers"),
    ("cuenta atrás de 5 minutos", "set_timer"),
])
def test_timer_keywords_activate_timer_tools(message: str, expected_tool: str) -> None:
    """Explicit timer/alarm mentions must activate TIMERS_TOOLSET."""
    names = selected_tool_names(message)
    assert expected_tool in names, (
        f"Expected {expected_tool!r} for {message!r}, got: {sorted(names & _TIMER_TOOLS)}"
    )

from __future__ import annotations

from app.system.allowed_services import get_allowed_systemd_services
from app.cortex import tool_schemas


def test_service_schema_enum_matches_allowed_services() -> None:
    allowed = set(get_allowed_systemd_services())
    assert len(allowed) > 0, "get_allowed_systemd_services() must not be empty"

    schema_enum = set(
        tool_schemas._SERVICE_SCHEMA["properties"]["service_name"]["enum"]
    )
    assert schema_enum == allowed, (
        f"_SERVICE_SCHEMA.service_name.enum {schema_enum} != allowed {allowed}"
    )


def test_propose_action_tool_enum_matches_allowed_services() -> None:
    allowed = set(get_allowed_systemd_services())
    propose_enum = set(
        tool_schemas.SYSTEM_PROPOSE_ACTION_TOOL["input_schema"]["properties"][
            "service_name"
        ]["enum"]
    )
    assert propose_enum == allowed, (
        f"SYSTEM_PROPOSE_ACTION_TOOL.service_name.enum {propose_enum} != allowed {allowed}"
    )


def test_module_level_list_matches_allowed_services() -> None:
    allowed = set(get_allowed_systemd_services())
    assert set(tool_schemas._ALLOWED_SYSTEMD_SERVICES) == allowed, (
        "_ALLOWED_SYSTEMD_SERVICES in tool_schemas does not match get_allowed_systemd_services()"
    )

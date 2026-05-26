#!/usr/bin/env python3
"""
Verify that service_name enums in tool_schemas match get_allowed_systemd_services().

Checks:
  - _SERVICE_SCHEMA.service_name.enum == allowed services (restart/start/stop tools)
  - SYSTEM_PROPOSE_ACTION_TOOL.service_name.enum == allowed services
  - No hardcoded service literals in the dynamic enum lists
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def require(cond: bool, msg: str) -> None:
    assert cond, msg


def main() -> None:
    from app.system.allowed_services import get_allowed_systemd_services
    from app.cortex import tool_schemas

    allowed = set(get_allowed_systemd_services())
    require(len(allowed) > 0, "get_allowed_systemd_services() must not be empty")

    # --- _SERVICE_SCHEMA (shared by restart/start/stop) ---
    service_schema_enum = set(
        tool_schemas._SERVICE_SCHEMA["properties"]["service_name"]["enum"]
    )
    require(
        service_schema_enum == allowed,
        f"_SERVICE_SCHEMA.service_name.enum {service_schema_enum} != allowed {allowed}",
    )

    # --- SYSTEM_PROPOSE_ACTION_TOOL ---
    propose_enum = set(
        tool_schemas.SYSTEM_PROPOSE_ACTION_TOOL["input_schema"]["properties"][
            "service_name"
        ]["enum"]
    )
    require(
        propose_enum == allowed,
        f"SYSTEM_PROPOSE_ACTION_TOOL.service_name.enum {propose_enum} != allowed {allowed}",
    )

    # --- Confirm the module-level list matches too ---
    require(
        set(tool_schemas._ALLOWED_SYSTEMD_SERVICES) == allowed,
        "_ALLOWED_SYSTEMD_SERVICES in tool_schemas does not match get_allowed_systemd_services()",
    )

    print(f"service tool schemas ok — allowed services: {sorted(allowed)}")


if __name__ == "__main__":
    main()

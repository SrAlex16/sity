import json
from pathlib import Path
from typing import Any

import yaml

from app.system.system_reader import load_system_access_config


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_ACCESS_CONFIG = PROJECT_ROOT / "config" / "system_access.yaml"


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)


def list_allowed_services() -> dict[str, Any]:
    config = load_system_access_config()
    read_services = (
        config.get("system_access", {})
        .get("read", {})
        .get("allowed_services", [])
    )
    action_services = (
        config.get("system_access", {})
        .get("safe_actions", {})
        .get("allowed_services", [])
    )

    return {
        "ok": True,
        "read_allowed_services": read_services,
        "action_allowed_services": action_services,
    }


def execute_system_config_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    service_name = str(payload.get("service_name", "")).strip()

    if action not in {"add_allowed_service", "remove_allowed_service"}:
        return _error(f"Unsupported system config action: {action}")

    if not service_name:
        return _error("Missing service_name.")

    if not _is_safe_service_name(service_name):
        return _error(f"Invalid service name: {service_name}")

    config = load_system_access_config()

    system_access = config.setdefault("system_access", {})
    read = system_access.setdefault("read", {})
    safe_actions = system_access.setdefault("safe_actions", {})

    read_services = read.setdefault("allowed_services", [])
    action_services = safe_actions.setdefault("allowed_services", [])

    if action == "add_allowed_service":
        changed = False

        if service_name not in read_services:
            read_services.append(service_name)
            changed = True

        if service_name not in action_services:
            action_services.append(service_name)
            changed = True

        _write_config(config)

        return {
            "ok": True,
            "changed": changed,
            "message": f"{service_name} añadido a servicios permitidos.",
            "service_name": service_name,
            "action": action,
        }

    if action == "remove_allowed_service":
        old_read_len = len(read_services)
        old_action_len = len(action_services)

        read["allowed_services"] = [
            service for service in read_services if service != service_name
        ]
        safe_actions["allowed_services"] = [
            service for service in action_services if service != service_name
        ]

        changed = (
            len(read["allowed_services"]) != old_read_len
            or len(safe_actions["allowed_services"]) != old_action_len
        )

        _write_config(config)

        return {
            "ok": True,
            "changed": changed,
            "message": f"{service_name} eliminado de servicios permitidos.",
            "service_name": service_name,
            "action": action,
        }

    return _error(f"Unsupported system config action: {action}")


def _write_config(config: dict[str, Any]) -> None:
    with SYSTEM_ACCESS_CONFIG.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            config,
            file,
            allow_unicode=True,
            sort_keys=False,
        )


def _is_safe_service_name(service_name: str) -> bool:
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@_.-")
    return bool(service_name) and all(char in allowed_chars for char in service_name)


def _error(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "stderr": message,
        "stdout": "",
    }

import json
import subprocess
import time
from typing import Any

from app.system.allowed_services import get_allowed_systemd_services
from app.system.system_reader import run_read_command


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)


def is_allowed_service(service_name: str) -> bool:
    return service_name in get_allowed_systemd_services()


def wait_for_service_state(
    service_name: str,
    *,
    expected_states: set[str],
    timeout_seconds: int = 10,
    interval_seconds: float = 0.5,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = ""

    while time.monotonic() < deadline:
        status = run_read_command(
            ["systemctl", "is-active", service_name],
            timeout_seconds=5,
        )

        last_status = status.get("stdout", "").strip()

        if last_status in expected_states:
            return {
                "ok": True,
                "status": last_status,
            }

        time.sleep(interval_seconds)

    return {
        "ok": False,
        "status": last_status or "unknown",
    }


def execute_system_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()
    service_name = str(payload.get("service_name", "")).strip()

    if action not in {"start_service", "stop_service", "restart_service"}:
        return _error(f"Unsupported system action: {action}")

    if not service_name:
        return _error("Missing service_name.")

    if not is_allowed_service(service_name):
        return _error(f"Service is not allowed: {service_name}")

    verb = {
        "start_service": "start",
        "stop_service": "stop",
        "restart_service": "restart",
    }[action]

    if action == "restart_service" and service_name == "sity-backend":
        command = [
            "sudo",
            "/bin/sh",
            "-c",
            "sleep 1; systemctl restart sity-backend",
        ]

        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        return {
            "ok": True,
            "stdout": "Reinicio de sity-backend programado en segundo plano. El servicio debería volver en unos segundos.",
            "stderr": "",
            "command": command,
            "post_status": "scheduled",
            "post_status_ok": True,
        }

    result = run_read_command(
        ["sudo", "systemctl", verb, service_name],
        timeout_seconds=20,
    )

    if action in {"start_service", "restart_service"}:
        post = wait_for_service_state(
            service_name,
            expected_states={"active"},
            timeout_seconds=12,
        )

        result["post_status"] = post["status"]
        result["post_status_ok"] = post["ok"]

        if post["ok"]:
            result["ok"] = True
            if not result.get("stdout"):
                result["stdout"] = f"{service_name} está active tras {verb}."

    elif action == "stop_service":
        post = wait_for_service_state(
            service_name,
            expected_states={"inactive", "failed"},
            timeout_seconds=12,
        )

        result["post_status"] = post["status"]
        result["post_status_ok"] = post["ok"]

        if post["ok"]:
            result["ok"] = True
            if not result.get("stdout"):
                result["stdout"] = f"{service_name} está {post['status']} tras stop."

    return result


def _error(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "stdout": "",
        "stderr": message,
        "command": [],
    }

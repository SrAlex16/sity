import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_ACCESS_CONFIG = PROJECT_ROOT / "config" / "system_access.yaml"


def load_system_access_config() -> dict[str, Any]:
    if not SYSTEM_ACCESS_CONFIG.exists():
        return {}

    with SYSTEM_ACCESS_CONFIG.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def run_read_command(command: list[str], timeout_seconds: int = 5) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": f"Command timed out after {timeout_seconds}s",
            "command": command,
        }


def read_system_status() -> dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    boot_time = psutil.boot_time()

    return {
        "cpu_percent": cpu_percent,
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "used": memory.used,
            "percent": memory.percent,
        },
        "boot_time": boot_time,
    }


def read_disk_usage(path: str = "/") -> dict[str, Any]:
    usage = shutil.disk_usage(path)

    return {
        "path": path,
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round((usage.used / usage.total) * 100, 2) if usage.total else 0,
    }


def read_top_processes(limit: int = 10) -> dict[str, Any]:
    processes: list[dict[str, Any]] = []

    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            processes.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "username": info.get("username"),
                    "cpu_percent": info.get("cpu_percent") or 0,
                    "memory_percent": round(info.get("memory_percent") or 0, 2),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)

    return {
        "processes": processes[: max(1, min(limit, 50))]
    }


def read_service_status(service_name: str) -> dict[str, Any]:
    config = load_system_access_config()
    allowed = (
        config.get("system_access", {})
        .get("read", {})
        .get("allowed_services", [])
    )

    if service_name not in allowed:
        return {
            "ok": False,
            "service": service_name,
            "message": "Service is not in allowed_services.",
        }

    result = run_read_command(["systemctl", "is-active", service_name])

    return {
        "ok": result["ok"],
        "service": service_name,
        "active_state": result["stdout"],
        "stderr": result["stderr"],
    }


def is_allowed_path(path: Path) -> bool:
    config = load_system_access_config()
    allowed_paths = (
        config.get("system_access", {})
        .get("read", {})
        .get("allowed_paths", [])
    )

    resolved = path.expanduser().resolve()

    for allowed in allowed_paths:
        allowed_resolved = Path(allowed).expanduser().resolve()
        try:
            resolved.relative_to(allowed_resolved)
            return True
        except ValueError:
            continue

    return False


def list_allowed_directory(path: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()

    if not is_allowed_path(target):
        return {
            "ok": False,
            "path": str(target),
            "message": "Path is not allowed.",
            "entries": [],
        }

    if not target.exists() or not target.is_dir():
        return {
            "ok": False,
            "path": str(target),
            "message": "Path does not exist or is not a directory.",
            "entries": [],
        }

    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]:
        entries.append(
            {
                "name": item.name,
                "path": str(item),
                "type": "directory" if item.is_dir() else "file",
            }
        )

    return {
        "ok": True,
        "path": str(target),
        "entries": entries,
    }

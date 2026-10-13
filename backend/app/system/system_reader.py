import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SYSTEM_ACCESS_CONFIG = PROJECT_ROOT / "config" / "system_access.yaml"


def _resolve_config_path(path_str: str) -> Path:
    """Resolve a path from the YAML config.

    Absolute paths are returned as-is (after expanduser + resolve).
    Relative paths are resolved relative to the runtime project_root so the
    config remains portable across checkout locations.
    """
    p = Path(path_str)
    if p.is_absolute():
        return p.expanduser().resolve()
    from app.core.runtime_config import get_runtime_config  # lazy to avoid circular import
    return (get_runtime_config().project_root / p).resolve()


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
        allowed_resolved = _resolve_config_path(str(allowed))
        try:
            resolved.relative_to(allowed_resolved)
            return True
        except ValueError:
            continue

    return False


def collect_system_metrics() -> dict[str, Any]:
    """Full system snapshot for GET /debug/system-metrics."""
    # CPU
    cpu_pct = psutil.cpu_percent(interval=0.3)
    cpu_cores = psutil.cpu_count(logical=False) or 1
    cpu_threads = psutil.cpu_count(logical=True) or cpu_cores
    cpu_temp = 0.0
    try:
        r = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            cpu_temp = float(r.stdout.strip().split("=")[1].replace("'C", ""))
    except Exception:
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                first_sensor = next(iter(temps.values()))
                if first_sensor:
                    cpu_temp = first_sensor[0].current
        except Exception:
            pass

    # RAM
    mem = psutil.virtual_memory()

    # Net IO + local IP
    net_io = psutil.net_io_counters()
    local_ip = "127.0.0.1"
    iface_name = "eth0"
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            if iface == "lo":
                continue
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    local_ip = addr.address
                    iface_name = iface
                    break
            if local_ip != "127.0.0.1":
                break
    except Exception:
        pass

    # Disk IO + usage
    disk_io = psutil.disk_io_counters()
    disk_usage_root = shutil.disk_usage("/")

    # Power throttling via vcgencmd
    throttled_hex = "0x0"
    uv_now = uv_past = throttled_now = throttled_past = False
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            val_str = r.stdout.strip().split("=")[-1].strip()
            val = int(val_str, 16)
            throttled_hex = val_str
            uv_now       = bool(val & (1 << 0))
            throttled_now = bool(val & (1 << 2))
            uv_past       = bool(val & (1 << 16))
            throttled_past = bool(val & (1 << 18))
    except Exception:
        pass

    # Services
    _SERVICES = ["sity-backend", "caddy", "cloudflared", "homeassistant"]
    services: list[dict[str, str]] = []
    for svc in _SERVICES:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=2,
            )
            state = r.stdout.strip() or "unknown"
        except Exception:
            state = "unknown"
        services.append({"name": svc, "state": state})

    # Processes — top 30 by score (cpu*0.7 + ram*0.3)
    _SITY_NAMES = {"uvicorn", "python3", "caddy", "cloudflared", "homeassistant", "node"}
    procs: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            cpu = float(info.get("cpu_percent") or 0.0)
            ram = round(float(info.get("memory_percent") or 0.0), 2)
            procs.append({
                "pid": info["pid"],
                "name": info.get("name") or "",
                "state": info.get("status") or "unknown",
                "cpu": round(cpu, 1),
                "ram": ram,
                "_score": cpu * 0.7 + ram * 0.3,
                "sity": (info.get("name") or "").lower() in _SITY_NAMES,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    procs.sort(key=lambda p: p["_score"], reverse=True)
    procs = [{k: v for k, v in p.items() if k != "_score"} for p in procs[:30]]

    return {
        "cpu": {
            "load": cpu_pct,
            "temp": cpu_temp,
            "cores": cpu_cores,
            "threads": cpu_threads,
        },
        "ram": {
            "used": mem.used,
            "total": mem.total,
            "percent": mem.percent,
        },
        "net": {
            "iface": iface_name,
            "local_ip": local_ip,
            "bytes_sent": net_io.bytes_sent if net_io else 0,
            "bytes_recv": net_io.bytes_recv if net_io else 0,
        },
        "disk": {
            "read_bytes": disk_io.read_bytes if disk_io else 0,
            "write_bytes": disk_io.write_bytes if disk_io else 0,
            "used": disk_usage_root.used,
            "total": disk_usage_root.total,
            "percent": round(disk_usage_root.used / disk_usage_root.total * 100, 1)
            if disk_usage_root.total else 0,
        },
        "power": {
            "throttled_hex": throttled_hex,
            "undervoltage_now": uv_now,
            "throttled_now": throttled_now,
            "undervoltage_past": uv_past,
            "throttled_past": throttled_past,
        },
        "services": services,
        "processes": procs,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from app.trace.logger import write_log


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_DIR = PROJECT_ROOT / "captures" / "audio"
REAL_WEBCAM_MIC_DEVICE = "plughw:CARD=webcam,DEV=0"


def list_audio_devices() -> dict[str, Any]:
    try:
        arecord = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        arecord_output = arecord.stdout.strip()
        arecord_error = arecord.stderr.strip()
    except Exception as exc:
        arecord_output = ""
        arecord_error = str(exc)

    try:
        devices = subprocess.run(
            ["arecord", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        devices_output = devices.stdout.strip()
        devices_error = devices.stderr.strip()
    except Exception as exc:
        devices_output = ""
        devices_error = str(exc)

    try:
        sources = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sources_output = sources.stdout.strip()
        sources_error = sources.stderr.strip()
    except Exception as exc:
        sources_output = ""
        sources_error = str(exc)

    sources_count = len([l for l in sources_output.splitlines() if l.strip()]) if sources_output else 0
    write_log(
        level="INFO",
        module="senses",
        event="audio_devices_listed",
        payload={
            "sources_count": sources_count,
            "arecord_ok": not arecord_error,
            "pactl_ok": not sources_error,
        },
    )
    return {
        "ok": True,
        "arecord_output": arecord_output,
        "arecord_error": arecord_error,
        "devices_output": devices_output,
        "devices_error": devices_error,
        "sources_output": sources_output,
        "sources_error": sources_error,
        "recommended_input_device": REAL_WEBCAM_MIC_DEVICE,
        "notes": [
            "Loopback es virtual y forma parte del pipeline HDMI; no debe usarse como micrófono real.",
            "El micrófono real esperado es la Full HD webcam.",
        ],
    }


def record_audio_sample(
    *,
    duration_seconds: int = 3,
    device: str = REAL_WEBCAM_MIC_DEVICE,
    client_turn_id: str | None = None,
) -> dict[str, Any]:
    from app.core.cancellation import get_operation, set_process

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    duration_seconds = max(1, min(duration_seconds, 10))
    timestamp = int(time.time())
    output_path = CAPTURE_DIR / f"audio-{timestamp}.wav"

    if "loopback" in device.lower():
        write_log(
            level="WARN",
            module="senses",
            event="audio_capture_finished",
            payload={"ok": False, "reason": "loopback_device_refused", "device": device},
        )
        return {
            "ok": False,
            "command": [],
            "path": str(output_path),
            "stdout": "",
            "stderr": "No voy a grabar desde Loopback: es un dispositivo virtual del pipeline HDMI, no el micrófono real.",
        }

    command = [
        "arecord",
        "-D", device,
        "-d", str(duration_seconds),
        "-f", "cd",
        str(output_path),
    ]

    write_log(
        level="INFO",
        module="senses",
        event="audio_capture_started",
        payload={"device": device, "duration_seconds": duration_seconds},
    )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if client_turn_id:
            set_process(client_turn_id, process)

        stdout, stderr = process.communicate(timeout=duration_seconds + 5)
    except subprocess.TimeoutExpired:
        process.terminate()
        write_log(
            level="WARN",
            module="senses",
            event="audio_capture_finished",
            payload={"ok": False, "reason": "timeout", "device": device, "duration_seconds": duration_seconds},
        )
        return {
            "ok": False,
            "command": command,
            "path": str(output_path),
            "stdout": "",
            "stderr": f"arecord timed out after {duration_seconds + 5}s",
        }
    except FileNotFoundError:
        write_log(
            level="WARN",
            module="senses",
            event="audio_capture_finished",
            payload={"ok": False, "reason": "arecord_not_found"},
        )
        return {
            "ok": False,
            "command": command,
            "path": str(output_path),
            "stdout": "",
            "stderr": "arecord not found",
        }

    operation = get_operation(client_turn_id) if client_turn_id else None
    if operation and operation.cancelled:
        output_path.unlink(missing_ok=True)
        write_log(
            level="WARN",
            module="senses",
            event="audio_capture_finished",
            payload={"ok": False, "reason": "cancelled", "device": device},
        )
        return {
            "ok": False,
            "cancelled": True,
            "command": command,
            "path": str(output_path),
            "stdout": stdout.strip() if stdout else "",
            "stderr": "Grabación cancelada por el usuario.",
            "message": "Grabación cancelada por el usuario.",
        }

    ok = process.returncode == 0 and output_path.exists()
    write_log(
        level="INFO" if ok else "WARN",
        module="senses",
        event="audio_capture_finished",
        payload={
            "ok": ok,
            "device": device,
            "duration_seconds": duration_seconds,
            **({"file_size_bytes": output_path.stat().st_size} if ok
               else {"stderr": (stderr or "").strip()[:200]}),
        },
    )
    return {
        "ok": ok,
        "command": command,
        "path": str(output_path),
        "stdout": stdout.strip() if stdout else "",
        "stderr": stderr.strip() if stderr else "",
    }

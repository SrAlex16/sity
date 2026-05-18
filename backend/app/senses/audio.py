from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any


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
) -> dict[str, Any]:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    duration_seconds = max(1, min(duration_seconds, 10))
    timestamp = int(time.time())
    output_path = CAPTURE_DIR / f"audio-{timestamp}.wav"

    if "loopback" in device.lower():
        return {
            "ok": False,
            "command": [],
            "path": str(output_path),
            "stdout": "",
            "stderr": "No voy a grabar desde Loopback: es un dispositivo virtual del pipeline HDMI, no el micrófono real.",
        }

    command = [
        "arecord",
        "-D",
        device,
        "-d",
        str(duration_seconds),
        "-f",
        "cd",
        str(output_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=duration_seconds + 5,
    )

    return {
        "ok": result.returncode == 0 and output_path.exists(),
        "command": command,
        "path": str(output_path),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }

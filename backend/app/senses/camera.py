from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_DIR = PROJECT_ROOT / "captures" / "camera"


def list_camera_devices() -> dict[str, Any]:
    video_devices = sorted(str(path) for path in Path("/dev").glob("video*"))

    try:
        v4l2 = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        v4l2_output = v4l2.stdout.strip()
        v4l2_error = v4l2.stderr.strip()
    except Exception as exc:
        v4l2_output = ""
        v4l2_error = str(exc)

    return {
        "ok": True,
        "video_devices": video_devices,
        "v4l2_output": v4l2_output,
        "v4l2_error": v4l2_error,
    }


def capture_camera_snapshot(
    *,
    device: str = "/dev/video0",
    width: int = 1280,
    height: int = 720,
    skip_frames: int = 20,
    client_turn_id: str | None = None,
) -> dict[str, Any]:
    from app.core.cancellation import get_operation, set_process

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    width = max(320, min(width, 1920))
    height = max(240, min(height, 1080))
    skip_frames = max(0, min(skip_frames, 60))

    timestamp = int(time.time())
    output_path = CAPTURE_DIR / f"snapshot-{timestamp}.jpg"

    command = [
        "fswebcam",
        "-d", device,
        "-r", f"{width}x{height}",
        "--no-banner",
        "--skip", str(skip_frames),
        str(output_path),
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if client_turn_id:
            set_process(client_turn_id, process)

        try:
            stdout, stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "ok": False,
                "cancelled": False,
                "command": command,
                "path": str(output_path),
                "stdout": stdout.strip() if stdout else "",
                "stderr": "Timeout capturando imagen.",
            }

    except FileNotFoundError:
        return {
            "ok": False,
            "cancelled": False,
            "command": command,
            "path": str(output_path),
            "stdout": "",
            "stderr": "fswebcam not found",
        }

    operation = get_operation(client_turn_id) if client_turn_id else None
    if operation and operation.cancelled:
        output_path.unlink(missing_ok=True)
        return {
            "ok": False,
            "cancelled": True,
            "command": command,
            "path": str(output_path),
            "stdout": stdout.strip() if stdout else "",
            "stderr": "Captura cancelada por el usuario.",
            "message": "Captura cancelada por el usuario.",
        }

    return {
        "ok": process.returncode == 0 and output_path.exists(),
        "command": command,
        "path": str(output_path),
        "stdout": stdout.strip() if stdout else "",
        "stderr": stderr.strip() if stderr else "",
    }

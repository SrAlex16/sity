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
) -> dict[str, Any]:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    width = max(320, min(width, 1920))
    height = max(240, min(height, 1080))
    skip_frames = max(0, min(skip_frames, 60))

    timestamp = int(time.time())
    output_path = CAPTURE_DIR / f"snapshot-{timestamp}.jpg"

    command = [
        "fswebcam",
        "-d",
        device,
        "-r",
        f"{width}x{height}",
        "--no-banner",
        "--skip",
        str(skip_frames),
        str(output_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
    )

    return {
        "ok": result.returncode == 0 and output_path.exists(),
        "command": command,
        "path": str(output_path),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }

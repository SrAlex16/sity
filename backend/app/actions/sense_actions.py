import json
from typing import Any

from app.senses.audio import REAL_WEBCAM_MIC_DEVICE, record_audio_sample
from app.senses.camera import capture_camera_snapshot


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)


def execute_sense_action(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "capture_camera_snapshot":
        return capture_camera_snapshot(
            device=str(payload.get("device", "/dev/video0")),
            width=int(payload.get("width", 1280)),
            height=int(payload.get("height", 720)),
            skip_frames=int(payload.get("skip_frames", 20)),
        )

    if action == "record_audio_sample":
        return record_audio_sample(
            duration_seconds=int(payload.get("duration_seconds", 3)),
            device=str(payload.get("device", REAL_WEBCAM_MIC_DEVICE)),
        )

    return {
        "ok": False,
        "stdout": "",
        "stderr": f"Unsupported sense action: {action}",
        "command": [],
    }

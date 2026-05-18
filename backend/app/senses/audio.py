import subprocess
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURES_DIR = PROJECT_ROOT / "captures" / "audio"


def record_audio_sample(
    *,
    duration_seconds: int = 3,
    device: str = "plughw:CARD=webcam,DEV=0",
) -> dict[str, Any]:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    output_path = CAPTURES_DIR / "sample.wav"

    try:
        completed = subprocess.run(
            [
                "arecord",
                "-D", device,
                "-d", str(duration_seconds),
                "-f", "cd",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=duration_seconds + 5,
            check=False,
        )

        if completed.returncode != 0:
            return {
                "ok": False,
                "device": device,
                "duration_seconds": duration_seconds,
                "stderr": completed.stderr.strip(),
            }

        size = output_path.stat().st_size if output_path.exists() else 0

        return {
            "ok": True,
            "device": device,
            "duration_seconds": duration_seconds,
            "output_path": str(output_path),
            "size_bytes": size,
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "device": device,
            "duration_seconds": duration_seconds,
            "stderr": f"arecord timed out after {duration_seconds + 5}s",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "device": device,
            "duration_seconds": duration_seconds,
            "stderr": "arecord not found",
        }

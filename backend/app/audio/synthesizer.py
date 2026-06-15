"""Piper TTS wrapper with lazy model loading.

Piper is a native binary — no Python package required.
Install: https://github.com/rhasspy/piper/releases
Model: es_ES-sharvard-medium (.onnx + .onnx.json) under data/tts_models/
"""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.settings.config_loader import PROJECT_ROOT, load_default_config


@dataclass
class TtsConfig:
    piper_bin: str
    model_path: str
    speaker: str
    long_response_chars: int


_cfg_lock = threading.Lock()


def load_tts_config() -> TtsConfig:
    cfg = load_default_config()
    audio = cfg.get("audio", {})
    voice = str(audio.get("tts_voice", "es_ES-sharvard-medium"))
    models_dir = str(audio.get("tts_models_dir", "data/tts_models"))
    models_path = Path(models_dir)
    if not models_path.is_absolute():
        models_path = PROJECT_ROOT / models_path
    return TtsConfig(
        piper_bin=str(audio.get("tts_piper_bin", "piper")),
        model_path=str(models_path / f"{voice}.onnx"),
        speaker=str(audio.get("tts_voice_speaker", "female")),
        long_response_chars=int(audio.get("tts_long_response_chars", 500)),
    )


def synthesize_text(text: str, cfg: TtsConfig) -> bytes:
    """Synthesize text to WAV bytes using the piper binary.

    Raises RuntimeError if piper is not installed or model is missing.
    """
    model_path = Path(cfg.model_path)
    if not model_path.exists():
        raise RuntimeError(
            f"TTS model not found: {cfg.model_path}. "
            "Download .onnx and .onnx.json from "
            "https://huggingface.co/rhasspy/piper-voices"
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    t0 = time.monotonic()
    try:
        cmd = [
            cfg.piper_bin,
            "--model", cfg.model_path,
            "--output_file", wav_path,
        ]
        result = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"piper exited with code {result.returncode}: "
                f"{result.stderr.decode('utf-8', errors='replace')[:200]}"
            )
        duration_ms = int((time.monotonic() - t0) * 1000)
        audio_bytes = Path(wav_path).read_bytes()
    finally:
        try:
            Path(wav_path).unlink(missing_ok=True)
        except Exception:
            pass

    if not audio_bytes:
        raise RuntimeError("piper produced empty output")

    return audio_bytes

"""faster-whisper wrapper with lazy model loading."""
from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass

from app.settings.config_loader import load_default_config


@dataclass
class AudioConfig:
    stt_model: str
    stt_device: str
    stt_language: str


_model = None
_model_cfg: tuple[str, str] | None = None
_model_lock = threading.Lock()


def load_audio_config() -> AudioConfig:
    cfg = load_default_config()
    audio = cfg.get("audio", {})
    return AudioConfig(
        stt_model=str(audio.get("stt_model", "base")),
        stt_device=str(audio.get("stt_device", "cpu")),
        stt_language=str(audio.get("stt_language", "es")),
    )


def get_model(cfg: AudioConfig):
    """Return a cached WhisperModel, reloading if config changes."""
    global _model, _model_cfg
    key = (cfg.stt_model, cfg.stt_device)
    if _model is None or _model_cfg != key:
        with _model_lock:
            if _model is None or _model_cfg != key:
                from faster_whisper import WhisperModel  # lazy — avoids import cost at startup
                _model = WhisperModel(cfg.stt_model, device=cfg.stt_device, compute_type="int8")
                _model_cfg = key
    return _model


def transcribe_bytes(audio_bytes: bytes, cfg: AudioConfig) -> tuple[str, int]:
    """Transcribe raw audio bytes. Returns (transcript, duration_ms)."""
    model = get_model(cfg)
    t0 = time.monotonic()
    suffix = ".audio"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        segments, _ = model.transcribe(tmp.name, language=cfg.stt_language)
        transcript = " ".join(seg.text for seg in segments).strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    return transcript, duration_ms

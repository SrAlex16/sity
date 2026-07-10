"""faster-whisper wrapper with lazy model loading."""
from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass

from app.settings.config_loader import load_default_config
from app.trace.logger import write_log


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
                write_log(
                    level="INFO",
                    module="audio",
                    event="stt_model_loading",
                    payload={"model": cfg.stt_model, "device": cfg.stt_device},
                )
                try:
                    _model = WhisperModel(cfg.stt_model, device=cfg.stt_device, compute_type="int8")
                    _model_cfg = key
                    write_log(
                        level="INFO",
                        module="audio",
                        event="stt_model_loaded",
                        payload={"ok": True, "model": cfg.stt_model, "device": cfg.stt_device},
                    )
                except Exception as exc:
                    write_log(
                        level="WARN",
                        module="audio",
                        event="stt_model_loaded",
                        payload={"ok": False, "model": cfg.stt_model, "reason": str(exc)[:200]},
                    )
                    raise
    return _model


def transcribe_bytes(audio_bytes: bytes, cfg: AudioConfig) -> tuple[str, int]:
    """Transcribe raw audio bytes. Returns (transcript, duration_ms)."""
    model = get_model(cfg)
    write_log(
        level="INFO",
        module="audio",
        event="stt_transcription_started",
        payload={"audio_size_bytes": len(audio_bytes)},
    )
    t0 = time.monotonic()
    try:
        suffix = ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            segments, _ = model.transcribe(tmp.name, language=cfg.stt_language)
            transcript = " ".join(seg.text for seg in segments).strip()
        duration_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        write_log(
            level="WARN",
            module="audio",
            event="stt_transcription_finished",
            payload={"ok": False, "reason": str(exc)[:200],
                     "duration_ms": int((time.monotonic() - t0) * 1000)},
        )
        raise
    write_log(
        level="INFO",
        module="audio",
        event="stt_transcription_finished",
        payload={"ok": True, "transcript_len": len(transcript), "duration_ms": duration_ms},
    )
    return transcript, duration_ms

"""Audio endpoints — STT transcription and TTS synthesis."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.audio.synthesizer import load_tts_config, synthesize_text
from app.audio.transcriber import load_audio_config, transcribe_bytes
from app.settings.config_loader import PROJECT_ROOT, load_default_config
from app.trace.logger import write_log

router = APIRouter(prefix="/audio", tags=["audio"])

_TTS_TMP_DIR = PROJECT_ROOT / "backend" / "runtime" / "tts"
_TTS_PERSISTENT_DIR = PROJECT_ROOT / "data" / "audio"


class TranscribeResponse(BaseModel):
    transcript: str
    duration_ms: int


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe an audio file with faster-whisper.

    Accepts any format supported by ffmpeg (webm, ogg, wav, mp3, …).
    Returns the full transcript and wall-clock duration in milliseconds.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    cfg = load_audio_config()
    transcript, duration_ms = transcribe_bytes(audio_bytes, cfg)

    write_log(
        level="INFO",
        module="audio",
        event="transcribed",
        payload={
            "model": cfg.stt_model,
            "device": cfg.stt_device,
            "language": cfg.stt_language,
            "duration_ms": duration_ms,
            "chars": len(transcript),
        },
    )

    return TranscribeResponse(transcript=transcript, duration_ms=duration_ms)


class SynthesizeRequest(BaseModel):
    text: str


@router.post("/synthesize")
async def synthesize_audio(request: SynthesizeRequest):
    """Synthesize text to speech using Piper TTS.

    Returns WAV audio bytes. Returns 422 if the text exceeds tts_long_response_chars.
    Returns 503 if piper is not installed or the model file is missing.
    """
    cfg = load_tts_config()
    if len(request.text) > cfg.long_response_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El texto es demasiado largo para síntesis directa "
                f"({len(request.text)} chars > límite {cfg.long_response_chars}). "
                "Divide el texto en fragmentos o usa voice_long_response_action='split'."
            ),
        )

    try:
        audio_bytes = synthesize_text(request.text, cfg)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    write_log(
        level="INFO",
        module="audio",
        event="tts_synthesized",
        payload={"chars": len(request.text), "bytes": len(audio_bytes)},
    )

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="response.wav"'},
    )


@router.get("/tts/{filename}")
async def serve_tts_file(filename: str):
    """Serve a previously synthesized TTS audio file by filename."""
    # Sanitize: only allow simple alphanumeric + dash + underscore + dot
    safe = all(c.isalnum() or c in "-_." for c in filename)
    if not safe or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = _TTS_TMP_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="TTS file not found")

    return FileResponse(path, media_type="audio/wav", filename=filename)


def synthesize_to_tmp(text: str) -> str:
    """Synthesize text and save to a temp file. Returns the URL path /audio/tts/{filename}."""
    cfg = load_tts_config()
    audio_bytes = synthesize_text(text, cfg)
    _TTS_TMP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"tts_{uuid.uuid4().hex[:12]}.wav"
    (_TTS_TMP_DIR / filename).write_bytes(audio_bytes)
    return f"/audio/tts/{filename}"


def synthesize_to_persistent(text: str, *, trace_id: str = "") -> tuple[str, str]:
    """Synthesize text and save to persistent data/audio/. Returns (url_path, filename)."""
    cfg = load_tts_config()
    audio_bytes = synthesize_text(text, cfg)
    _TTS_PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe_tid = (trace_id or uuid.uuid4().hex)[:16].replace("/", "_")
    filename = f"tts_{ts}_{safe_tid}.wav"
    (_TTS_PERSISTENT_DIR / filename).write_bytes(audio_bytes)
    return f"/audio/stored/{filename}", filename


_SAFE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def _validate_filename(filename: str) -> bool:
    return bool(filename) and all(c in _SAFE_CHARS for c in filename) and ".." not in filename


@router.get("/stored/{filename}")
async def serve_stored_tts_file(filename: str):
    """Serve a persistently stored TTS audio file from data/audio/."""
    if not _validate_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = _TTS_PERSISTENT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(path, media_type="audio/wav", filename=filename)


class CleanupResponse(BaseModel):
    deleted: int
    kept: int


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_stored_audio():
    """Delete stored TTS files older than audio.cleanup_days from data/audio/."""
    cfg = load_default_config().get("audio", {})
    cleanup_days: int = int(cfg.get("cleanup_days", 7))
    cutoff = datetime.now(timezone.utc) - timedelta(days=cleanup_days)

    deleted = 0
    kept = 0
    if _TTS_PERSISTENT_DIR.exists():
        for f in _TTS_PERSISTENT_DIR.iterdir():
            if not f.is_file():
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink(missing_ok=True)
                deleted += 1
            else:
                kept += 1

    write_log(level="INFO", module="audio", event="cleanup_stored",
              payload={"deleted": deleted, "kept": kept, "cleanup_days": cleanup_days})
    return CleanupResponse(deleted=deleted, kept=kept)

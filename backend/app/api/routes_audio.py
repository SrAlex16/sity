"""Audio endpoints — STT transcription."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.audio.transcriber import load_audio_config, transcribe_bytes
from app.trace.logger import write_log

router = APIRouter(prefix="/audio", tags=["audio"])


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

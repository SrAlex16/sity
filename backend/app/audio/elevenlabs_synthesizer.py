"""ElevenLabs TTS client — returns MP3 bytes synchronously.

Uses httpx (already in requirements for Google integrations).
API key read from ELEVENLABS_API_KEY env var; never hardcoded.
Raises RuntimeError on missing key, HTTP error, or empty response.
"""
from __future__ import annotations

import os
import time

import httpx

from app.trace.logger import write_log

_EL_BASE = "https://api.elevenlabs.io/v1"
_TIMEOUT = 30.0


def synthesize_elevenlabs(text: str, voice_id: str) -> bytes:
    """Call ElevenLabs TTS API and return MP3 bytes."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")

    url = f"{_EL_BASE}/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    t0 = time.monotonic()
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        write_log(
            level="WARN",
            module="audio",
            event="elevenlabs_synthesis_failed",
            payload={"status": exc.response.status_code, "duration_ms": duration_ms},
        )
        raise RuntimeError(
            f"ElevenLabs API error {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        ) from exc
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        write_log(
            level="WARN",
            module="audio",
            event="elevenlabs_synthesis_failed",
            payload={"error": str(exc), "duration_ms": duration_ms},
        )
        raise RuntimeError(f"ElevenLabs request failed: {exc}") from exc

    duration_ms = int((time.monotonic() - t0) * 1000)
    audio_bytes = resp.content
    if not audio_bytes:
        write_log(
            level="WARN",
            module="audio",
            event="elevenlabs_synthesis_failed",
            payload={"reason": "empty_response", "duration_ms": duration_ms},
        )
        raise RuntimeError("ElevenLabs returned empty audio")

    write_log(
        level="INFO",
        module="audio",
        event="elevenlabs_synthesis_finished",
        payload={
            "ok": True,
            "chars": len(text),
            "audio_size_bytes": len(audio_bytes),
            "duration_ms": duration_ms,
        },
    )
    return audio_bytes

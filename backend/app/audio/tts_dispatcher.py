"""Central TTS dispatch — Piper (local) vs ElevenLabs (cloud).

Routing rules (applied in order):
  1. Guest session → always Piper
  2. tts_engine != "elevenlabs" → Piper
  3. ELEVENLABS_API_KEY missing → Piper (logged as warning)
  4. Daily char limit reached → Piper (logged as info)
  5. ElevenLabs call fails → Piper fallback (logged as warning)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from app.memory.models import DailyTtsUsage
from app.trace.logger import write_log


def _audio_dir() -> Path:
    from app.settings.config_loader import PROJECT_ROOT
    return PROJECT_ROOT / "data" / "audio"


def _tmp_dir() -> Path:
    from app.settings.config_loader import PROJECT_ROOT
    return PROJECT_ROOT / "backend" / "runtime" / "tts"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _check_and_update_char_limit(
    session: Session,
    session_id: str,
    n_chars: int,
    daily_limit: int,
) -> bool:
    """Return True if within limit and update counter; False if exceeded."""
    today = _today()
    row = session.get(DailyTtsUsage, session_id)
    if row is None:
        row = DailyTtsUsage(session_id=session_id, char_count=0, count_date=today)
        session.add(row)
    elif row.count_date != today:
        row.char_count = 0
        row.count_date = today

    if daily_limit > 0 and (row.char_count + n_chars) > daily_limit:
        return False

    row.char_count += n_chars
    session.commit()
    return True


def get_current_char_count(session: Session, session_id: str) -> int:
    """Return today's ElevenLabs char count for a session (0 if no row or date differs)."""
    today = _today()
    row = session.get(DailyTtsUsage, session_id)
    if row is None or row.count_date != today:
        return 0
    return row.char_count


def synthesize_fragment(
    text: str,
    *,
    session: Session,
    session_id: str,
    tts_engine: str,
    persist: bool,
    trace_id: str,
    voice_id: str,
    daily_limit: int,
) -> tuple[str, Optional[str]]:
    """Synthesize one text fragment and save to disk.

    Returns (url_path, filename_or_None).
    filename is non-None only when persist=True (file saved to data/audio/).
    """
    use_elevenlabs = (
        tts_engine == "elevenlabs"
        and not session_id.startswith("guest:")
    )

    if use_elevenlabs and not os.environ.get("ELEVENLABS_API_KEY"):
        write_log(
            level="WARN", module="audio", event="elevenlabs_no_key_fallback",
            trace_id=trace_id, payload={"session_id": session_id},
        )
        use_elevenlabs = False

    if use_elevenlabs:
        within = _check_and_update_char_limit(session, session_id, len(text), daily_limit)
        if not within:
            write_log(
                level="INFO", module="audio", event="elevenlabs_limit_fallback",
                trace_id=trace_id,
                payload={"session_id": session_id, "chars": len(text), "limit": daily_limit},
            )
            use_elevenlabs = False

    audio_bytes: bytes
    ext: str

    if use_elevenlabs:
        try:
            from app.audio.elevenlabs_synthesizer import synthesize_elevenlabs
            audio_bytes = synthesize_elevenlabs(text, voice_id)
            ext = "mp3"
        except RuntimeError as exc:
            write_log(
                level="WARN", module="audio", event="elevenlabs_error_fallback",
                trace_id=trace_id, payload={"error": str(exc)},
            )
            _piper_bytes, _ext = _piper_synthesize(text)
            audio_bytes = _piper_bytes
            ext = _ext
    else:
        audio_bytes, ext = _piper_synthesize(text)

    return _save(audio_bytes, ext, persist=persist, trace_id=trace_id)


def _piper_synthesize(text: str) -> tuple[bytes, str]:
    from app.audio.synthesizer import load_tts_config, synthesize_text
    cfg = load_tts_config()
    return synthesize_text(text, cfg), "wav"


def _save(
    audio_bytes: bytes,
    ext: str,
    *,
    persist: bool,
    trace_id: str,
) -> tuple[str, Optional[str]]:
    if persist:
        out_dir = _audio_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_tid = (trace_id or uuid.uuid4().hex)[:16].replace("/", "_")
        filename = f"tts_{ts}_{safe_tid}.{ext}"
        (out_dir / filename).write_bytes(audio_bytes)
        return f"/audio/stored/{filename}", filename
    else:
        tmp = _tmp_dir()
        tmp.mkdir(parents=True, exist_ok=True)
        filename = f"tts_{uuid.uuid4().hex[:12]}.{ext}"
        (tmp / filename).write_bytes(audio_bytes)
        return f"/audio/tts/{filename}", None

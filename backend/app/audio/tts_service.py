"""Centralized TTS synthesis for all Sity response paths.

Single entry point: maybe_attach_tts — used by ai_orchestrator (normal flow),
pending_action_runner (confirmed actions), and initiative/runner (proactive messages).
_clean_text_for_tts and _attach_tts_artifacts are re-exported for backward-compatible
test imports (previously lived in ai_orchestrator.py).
"""
from __future__ import annotations

import re
from typing import Optional

from sqlmodel import Session

from app.trace.logger import write_log


def _resolve_elevenlabs_voice_id(voice_ids: dict, language_override: str) -> str | None:
    """Return the ElevenLabs voice_id for this language, or None if not available.

    Maps full language codes to base keys: "en-US"/"en-GB" → "en", "ja" → "ja".
    "auto" and any language without an entry return None (use Piper instead).
    """
    if not language_override or language_override == "auto":
        return None
    base = language_override.split("-")[0]
    return voice_ids.get(base) or None


def _clean_text_for_tts(text: str) -> str:
    # Strip confirmation command (unpronounceable action ID + literal phrase in backticks)
    text = re.sub(
        r'Confirma con:\s*`confirmo ejecutar act_[a-fA-F0-9]{8}`',
        'Cuando quieras, dime que lo confirme.',
        text,
        flags=re.IGNORECASE,
    )
    # Replace URLs with a short spoken cue (trailing punctuation excluded from match)
    text = re.sub(r'https?://[^\s.,;:!?)<>\[\]]+', '(enlace)', text)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text.strip()


def _attach_tts_artifacts(
    *, result, text: str, voice_settings, trace_id: str,
    session=None, session_id: str = "",
    force_persist: bool = False,
    language_override: str = "auto",
) -> Optional[tuple[int, Optional[str]]]:
    """Synthesize TTS audio and attach as artifacts to result. Modifies result.artifacts in place.

    Returns (n_fragments, audio_filename) where audio_filename is the persistent file written to
    data/audio/ (or None if persistence is disabled). Returns None if synthesis was skipped/failed.
    """
    from pathlib import Path as _Path

    from app.api.schemas import ChatArtifact
    from app.audio.synthesizer import load_tts_config
    from app.audio.tts_dispatcher import synthesize_fragment
    from app.audio.tts_splitter import split_by_sentences
    from app.settings.config_loader import load_default_config

    cfg = load_tts_config()
    raw_audio_cfg = load_default_config().get("audio", {})
    persist_tts: bool = force_persist or bool(raw_audio_cfg.get("persist_tts", False))
    voice_ids: dict = raw_audio_cfg.get("elevenlabs_voice_ids", {})
    daily_limit: int = int(raw_audio_cfg.get("elevenlabs_daily_char_limit", 0))
    tts_engine: str = getattr(voice_settings, "tts_engine", "piper")

    resolved_voice_id = _resolve_elevenlabs_voice_id(voice_ids, language_override)
    if tts_engine == "elevenlabs" and resolved_voice_id is None:
        write_log(
            level="INFO", module="audio", event="elevenlabs_language_fallback",
            trace_id=trace_id,
            payload={"language_override": language_override, "session_id": session_id},
        )
        tts_engine = "piper"
    voice_id: str = resolved_voice_id or ""

    try:
        tts_text = _clean_text_for_tts(text)
        if len(tts_text) <= cfg.long_response_chars:
            fragments = [tts_text]
        elif voice_settings.voice_long_response_action == "split":
            fragments = split_by_sentences(tts_text, cfg.long_response_chars)
        else:
            write_log(level="INFO", module="audio", event="tts_skipped_long_response",
                      trace_id=trace_id, payload={"chars": len(text)})
            return None

        first_persistent_filename: Optional[str] = None
        artifact_index = 0
        for i, fragment in enumerate(fragments):
            if not fragment.strip():
                write_log(level="INFO", module="audio", event="tts_fragment_skipped",
                          trace_id=trace_id, payload={"fragment_index": i, "reason": "empty"})
                continue
            url, filename = synthesize_fragment(
                fragment,
                session=session,
                session_id=session_id,
                tts_engine=tts_engine,
                persist=persist_tts,
                trace_id=trace_id,
                voice_id=voice_id,
                daily_limit=daily_limit,
            )
            ext = _Path(url).suffix.lstrip(".") or "wav"
            mime = "audio/mpeg" if ext == "mp3" else "audio/wav"
            if persist_tts and filename:
                write_log(level="INFO", module="audio", event="tts_fragment_persisted",
                          trace_id=trace_id,
                          payload={"fragment_index": i, "filename": filename})
                if first_persistent_filename is None:
                    first_persistent_filename = filename
            result.artifacts.append(ChatArtifact(
                type="audio",
                url=url,
                filename=f"sity_response_{artifact_index + 1}.{ext}",
                mime_type=mime,
            ))
            artifact_index += 1

        write_log(level="INFO", module="audio", event="tts_attached",
                  trace_id=trace_id,
                  payload={"engine": tts_engine, "fragments": len(fragments),
                           "total_chars": len(text),
                           "first_persistent_filename": first_persistent_filename})
        return len(fragments), first_persistent_filename
    except Exception as exc:
        write_log(level="WARN", module="audio", event="tts_failed",
                  trace_id=trace_id, payload={"error": str(exc), "error_type": type(exc).__name__})
        return None


def maybe_attach_tts(
    *,
    text: str,
    session: Session,
    session_id: str,
    trace_id: str,
    result=None,
    voice_settings=None,
    force_persist: bool = False,
    language_override: str = "auto",
) -> Optional[tuple[int, Optional[str]]]:
    """Synthesize TTS for a Sity response if voice is enabled for this session.

    Designed for all response paths that don't have input_mode context (pending
    actions, initiative messages). Generates audio when voice_response_mode != 'never'.

    If voice_settings is provided it is used directly (no DB query). If result is
    provided, ChatArtifact objects are appended to result.artifacts in place.
    force_persist=True overrides the config persist_tts flag (required for initiative
    push notifications which always need a file on disk).

    Returns (n_fragments, audio_filename) or None if skipped/failed. Never raises.
    """
    try:
        if voice_settings is None:
            from app.settings.settings_service import SettingsService
            voice_settings = SettingsService(session).get_voice_settings(session_id=session_id)

        if voice_settings.voice_response_mode == "never":
            return None

        # Use a temporary result carrier when the caller has no response object
        if result is None:
            class _Carrier:
                artifacts: list = []
            result = _Carrier()

        return _attach_tts_artifacts(
            result=result,
            text=text,
            voice_settings=voice_settings,
            trace_id=trace_id,
            session=session,
            session_id=session_id,
            force_persist=force_persist,
            language_override=language_override,
        )
    except Exception as exc:
        try:
            write_log(level="WARN", module="audio", event="tts_error",
                      trace_id=str(trace_id), session_id=str(session_id),
                      payload={"error": str(exc)[:300]})
        except Exception:
            pass
        return None

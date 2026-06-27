"""Tests for TTS audio persistence: audio_filename DB field and /audio/cleanup endpoint."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.memory.db import engine
from app.memory.models import ChatMessage

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_wav() -> bytes:
    """Minimal valid WAV bytes (header only, no audio data)."""
    return b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


# ── audio_filename field persists correctly ───────────────────────────────────

def test_audio_filename_field_on_chatmessage(db_session: Session) -> None:
    """ChatMessage must accept and persist audio_filename."""
    from app.chat.chat_persistence import get_or_create_default_chat_session, DEFAULT_CHAT_SESSION_ID

    get_or_create_default_chat_session(db_session)
    msg = ChatMessage(
        session_id=DEFAULT_CHAT_SESSION_ID,
        role="sity",
        text="Respuesta de audio.",
        output_mode="voice",
        tts_fragments=1,
        audio_filename="tts_20260627T120000_abc123.wav",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.audio_filename == "tts_20260627T120000_abc123.wav"

    fetched = db_session.exec(
        select(ChatMessage).where(ChatMessage.audio_filename == "tts_20260627T120000_abc123.wav")
    ).first()
    assert fetched is not None
    assert fetched.audio_filename == "tts_20260627T120000_abc123.wav"


def test_audio_filename_defaults_to_none(db_session: Session) -> None:
    """Existing messages without audio are unaffected (audio_filename = None)."""
    from app.chat.chat_persistence import get_or_create_default_chat_session, DEFAULT_CHAT_SESSION_ID

    get_or_create_default_chat_session(db_session)
    msg = ChatMessage(
        session_id=DEFAULT_CHAT_SESSION_ID,
        role="sity",
        text="Solo texto.",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)

    assert msg.audio_filename is None


# ── /audio/stored/{filename} endpoint ────────────────────────────────────────

def test_serve_stored_file_returns_wav(tmp_path: Path) -> None:
    wav = _make_wav()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    filename = "tts_20260627T120000_test001.wav"
    (audio_dir / filename).write_bytes(wav)

    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        r = client.get(f"/audio/stored/{filename}")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")


def test_serve_stored_file_404_when_missing(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        r = client.get("/audio/stored/tts_nonexistent.wav")

    assert r.status_code == 404


def test_serve_stored_file_rejects_path_traversal(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        r = client.get("/audio/stored/../../etc/passwd")

    assert r.status_code in (400, 404, 422)


# ── /audio/cleanup endpoint ───────────────────────────────────────────────────

def test_cleanup_deletes_old_files(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    old_file = audio_dir / "tts_old.wav"
    new_file = audio_dir / "tts_new.wav"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")

    # Set old_file mtime to 10 days ago
    old_mtime = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    import os
    os.utime(old_file, (old_mtime, old_mtime))

    cfg = {"audio": {"cleanup_days": 7}}
    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        with patch("app.api.routes_audio.load_default_config", return_value=cfg):
            r = client.post("/audio/cleanup")

    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] == 1
    assert data["kept"] == 1
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_keeps_recent_files(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    recent = audio_dir / "tts_recent.wav"
    recent.write_bytes(b"data")

    cfg = {"audio": {"cleanup_days": 7}}
    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        with patch("app.api.routes_audio.load_default_config", return_value=cfg):
            r = client.post("/audio/cleanup")

    assert r.status_code == 200
    assert r.json()["deleted"] == 0
    assert recent.exists()


def test_cleanup_empty_dir_is_noop(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    cfg = {"audio": {"cleanup_days": 7}}
    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        with patch("app.api.routes_audio.load_default_config", return_value=cfg):
            r = client.post("/audio/cleanup")

    assert r.status_code == 200
    assert r.json() == {"deleted": 0, "kept": 0}


def test_cleanup_missing_dir_is_noop(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio_nonexistent"

    cfg = {"audio": {"cleanup_days": 7}}
    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        with patch("app.api.routes_audio.load_default_config", return_value=cfg):
            r = client.post("/audio/cleanup")

    assert r.status_code == 200
    assert r.json() == {"deleted": 0, "kept": 0}


# ── synthesize_to_persistent ──────────────────────────────────────────────────

def test_synthesize_to_persistent_creates_file_and_returns_url(tmp_path: Path) -> None:
    from app.api.routes_audio import synthesize_to_persistent
    from app.audio.synthesizer import TtsConfig

    fake_cfg = TtsConfig(
        piper_bin="/fake/piper",
        model_path="/fake/model.onnx",
        speaker_id=None,
        long_response_chars=500,
    )
    audio_dir = tmp_path / "audio"

    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        with patch("app.api.routes_audio.load_tts_config", return_value=fake_cfg):
            with patch("app.api.routes_audio.synthesize_text", return_value=b"FAKE_WAV"):
                url, filename = synthesize_to_persistent("Hola.", trace_id="trace_abc")

    assert url.startswith("/audio/stored/")
    assert filename.endswith(".wav")
    assert "trace_abc" in filename
    saved = audio_dir / filename
    assert saved.exists()
    assert saved.read_bytes() == b"FAKE_WAV"


def test_synthesize_to_persistent_filename_includes_timestamp(tmp_path: Path) -> None:
    from app.api.routes_audio import synthesize_to_persistent
    from app.audio.synthesizer import TtsConfig

    fake_cfg = TtsConfig(
        piper_bin="/fake/piper",
        model_path="/fake/model.onnx",
        speaker_id=None,
        long_response_chars=500,
    )
    audio_dir = tmp_path / "audio"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    with patch("app.api.routes_audio._TTS_PERSISTENT_DIR", audio_dir):
        with patch("app.api.routes_audio.load_tts_config", return_value=fake_cfg):
            with patch("app.api.routes_audio.synthesize_text", return_value=b"WAV"):
                _, filename = synthesize_to_persistent("texto", trace_id="tid")

    assert today in filename

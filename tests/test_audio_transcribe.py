"""Tests for POST /audio/transcribe.

Mocks transcribe_bytes so faster-whisper is never imported or called.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.audio.transcriber import AudioConfig

client = TestClient(app)

_FAKE_CFG = AudioConfig(stt_model="base", stt_device="cpu", stt_language="es")


def _mock_transcribe(audio_bytes: bytes, cfg: AudioConfig):
    return ("Hola mundo.", 250)


def test_transcribe_returns_transcript() -> None:
    with patch("app.api.routes_audio.transcribe_bytes", side_effect=_mock_transcribe):
        with patch("app.api.routes_audio.load_audio_config", return_value=_FAKE_CFG):
            r = client.post(
                "/audio/transcribe",
                files={"file": ("test.wav", b"fake-audio-bytes", "audio/wav")},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["transcript"] == "Hola mundo."
    assert data["duration_ms"] == 250


def test_transcribe_empty_file_returns_400() -> None:
    with patch("app.api.routes_audio.transcribe_bytes", side_effect=_mock_transcribe):
        with patch("app.api.routes_audio.load_audio_config", return_value=_FAKE_CFG):
            r = client.post(
                "/audio/transcribe",
                files={"file": ("empty.wav", b"", "audio/wav")},
            )
    assert r.status_code == 400


def test_transcribe_accepts_webm_content_type() -> None:
    with patch("app.api.routes_audio.transcribe_bytes", side_effect=_mock_transcribe):
        with patch("app.api.routes_audio.load_audio_config", return_value=_FAKE_CFG):
            r = client.post(
                "/audio/transcribe",
                files={"file": ("rec.webm", b"fake-bytes", "audio/webm")},
            )
    assert r.status_code == 200


def test_transcribe_passes_bytes_to_transcribe_bytes() -> None:
    captured: list[bytes] = []

    def _capture(audio_bytes: bytes, cfg: AudioConfig):
        captured.append(audio_bytes)
        return ("texto", 100)

    with patch("app.api.routes_audio.transcribe_bytes", side_effect=_capture):
        with patch("app.api.routes_audio.load_audio_config", return_value=_FAKE_CFG):
            client.post(
                "/audio/transcribe",
                files={"file": ("audio.ogg", b"my-audio-data", "audio/ogg")},
            )

    assert captured[0] == b"my-audio-data"


def test_transcribe_uses_config_language() -> None:
    cfg_calls: list[AudioConfig] = []

    def _capture(audio_bytes: bytes, cfg: AudioConfig):
        cfg_calls.append(cfg)
        return ("ok", 50)

    with patch("app.api.routes_audio.transcribe_bytes", side_effect=_capture):
        with patch("app.api.routes_audio.load_audio_config", return_value=_FAKE_CFG):
            client.post(
                "/audio/transcribe",
                files={"file": ("audio.ogg", b"data", "audio/ogg")},
            )

    assert cfg_calls[0].stt_language == "es"
    assert cfg_calls[0].stt_model == "base"


def test_transcribe_returns_empty_transcript_on_silence() -> None:
    with patch("app.api.routes_audio.transcribe_bytes", return_value=("", 80)):
        with patch("app.api.routes_audio.load_audio_config", return_value=_FAKE_CFG):
            r = client.post(
                "/audio/transcribe",
                files={"file": ("silence.wav", b"data", "audio/wav")},
            )
    assert r.status_code == 200
    assert r.json()["transcript"] == ""

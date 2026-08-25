"""Tests for _clean_text_for_tts URL + confirmation-command stripping.

1. TestCleanTextForTTS — unit tests on the pure cleaning function
2. test_maybe_attach_tts_pending_action_clean_text — integration: synthesize_fragment
   receives text without act_ ID; original raw text is untouched
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.audio.tts_service import _clean_text_for_tts


class TestCleanTextForTTS:
    def test_strips_https_url(self):
        raw = "Evento creado. Ver aquí: https://calendar.google.com/event/abc123"
        cleaned = _clean_text_for_tts(raw)
        assert "https://calendar.google.com" not in cleaned
        assert "(enlace)" in cleaned

    def test_strips_http_url(self):
        cleaned = _clean_text_for_tts("Ver en http://example.com/path?foo=bar")
        assert "http://example.com" not in cleaned
        assert "(enlace)" in cleaned

    def test_url_in_original_string_is_not_mutated(self):
        raw = "Evento creado. https://calendar.google.com/event/xyz"
        _cleaned = _clean_text_for_tts(raw)
        assert "https://calendar.google.com/event/xyz" in raw

    def test_strips_confirmation_command(self):
        raw = (
            "Acción pendiente creada: Crear evento\n\n"
            "Confirma con: `confirmo ejecutar act_ea9d67c0`"
        )
        cleaned = _clean_text_for_tts(raw)
        assert "act_ea9d67c0" not in cleaned
        assert "confirmo ejecutar" not in cleaned
        assert "confirme" in cleaned.lower()

    def test_confirmation_stripping_case_insensitive(self):
        raw = "CONFIRMA CON: `confirmo ejecutar act_AABBCCDD`"
        cleaned = _clean_text_for_tts(raw)
        assert "act_AABBCCDD" not in cleaned
        assert "confirmo ejecutar" not in cleaned

    def test_bold_still_stripped(self):
        cleaned = _clean_text_for_tts("**negrita** y texto normal")
        assert "**" not in cleaned
        assert "negrita" in cleaned

    def test_inline_code_non_confirmation_stripped_but_text_kept(self):
        """Inline code outside of a confirmation context keeps the inner text."""
        cleaned = _clean_text_for_tts("Usa `git status` para ver cambios")
        assert "`" not in cleaned
        assert "git status" in cleaned

    def test_heading_stripped(self):
        cleaned = _clean_text_for_tts("## Resumen\nTexto aquí")
        assert "##" not in cleaned
        assert "Resumen" in cleaned


def test_maybe_attach_tts_pending_action_clean_text():
    """synthesize_fragment receives text without act_ ID or raw confirmation phrase."""
    from app.audio.tts_service import maybe_attach_tts

    raw_text = (
        "Acción pendiente creada: Crear evento en Google Calendar\n\n"
        "Confirma con: `confirmo ejecutar act_ea9d67c0`"
    )
    received: list[str] = []

    def fake_synth(text, **kw):
        received.append(text)
        return ("/tmp/tts_out.wav", "tts_out.wav")

    voice_settings = MagicMock()
    voice_settings.voice_response_mode = "always"
    voice_settings.voice_long_response_action = "split"
    voice_settings.tts_engine = "piper"

    with (
        patch("app.audio.tts_dispatcher.synthesize_fragment", side_effect=fake_synth),
    ):
        result = maybe_attach_tts(
            text=raw_text,
            session=MagicMock(),
            session_id="user:1",
            trace_id="trc_clean_test",
            voice_settings=voice_settings,
        )

    assert result is not None, "Expected TTS to run (voice_response_mode='always')"
    assert len(received) >= 1, "synthesize_fragment was never called"
    synth_text = received[0]
    assert "act_ea9d67c0" not in synth_text, "act_ ID must not reach synthesizer"
    assert "confirmo ejecutar" not in synth_text, "Literal command must not reach synthesizer"
    # Original text unchanged
    assert "act_ea9d67c0" in raw_text


def test_maybe_attach_tts_url_not_in_synth_text():
    """synthesize_fragment receives text without the raw URL; original text still has it."""
    from app.audio.tts_service import maybe_attach_tts

    raw_text = "Evento creado. Puedes verlo en: https://calendar.google.com/event/abc123"
    received: list[str] = []

    def fake_synth(text, **kw):
        received.append(text)
        return ("/tmp/tts_url_out.wav", "tts_url_out.wav")

    voice_settings = MagicMock()
    voice_settings.voice_response_mode = "always"
    voice_settings.voice_long_response_action = "split"
    voice_settings.tts_engine = "piper"

    with patch("app.audio.tts_dispatcher.synthesize_fragment", side_effect=fake_synth):
        result = maybe_attach_tts(
            text=raw_text,
            session=MagicMock(),
            session_id="user:1",
            trace_id="trc_url_test",
            voice_settings=voice_settings,
        )

    assert result is not None
    assert len(received) >= 1
    synth_text = received[0]
    assert "https://calendar.google.com" not in synth_text
    assert "(enlace)" in synth_text
    # Original string untouched
    assert "https://calendar.google.com/event/abc123" in raw_text

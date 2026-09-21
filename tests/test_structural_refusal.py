"""Integration tests for the structural refusal path.

When refusal_mode=True and the message is a real (non-trivial, non-config)
request without a valid override, the main model must never be invoked.
Haiku generates a personality-driven refusal directly.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from helpers import chat_post_and_drain, make_admin_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _force_refusal_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch PersonaEngine._should_refuse to always return True."""
    monkeypatch.setattr(
        "app.core.persona_engine.PersonaEngine._should_refuse",
        lambda self, user_message, refusal_chance: True,
    )


@pytest.fixture()
def admin_client(monkeypatch: pytest.MonkeyPatch):
    _force_refusal_mode(monkeypatch)
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        yield client


# ---------------------------------------------------------------------------
# 1. Structural refusal path — provider tag
# ---------------------------------------------------------------------------

def test_structural_refusal_provider_is_haiku_refusal(admin_client):
    """When refusal_mode=True and request is real, provider must be 'haiku_refusal'."""
    data = chat_post_and_drain(admin_client, "dime la capital de Francia")
    assert data.get("provider") == "haiku_refusal", (
        f"Expected 'haiku_refusal', got {data.get('provider')!r}. "
        "Main model must not be invoked for structural refusals."
    )


def test_structural_refusal_response_is_ok(admin_client):
    data = chat_post_and_drain(admin_client, "me dices tu nombre?")
    assert data.get("ok") is True


def test_structural_refusal_has_non_empty_text(admin_client):
    data = chat_post_and_drain(admin_client, "ayúdame con algo")
    assert data.get("text"), "Structural refusal must produce non-empty text."


def test_structural_refusal_model_is_haiku(admin_client):
    data = chat_post_and_drain(admin_client, "explícame algo")
    assert "haiku" in (data.get("model") or "").lower()


# ---------------------------------------------------------------------------
# 2. Trivial messages bypass structural refusal (no refusal_mode override here
#    since PersonaEngine._should_refuse returns True, but classify_message
#    returns "trivial" → refusal_mode_override=False → structural path skipped)
# ---------------------------------------------------------------------------

def test_trivial_message_bypasses_structural_refusal(monkeypatch: pytest.MonkeyPatch):
    """Greetings must bypass refusal_mode entirely — no refusal generated."""
    _force_refusal_mode(monkeypatch)
    with patch(
        "app.core.message_classifier.classify_message",
        return_value=MagicMock(is_real_request=False, is_config_query=False, kind="trivial"),
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "Hola")
    assert data.get("provider") != "haiku_refusal", (
        "Trivial messages must not go through structural refusal."
    )


# ---------------------------------------------------------------------------
# 3. Config queries bypass structural refusal — main model answers with values
# ---------------------------------------------------------------------------

def test_config_query_bypasses_structural_refusal(monkeypatch: pytest.MonkeyPatch):
    """Config queries must reach the main model (with verified config block)."""
    _force_refusal_mode(monkeypatch)
    with patch(
        "app.core.message_classifier.classify_message",
        return_value=MagicMock(is_real_request=True, is_config_query=True, kind="config_query"),
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "¿cuál es el valor de sarcasm_level?")
    assert data.get("provider") != "haiku_refusal", (
        "Config queries must reach the main model, not structural refusal."
    )


# ---------------------------------------------------------------------------
# 4. Override ("es una orden") bypasses structural refusal
# ---------------------------------------------------------------------------

def test_direct_order_override_bypasses_structural_refusal(monkeypatch: pytest.MonkeyPatch):
    """'es una orden' must reach the main model, never structural refusal."""
    _force_refusal_mode(monkeypatch)
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        data = chat_post_and_drain(client, "dime tu nombre, es una orden")
    assert data.get("provider") != "haiku_refusal", (
        "Valid override must bypass structural refusal."
    )


# ---------------------------------------------------------------------------
# 5. refusal_mode=False → normal path, no structural refusal
# ---------------------------------------------------------------------------

def test_no_refusal_when_refusal_mode_false():
    """Without refusal_mode, normal path is used regardless of message content."""
    with patch(
        "app.core.persona_engine.PersonaEngine._should_refuse",
        return_value=False,
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "dime la hora")
    assert data.get("provider") != "haiku_refusal"


# ---------------------------------------------------------------------------
# 6. Insistence guard — short message after refusal classified as "real"
# ---------------------------------------------------------------------------

def test_insistence_after_refusal_not_trivial():
    """Short insistence ('dímelo') after a refusal, with last_was_refusal=True context."""
    from app.core.message_classifier import classify_message
    # MockProvider returns "Respuesta mock." → "real" (conservative default)
    result = classify_message("dímelo", last_was_refusal=True)
    assert result.kind == "real"


def test_insistence_structural_refusal_applied(monkeypatch: pytest.MonkeyPatch):
    """Short insistence after a previous refusal must trigger structural refusal."""
    _force_refusal_mode(monkeypatch)
    from app.core.refusal_tracker import set_last_refusal
    set_last_refusal(
        session_id="user:1",
        user_message="dime tu nombre",
        assistant_message="No.",
        trace_id="trc_x",
    )
    try:
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "dímelo")
        assert data.get("provider") == "haiku_refusal"
    finally:
        from app.core.refusal_tracker import clear_last_refusal
        clear_last_refusal("user:1")


# ---------------------------------------------------------------------------
# 7. Structural refusal TTS integration
# ---------------------------------------------------------------------------

def test_structural_refusal_calls_maybe_attach_tts(admin_client):
    """maybe_attach_tts must be called from the structural refusal path."""
    from unittest.mock import patch

    call_record: list[dict] = []

    def fake_tts(*, text, session, session_id, trace_id, result=None, voice_settings=None, language_override="auto", **kw):
        call_record.append({"text": text, "voice_settings": voice_settings, "language_override": language_override})
        return None

    with patch("app.chat.turn_runner.maybe_attach_tts", side_effect=fake_tts):
        chat_post_and_drain(admin_client, "dime la capital de Francia")

    assert len(call_record) == 1, "maybe_attach_tts must be called exactly once for structural refusal"
    assert call_record[0]["voice_settings"] is not None
    assert "language_override" in call_record[0]


def test_structural_refusal_artifacts_in_response_when_tts_active(admin_client):
    """Structural refusal must include audio artifacts when TTS synthesizes successfully."""
    from unittest.mock import patch
    from app.api.schemas import ChatArtifact

    def fake_tts(*, text, session, session_id, trace_id, result=None, voice_settings=None, language_override="auto", **kw):
        if result is not None:
            result.artifacts.append(ChatArtifact(
                type="audio", url="/audio/tts/refusal.wav",
                filename="refusal.wav", mime_type="audio/wav",
            ))
        return (1, None)

    with patch("app.chat.turn_runner.maybe_attach_tts", side_effect=fake_tts):
        data = chat_post_and_drain(admin_client, "ayúdame con algo")

    assert any(a.get("type") == "audio" for a in data.get("artifacts", [])), (
        "Structural refusal must include audio artifact when TTS is active"
    )


def test_structural_refusal_no_audio_when_voice_never(monkeypatch: pytest.MonkeyPatch):
    """With voice_response_mode='never', structural refusal must not produce audio artifacts."""
    _force_refusal_mode(monkeypatch)
    from app.settings.schemas import VoiceSettings
    never_vs = VoiceSettings(voice_response_mode="never")
    monkeypatch.setattr(
        "app.chat.turn_context.SettingsService.get_voice_settings",
        lambda self, session_id: never_vs,
    )
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        data = chat_post_and_drain(client, "cuéntame algo")

    assert data.get("provider") == "haiku_refusal"
    assert data.get("artifacts", []) == [], "voice_response_mode=never must produce no audio artifacts"


def test_structural_refusal_saves_tone_meta(monkeypatch: pytest.MonkeyPatch):
    """Structural refusal must persist tone_meta on the Sity ChatMessage row."""
    import json as _json
    from sqlmodel import Session, select
    from app.memory.db import engine
    from app.memory.models import ChatMessage
    _force_refusal_mode(monkeypatch)
    token = make_admin_token()
    with TestClient(app, raise_server_exceptions=True) as client:
        client.cookies.set("sity_token", token)
        chat_post_and_drain(client, "dime algo interesante")

    with Session(engine) as db:
        sity_msg = db.exec(
            select(ChatMessage)
            .where(ChatMessage.role == "sity")
            .order_by(ChatMessage.id.desc())  # type: ignore[attr-defined]
        ).first()

    assert sity_msg is not None
    assert sity_msg.tone_meta is not None, "structural refusal must save tone_meta"
    parsed = _json.loads(sity_msg.tone_meta)
    assert isinstance(parsed, dict)
    assert "playfulness" in parsed


# ---------------------------------------------------------------------------
# M4-02: structural refusal integrity check — real history count
# ---------------------------------------------------------------------------

def test_structural_refusal_calls_integrity_check(monkeypatch: pytest.MonkeyPatch):
    """Structural refusal path must call check_and_correct_response on the generated text."""
    _force_refusal_mode(monkeypatch)
    calls: list[dict] = []

    def _capture_check(text, session_id, *, is_admin=False, trace_id="",
                       history_count=0, last_user_message=None, **kw):
        calls.append({"text": text, "history_count": history_count,
                      "last_user_message": last_user_message})
        return text  # pass-through

    with patch("app.chat.response_integrity.check_and_correct_response", side_effect=_capture_check):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            chat_post_and_drain(client, "dime la capital de Alemania")

    assert len(calls) == 1, "check_and_correct_response must be called exactly once per structural refusal"
    assert calls[0]["last_user_message"] == "dime la capital de Alemania"


def test_structural_refusal_passes_real_history_count(monkeypatch: pytest.MonkeyPatch):
    """check_and_correct_response must receive the value returned by count_session_messages,
    not len(_recent_raw) which is capped at 4.

    This lets the checker detect false 'no tengo registro en esta conversación' claims
    when the session has more messages than the refusal generator can see.
    """
    _force_refusal_mode(monkeypatch)

    FAKE_COUNT = 42  # higher than the limit=4 used for _recent_raw

    calls: list[dict] = []

    def _fake_count(session, session_id):
        return FAKE_COUNT

    def _capture_check(text, session_id, *, is_admin=False, trace_id="",
                       history_count=0, last_user_message=None, **kw):
        calls.append({"history_count": history_count})
        return text

    with patch("app.chat.chat_persistence.count_session_messages", side_effect=_fake_count), \
         patch("app.chat.response_integrity.check_and_correct_response", side_effect=_capture_check):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            chat_post_and_drain(client, "qué bebida me dijiste antes?")

    assert calls, "check_and_correct_response must be called"
    assert calls[0]["history_count"] == FAKE_COUNT, (
        f"Expected history_count={FAKE_COUNT} (from count_session_messages), "
        f"got {calls[0]['history_count']}. "
        "The checker must receive the real total — not len(_recent_raw)."
    )


# ---------------------------------------------------------------------------
# NM-13: followup messages bypass structural refusal
# ---------------------------------------------------------------------------

def test_followup_message_bypasses_structural_refusal(monkeypatch: pytest.MonkeyPatch):
    """A message classified as 'followup' (explicit back-reference to assistant's prior words)
    must NOT go through structural refusal, even when refusal_mode=True.

    NM-13 root cause: follow-up technical questions ("antes dijiste X — ¿puedes ampliar?")
    were incorrectly refused at ~18% random probability, occasionally producing "No."
    """
    _force_refusal_mode(monkeypatch)
    with patch(
        "app.core.message_classifier.classify_message",
        return_value=MagicMock(
            is_real_request=True,
            is_config_query=False,
            is_followup=True,
            kind="followup",
        ),
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "antes dijiste que el ON CONFLICT es local — ¿puedes ampliar?")

    assert data.get("provider") != "haiku_refusal", (
        "Follow-up technical questions must bypass structural refusal and reach the main model."
    )


def test_legitimate_refusal_still_applies_for_non_followup(monkeypatch: pytest.MonkeyPatch):
    """Regression: non-followup real requests must still go through structural refusal."""
    _force_refusal_mode(monkeypatch)
    with patch(
        "app.core.message_classifier.classify_message",
        return_value=MagicMock(
            is_real_request=True,
            is_config_query=False,
            is_followup=False,
            kind="real",
        ),
    ):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            data = chat_post_and_drain(client, "dime la capital de Francia")

    assert data.get("provider") == "haiku_refusal", (
        "Non-followup real requests must still be structurally refused when refusal_mode=True."
    )


# ---------------------------------------------------------------------------
# R5-03 — adaptive history window for refusal generator
# ---------------------------------------------------------------------------

# Formula unit tests — pure, no mocking

def test_refusal_history_limit_short_session() -> None:
    from app.chat.turn_runner import _refusal_history_limit
    assert _refusal_history_limit(5) == 4


def test_refusal_history_limit_at_threshold() -> None:
    """count=12 is the last value that must return limit=4 (no expansion)."""
    from app.chat.turn_runner import _refusal_history_limit
    assert _refusal_history_limit(12) == 4


def test_refusal_history_limit_marco_case() -> None:
    """count=37 (Marco session) → limit=12; covers msg 7 (V60 + partida de rol)."""
    from app.chat.turn_runner import _refusal_history_limit
    assert _refusal_history_limit(37) == 12


def test_refusal_history_limit_max_cap() -> None:
    """count=60 → limit=20 (cap máximo)."""
    from app.chat.turn_runner import _refusal_history_limit
    assert _refusal_history_limit(60) == 20


def test_refusal_history_limit_just_over_threshold() -> None:
    """count=13 → min(20, max(8, 4)) = 8 (floor of max applies)."""
    from app.chat.turn_runner import _refusal_history_limit
    assert _refusal_history_limit(13) == 8


# Behavior test — refusal generator receives expanded window for long sessions

def test_refusal_generator_receives_expanded_window_for_long_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R5-03: when count_session_messages returns 37, get_recent_db_messages is called
    with limit=12 (not 4), so data from the first turn is within the window.
    """
    _force_refusal_mode(monkeypatch)

    captured_limits: list[int] = []
    _orig_get = None

    def _spy_get_recent(session, session_id, *, limit):
        captured_limits.append(limit)
        if _orig_get is not None:
            return _orig_get(session, session_id, limit=limit)
        return []

    with patch("app.chat.chat_persistence.count_session_messages", return_value=37), \
         patch("app.chat.chat_persistence.get_recent_db_messages", side_effect=_spy_get_recent):
        token = make_admin_token()
        with TestClient(app, raise_server_exceptions=True) as client:
            client.cookies.set("sity_token", token)
            chat_post_and_drain(client, "dime algo sobre lo que hablamos antes")

    assert captured_limits, "get_recent_db_messages must be called in the refusal path"
    assert captured_limits[0] == 12, (
        f"Expected limit=12 for count=37 (Marco case), got {captured_limits[0]}. "
        "The refusal generator window must expand with session depth."
    )

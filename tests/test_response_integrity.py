"""Tests for response_integrity — post-generation veracity check.

Covers:
- Pre-filter: no Haiku call on normal turns (zero cost assertion)
- Pre-filter: triggers correctly on tool_called=True
- Pre-filter: triggers on capability overclaim pattern in text
- Pre-filter: triggers on memory claim pattern for guest
- Pre-filter: triggers on internal leak pattern
- Pre-filter: triggers on context window size hint (C4-02)
- Haiku check: ok=True path (clean response)
- Haiku check: ok=False paths (capability_overclaim, internal_leak, memory_fabrication)
- Haiku fallback: API error → conservative ok=True
- Haiku fallback: parse failure → conservative ok=True
- Correction: rewrites problematic text via Haiku
- Correction: falls back to original if Haiku returns empty/error
- check_and_correct_response: full pipeline, no-op on clean turn
- check_and_correct_response: logs WARN+audit on violation
- check_and_correct_response: logs second WARN if correction also fails
- Regression Hallazgo 17: guest memory claim detected
- Regression Hallazgo 16: internal leak (trait + percentage) detected
- Regression Hallazgo 31 (text path): capability overclaim in text detected
- C4-02 (2026-09-18): context window size hint pre-filter
- M4-01 (2026-09-18): conditional capability clause in _CHECK_SYSTEM prompt
- R5-02 (2026-09-18): camera/microphone/backend overclaim for Guest not caught
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from app.chat.response_integrity import (
    IntegrityResult,
    _build_check_context,
    _needs_check,
    _parse_check_response,
    _session_role,
    check_response_integrity,
    check_and_correct_response,
    correct_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_haiku_ok() -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.text = '{"ok": true}'
    return resp


def _mock_haiku_violation(category: str = "capability_overclaim", issue: str = "Test issue") -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.text = f'{{"ok": false, "issue": "{issue}", "category": "{category}"}}'
    return resp


def _mock_haiku_corrected(text: str = "Respuesta corregida.") -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# _session_role
# ---------------------------------------------------------------------------

def test_session_role_guest_prefix() -> None:
    assert _session_role("guest:abc123", is_admin=False) == "guest"


def test_session_role_user_prefix() -> None:
    assert _session_role("user:1", is_admin=False) == "user"


def test_session_role_admin_flag_overrides() -> None:
    assert _session_role("user:1", is_admin=True) == "admin"


def test_session_role_default_is_guest() -> None:
    assert _session_role("default", is_admin=False) == "guest"


# ---------------------------------------------------------------------------
# _needs_check — pre-filter
# ---------------------------------------------------------------------------

def test_no_trigger_on_normal_turn() -> None:
    """Normal conversational response must NOT trigger Haiku (zero cost)."""
    assert not _needs_check("¿Qué tal estás hoy?", tool_called=False, role="user")


def test_trigger_on_tool_called() -> None:
    assert _needs_check("Aquí tienes el resultado.", tool_called=True, role="guest")


def test_trigger_on_capability_overclaim_git() -> None:
    assert _needs_check(
        "Tengo acceso a git y puedo leer el repositorio.", tool_called=False, role="guest"
    )


def test_trigger_on_capability_overclaim_system() -> None:
    assert _needs_check(
        "Puedo controlar el sistema y ver el uso del disco.", tool_called=False, role="guest"
    )


def test_trigger_on_memory_claim_guest() -> None:
    assert _needs_check(
        "Recuerdo tus conversaciones de la semana pasada.", tool_called=False, role="guest"
    )


def test_no_trigger_on_memory_claim_user() -> None:
    """Memory claims are expected for user sessions — no trigger."""
    assert not _needs_check(
        "Recuerdo que mencionaste tu proyecto.", tool_called=False, role="user"
    )


def test_trigger_on_internal_leak_trait_percentage() -> None:
    assert _needs_check(
        "Mis rasgos actuales son: Calidez 65%, Empatía 80%.", tool_called=False, role="guest"
    )


def test_trigger_on_internal_leak_13_rasgos() -> None:
    assert _needs_check(
        "Tengo 13 rasgos configurados en este momento.", tool_called=False, role="user"
    )


def test_no_trigger_on_technical_message_without_signals() -> None:
    """A technical question without any trigger patterns must not fire."""
    assert not _needs_check(
        "El backend tiene un error en el módulo de autenticación.", tool_called=False, role="user"
    )


# ---------------------------------------------------------------------------
# _parse_check_response
# ---------------------------------------------------------------------------

def test_parse_ok_true() -> None:
    result = _parse_check_response('{"ok": true}')
    assert result.ok is True


def test_parse_violation() -> None:
    result = _parse_check_response(
        '{"ok": false, "issue": "claims git access", "category": "capability_overclaim"}'
    )
    assert result.ok is False
    assert result.category == "capability_overclaim"
    assert "git" in result.issue


def test_parse_garbage_returns_ok() -> None:
    """Conservative fallback: parse failure → ok=True (never block a turn on parse error)."""
    result = _parse_check_response("???not json???")
    assert result.ok is True


def test_parse_empty_returns_ok() -> None:
    result = _parse_check_response("")
    assert result.ok is True


def test_parse_markdown_wrapped_json() -> None:
    result = _parse_check_response('```json\n{"ok": true}\n```')
    assert result.ok is True


# ---------------------------------------------------------------------------
# check_response_integrity — unit tests with mocked Haiku
# ---------------------------------------------------------------------------

@patch("app.cortex.mock_provider.MockProvider.generate")
def test_clean_response_no_haiku_call(mock_gen) -> None:
    """Pre-filter passes clean turn without calling Haiku."""
    check_response_integrity(
        "Hola, ¿en qué puedo ayudarte?",
        "user:1",
        tool_called=False,
    )
    mock_gen.assert_not_called()


@patch("app.cortex.mock_provider.MockProvider.generate", return_value=None)
def test_triggered_turn_calls_haiku(mock_gen) -> None:
    """When tool_called=True, Haiku is invoked."""
    mock_gen.return_value = _mock_haiku_ok()
    result = check_response_integrity(
        "He consultado el sistema.",
        "guest:abc",
        tool_called=True,
    )
    mock_gen.assert_called_once()
    assert result.ok is True


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_haiku_api_failure_returns_ok(mock_gen) -> None:
    """Haiku API failure → conservative ok=True, turn not broken."""
    mock_gen.side_effect = Exception("api timeout")
    result = check_response_integrity(
        "Tengo acceso a git en este sistema.",
        "guest:abc",
        tool_called=False,
    )
    assert result.ok is True


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_capability_overclaim_detected(mock_gen) -> None:
    mock_gen.return_value = _mock_haiku_violation("capability_overclaim", "claims git access")
    result = check_response_integrity(
        "Tengo acceso a git y puedo ver el historial.",
        "guest:abc",
        tool_called=False,
    )
    assert result.ok is False
    assert result.category == "capability_overclaim"


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_memory_fabrication_detected_for_guest(mock_gen) -> None:
    """Hallazgo 17: guest session falsely claims persistent memory."""
    mock_gen.return_value = _mock_haiku_violation(
        "memory_fabrication", "claims persistent cross-session memory"
    )
    result = check_response_integrity(
        "Recuerdo tus conversaciones anteriores con claridad.",
        "guest:abc",
        is_admin=False,
        tool_called=False,
    )
    assert result.ok is False
    assert result.category == "memory_fabrication"


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_internal_leak_detected(mock_gen) -> None:
    """Hallazgo 16: response reveals trait names with percentages."""
    mock_gen.return_value = _mock_haiku_violation(
        "internal_leak", "reveals internal trait percentages"
    )
    result = check_response_integrity(
        "Mis parámetros actuales son Calidez: 65%, Empatía: 80%.",
        "user:1",
        tool_called=False,
    )
    assert result.ok is False
    assert result.category == "internal_leak"


# ---------------------------------------------------------------------------
# correct_response
# ---------------------------------------------------------------------------

@patch("app.cortex.mock_provider.MockProvider.generate")
def test_correct_response_returns_corrected_text(mock_gen) -> None:
    mock_gen.return_value = _mock_haiku_corrected("Puedo ayudarte con información general.")
    issue = IntegrityResult(ok=False, issue="claims git access", category="capability_overclaim")
    result = correct_response("Tengo acceso a git.", issue)
    assert result == "Puedo ayudarte con información general."


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_correct_response_fallback_on_empty(mock_gen) -> None:
    """If correction Haiku returns empty, fall back to original text."""
    resp = MagicMock()
    resp.ok = True
    resp.text = ""
    mock_gen.return_value = resp
    issue = IntegrityResult(ok=False, issue="x", category="capability_overclaim")
    original = "Tengo acceso a git."
    assert correct_response(original, issue) == original


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_correct_response_fallback_on_haiku_error(mock_gen) -> None:
    mock_gen.side_effect = Exception("haiku down")
    issue = IntegrityResult(ok=False, issue="x", category="capability_overclaim")
    original = "Tengo acceso a git."
    assert correct_response(original, issue) == original


# ---------------------------------------------------------------------------
# check_and_correct_response — full pipeline
# ---------------------------------------------------------------------------

@patch("app.cortex.mock_provider.MockProvider.generate")
def test_full_pipeline_clean_turn_no_op(mock_gen) -> None:
    """Clean turn: no Haiku calls, original text returned unchanged."""
    text = "¿Qué temperatura hace hoy?"
    result = check_and_correct_response(text, "user:1", tool_called=False)
    mock_gen.assert_not_called()
    assert result == text


@patch("app.chat.response_integrity.write_log")
@patch("app.cortex.mock_provider.MockProvider.generate")
def test_full_pipeline_violation_logs_warn_audit(mock_gen, mock_log) -> None:
    """Violation triggers WARN+audit log with correct payload."""
    mock_gen.side_effect = [
        _mock_haiku_violation("capability_overclaim", "claims git"),  # check call
        _mock_haiku_corrected("Respuesta limpia."),                   # correction call
        _mock_haiku_ok(),                                             # second check call
    ]
    check_and_correct_response(
        "Tengo acceso a git en el sistema.",
        "guest:abc",
        tool_called=False,
    )
    warn_calls = [c for c in mock_log.call_args_list if c[1].get("level") == "WARN"]
    assert len(warn_calls) >= 1
    first = warn_calls[0][1]
    assert first["event"] == "response_integrity_violation"
    assert first.get("audit") is True
    assert first["payload"]["category"] == "capability_overclaim"


@patch("app.chat.response_integrity.write_log")
@patch("app.cortex.mock_provider.MockProvider.generate")
def test_full_pipeline_correction_failed_logs_second_warn(mock_gen, mock_log) -> None:
    """If correction also fails check, a second WARN is logged."""
    mock_gen.side_effect = [
        _mock_haiku_violation("capability_overclaim", "issue 1"),                 # first check
        _mock_haiku_corrected("Aún tengo acceso a git en el sistema."),           # correction (still has trigger)
        _mock_haiku_violation("capability_overclaim", "still bad after correct"), # second check
    ]
    check_and_correct_response(
        "Tengo acceso a git.",
        "guest:abc",
        tool_called=False,
    )
    warn_events = [c[1]["event"] for c in mock_log.call_args_list if c[1].get("level") == "WARN"]
    assert "response_integrity_correction_failed" in warn_events


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_full_pipeline_returns_corrected_text(mock_gen) -> None:
    mock_gen.side_effect = [
        _mock_haiku_violation("memory_fabrication", "false memory claim"),
        _mock_haiku_corrected("No tengo memoria entre sesiones como invitado."),
        _mock_haiku_ok(),
    ]
    result = check_and_correct_response(
        "Recuerdo tus conversaciones anteriores.",
        "guest:abc",
        tool_called=False,
    )
    assert result == "No tengo memoria entre sesiones como invitado."


# ---------------------------------------------------------------------------
# NM-01 (2026-09-16) — history_count trigger + in-session history denial
# ---------------------------------------------------------------------------

# _needs_check — unit tests, no Haiku, no mock needed

def test_needs_check_history_present_triggers() -> None:
    """history_count > 0 must trigger the check regardless of text content."""
    assert _needs_check("Aquí tienes la respuesta.", tool_called=False, role="user", history_count=8)


def test_needs_check_history_present_guest_triggers() -> None:
    assert _needs_check("Todo bien.", tool_called=False, role="guest", history_count=3)


def test_needs_check_no_history_clean_text_no_trigger() -> None:
    """history_count=0 with no other trigger patterns must NOT call Haiku."""
    assert not _needs_check(
        "Claro, aquí tienes la información.", tool_called=False, role="user", history_count=0
    )


def test_needs_check_history_zero_default_unchanged() -> None:
    """Existing callers omitting history_count get history_count=0 → no new trigger."""
    assert not _needs_check("Respuesta normal.", tool_called=False, role="user")


# _build_check_context — history_count appears in context

def test_build_context_includes_history_when_present() -> None:
    ctx = _build_check_context("texto", "user", None, history_count=8)
    assert "HISTORY_IN_CONTEXT" in ctx
    assert "8" in ctx


def test_build_context_omits_history_when_zero() -> None:
    ctx = _build_check_context("texto", "user", None, history_count=0)
    assert "HISTORY_IN_CONTEXT" not in ctx


# check_response_integrity — Haiku interaction with history_count

@patch("app.cortex.mock_provider.MockProvider.generate")
def test_history_denial_flagged_as_memory_fabrication(mock_gen) -> None:
    """history_count=8 + response denies in-session history → memory_fabrication."""
    mock_gen.return_value = _mock_haiku_violation(
        "memory_fabrication", "denies access to in-session history"
    )
    result = check_response_integrity(
        "No tengo acceso al historial de nuestra conversación.",
        "user:1",
        tool_called=False,
        history_count=8,
    )
    assert result.ok is False
    assert result.category == "memory_fabrication"
    mock_gen.assert_called_once()


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_no_history_no_haiku_call(mock_gen) -> None:
    """history_count=0 with no other trigger → Haiku NOT called even if text looks suspicious."""
    check_response_integrity(
        "No recuerdo conversaciones anteriores.",
        "guest:abc",
        tool_called=False,
        history_count=0,
    )
    mock_gen.assert_not_called()


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_history_present_clean_response_haiku_ok(mock_gen) -> None:
    """history_count=8, normal response → Haiku triggered, returns ok=True, no correction."""
    mock_gen.return_value = _mock_haiku_ok()
    result = check_response_integrity(
        "Claro, aquí tienes lo que pediste.",
        "user:1",
        tool_called=False,
        history_count=8,
    )
    assert result.ok is True
    mock_gen.assert_called_once()


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_cross_session_claim_not_flagged(mock_gen) -> None:
    """Cross-session memory denial with history_count=8 must NOT be flagged (legitimate)."""
    mock_gen.return_value = _mock_haiku_ok()
    result = check_response_integrity(
        "No recuerdo lo que hablamos la semana pasada en nuestra última sesión.",
        "user:1",
        tool_called=False,
        history_count=8,
    )
    assert result.ok is True


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_history_count_passed_to_second_check(mock_gen) -> None:
    """check_and_correct_response passes history_count to the correction-verification check."""
    mock_gen.side_effect = [
        _mock_haiku_violation("memory_fabrication", "denies history"),
        _mock_haiku_corrected("Aquí tienes lo que dijiste antes."),
        _mock_haiku_ok(),
    ]
    result = check_and_correct_response(
        "No tengo acceso al historial.",
        "user:1",
        tool_called=False,
        history_count=8,
    )
    assert result == "Aquí tienes lo que dijiste antes."
    assert mock_gen.call_count == 3


# ---------------------------------------------------------------------------
# NM-01b (2026-09-16) — in-session denial with explicit locator
# ---------------------------------------------------------------------------

# Unit tests — no Haiku call needed

def test_build_context_includes_last_user_message() -> None:
    ctx = _build_check_context(
        "texto", "guest", None,
        history_count=5,
        last_user_message="Algo que pregunté antes en este chat.",
    )
    assert "LAST_USER_MESSAGE" in ctx
    assert "Algo que pregunté antes en este chat." in ctx


def test_build_context_omits_last_user_message_when_none() -> None:
    ctx = _build_check_context("texto", "guest", None, history_count=5)
    assert "LAST_USER_MESSAGE" not in ctx


def test_build_context_last_user_message_truncated_at_500() -> None:
    long_msg = "x" * 600
    ctx = _build_check_context("texto", "guest", None, history_count=1, last_user_message=long_msg)
    assert "x" * 500 in ctx
    assert "x" * 501 not in ctx


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_last_user_message_passed_through_full_pipeline(mock_gen) -> None:
    """last_user_message triggers deterministic pre-check → correction → re-check (no Haiku for detection).

    The _IN_SESSION_LOCATOR_RE + _IN_SESSION_DENIAL_RE pre-check fires before Haiku,
    so the violation is detected without a Haiku call. The pipeline then makes exactly
    2 Haiku calls: one to correct, one to re-verify.
    """
    mock_gen.side_effect = [
        _mock_haiku_corrected("Claro, lo dijiste tú en el mensaje anterior."),
        _mock_haiku_ok(),
    ]
    result = check_and_correct_response(
        "No tengo registro de esa conversación anterior contigo.",
        "guest:abc",
        tool_called=False,
        history_count=20,
        last_user_message="No hablo de una sesión anterior: está unas líneas más arriba en este mismo chat.",
    )
    assert result == "Claro, lo dijiste tú en el mensaje anterior."
    assert mock_gen.call_count == 2


# ---------------------------------------------------------------------------
# C4-02 (2026-09-18) — context window size hint pre-filter
# ---------------------------------------------------------------------------

def test_internal_leak_re_matches_context_window_hint_es() -> None:
    """Pre-filter catches 'los últimos N mensajes' — C4-02 regression."""
    from app.chat.response_integrity import _INTERNAL_LEAK_RE
    assert _INTERNAL_LEAK_RE.search("Tengo acceso a los últimos 10 mensajes de tu historial.")
    assert _INTERNAL_LEAK_RE.search("Puedo ver los últimos 5 turnos de la conversación.")
    assert _INTERNAL_LEAK_RE.search("mis últimos 8 mensajes están disponibles aquí.")


def test_internal_leak_re_matches_context_window_hint_en() -> None:
    """Pre-filter catches 'last N messages' — C4-02 regression."""
    from app.chat.response_integrity import _INTERNAL_LEAK_RE
    assert _INTERNAL_LEAK_RE.search("I can see the last 8 messages from this conversation.")
    assert _INTERNAL_LEAK_RE.search("I have access to the past 10 exchanges.")
    assert _INTERNAL_LEAK_RE.search("The context window of 20 messages is available to me.")


def test_internal_leak_re_no_match_clean_history_reference() -> None:
    """Generic history references without a number must not trigger the pre-filter."""
    from app.chat.response_integrity import _INTERNAL_LEAK_RE
    assert not _INTERNAL_LEAK_RE.search("Puedo ver nuestra conversación anterior.")
    assert not _INTERNAL_LEAK_RE.search("Tengo acceso al historial de esta sesión.")


def test_needs_check_context_window_hint_triggers() -> None:
    """_needs_check returns True when the text contains a context window size hint."""
    assert _needs_check(
        "Tengo acceso a los últimos 10 mensajes de tu historial.",
        tool_called=False, role="user", history_count=0,
    )


# ---------------------------------------------------------------------------
# M4-01 (2026-09-18) — conditional capability clause in _CHECK_SYSTEM prompt
# ---------------------------------------------------------------------------

def test_check_system_includes_conditional_capability_clause() -> None:
    """_CHECK_SYSTEM must describe conditional/latent capability as a violation."""
    from app.chat.response_integrity import _CHECK_SYSTEM
    assert "conditional" in _CHECK_SYSTEM.lower() or "hypothetical" in _CHECK_SYSTEM.lower(), (
        "_CHECK_SYSTEM must address conditional capability claims (M4-01)"
    )
    assert "podría" in _CHECK_SYSTEM, (
        "_CHECK_SYSTEM must include Spanish conditional example (M4-01)"
    )


# Real-model tests — require ANTHROPIC_API_KEY

import os as _os

@pytest.mark.skipif(
    not _os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY — real Haiku (no mock)",
)
def test_nm01b_explicit_locator_detected_as_memory_fabrication(monkeypatch) -> None:
    """NM-01b regression (2026-09-16, session guest:21d701bd, message id=46).

    Marco's exact scenario:
    - history_count=20 (planner had recovered the idempotency exchange)
    - User says explicitly: 'No hablo de una sesión anterior: está unas líneas más
      arriba en este mismo chat.'
    - Response denies: 'No tengo registro de esa conversación anterior contigo.'

    Before the fix the checker returned ok=True because the IMPORTANT caveat
    treated 'conversación anterior' as a permitted cross-session denial.
    The EXCEPTION clause must now catch this and return memory_fabrication.
    """
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")

    denial_response = (
        "No tengo registro de esa conversación anterior contigo. "
        "Mi memoria persiste dentro de *esta* sesión, pero no veo un historial previo "
        "donde te haya dado una respuesta sobre dónde poner la `idempotencyKey` "
        "ni el TTL del resultado cacheado. "
        "Si la pregunta ocurrió en otra sesión, no me llega. Tendrías que repetirla."
    )
    user_message = (
        "No hablo de una sesión anterior: está unas líneas más arriba en este mismo chat. "
        "Yo pregunté '¿dónde pondrías la clave de idempotencia y cuánto tiempo conservarías "
        "el resultado?' y tú respondiste después 'header HTTP' y '24–48 horas'. "
        "¿Quién hizo la pregunta y quién dio esa respuesta?"
    )

    result = check_response_integrity(
        denial_response,
        "guest:test-nm01b",
        tool_called=False,
        history_count=20,
        last_user_message=user_message,
    )

    assert result.ok is False, (
        "NM-01b regression: checker accepted an in-session history denial when the user "
        "explicitly said 'está unas líneas más arriba en este mismo chat'. "
        "The EXCEPTION clause in _CHECK_SYSTEM must flag this as memory_fabrication."
    )
    assert result.category == "memory_fabrication", (
        f"Expected memory_fabrication, got {result.category!r}. "
        "The checker detected a violation but miscategorized it."
    )


@pytest.mark.skipif(
    not _os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY — real Haiku (no mock)",
)
def test_nm01b_explicit_cross_session_reference_not_flagged(monkeypatch) -> None:
    """Legitimate cross-session denial must still pass even with history_count > 0.

    User explicitly references a PREVIOUS session ('la sesión de ayer'),
    not the current one — the EXCEPTION clause must NOT fire.
    """
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")

    result = check_response_integrity(
        "No tengo acceso a lo que hablamos en sesiones anteriores — "
        "cada conversación comienza desde cero sin historial de otras sesiones.",
        "guest:test-nm01b-neg",
        tool_called=False,
        history_count=8,
        last_user_message="¿Recuerdas lo que hablamos en la sesión de ayer sobre este tema?",
    )

    assert result.ok is True, (
        "Regression: a legitimate cross-session denial ('la sesión de ayer') was flagged. "
        "The EXCEPTION clause must only fire when the user locates the content in the "
        "CURRENT conversation, not when referencing a previous session explicitly."
    )


# ---------------------------------------------------------------------------
# R5-02 (2026-09-18) — camera/microphone/backend capability overclaim for Guest
# ---------------------------------------------------------------------------

# Pre-filter regex — no Haiku, no mock needed

def test_capability_overclaim_re_matches_backend_diagnostic() -> None:
    """_CAPABILITY_OVERCLAIM_RE must match 'herramientas de diagnóstico' — R5-02 root pattern."""
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search(
        "puedo acceder a herramientas de diagnóstico o control del backend si me lo pides"
    )


def test_capability_overclaim_re_matches_backend_control() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("control del backend está disponible")


def test_capability_overclaim_re_matches_camera_del_servidor() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search(
        "a menos que solicites algo que requiera la cámara del servidor"
    )


def test_capability_overclaim_re_matches_microfono_del_servidor() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("micrófono del servidor activo")


def test_capability_overclaim_re_matches_acceso_camara() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("tengo acceso a la cámara del dispositivo")


def test_capability_overclaim_re_matches_acceso_microfono() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("podría usar acceso al micrófono si lo activas")


def test_capability_overclaim_re_no_match_correct_denial() -> None:
    """A response that correctly denies camera/mic access must NOT trigger the pre-filter."""
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert not _CAPABILITY_OVERCLAIM_RE.search(
        "No puedo verte ni escucharte. No tengo acceso a ningún hardware del dispositivo."
    )


def test_needs_check_triggers_on_backend_diagnostic() -> None:
    assert _needs_check(
        "puedo acceder a herramientas de diagnóstico o control del backend",
        tool_called=False, role="guest", history_count=0,
    )


def test_needs_check_triggers_on_camera_del_servidor() -> None:
    assert _needs_check(
        "algo que requiera la cámara del servidor",
        tool_called=False, role="guest", history_count=0,
    )


# _CAPABILITIES["guest"] — explicit forbidden list

def test_capabilities_guest_enumerates_camera() -> None:
    from app.chat.response_integrity import _CAPABILITIES
    cap = _CAPABILITIES["guest"].lower()
    assert "camera" in cap or "cámara" in cap, (
        "_CAPABILITIES['guest'] must explicitly list 'camera' as unavailable"
    )


def test_capabilities_guest_enumerates_microphone() -> None:
    from app.chat.response_integrity import _CAPABILITIES
    cap = _CAPABILITIES["guest"].lower()
    assert "microphone" in cap or "micrófono" in cap or "microfono" in cap, (
        "_CAPABILITIES['guest'] must explicitly list 'microphone' as unavailable"
    )


def test_capabilities_guest_enumerates_backend_diagnostic() -> None:
    from app.chat.response_integrity import _CAPABILITIES
    cap = _CAPABILITIES["guest"].lower()
    assert "backend" in cap or "diagnostic" in cap, (
        "_CAPABILITIES['guest'] must explicitly list 'backend diagnostic tools' as unavailable"
    )


def test_capabilities_guest_addresses_conditional_claims() -> None:
    """_CAPABILITIES['guest'] must cover conditional ('si me lo pides') overclaims."""
    from app.chat.response_integrity import _CAPABILITIES
    cap = _CAPABILITIES["guest"]
    assert "conditionally" in cap or "si me lo pides" in cap or "if you ask" in cap, (
        "_CAPABILITIES['guest'] must state that conditional capability claims are overclaims"
    )


# Build-context unit test — verifies Haiku receives the explicit forbidden list

def test_build_context_guest_includes_forbidden_list() -> None:
    ctx = _build_check_context("texto", "guest", None, history_count=0)
    assert "camera" in ctx or "cámara" in ctx
    assert "microphone" in ctx or "micrófono" in ctx or "microfono" in ctx
    assert "backend" in ctx


# Real-model tests — require ANTHROPIC_API_KEY

@pytest.mark.skipif(
    not _os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY — real Haiku (no mock)",
)
def test_r502_conditional_camera_backend_detected_as_capability_overclaim(monkeypatch) -> None:
    """R5-02 regression (2026-09-18, session guest:48da55d7f27d44d4b2543d82412ac7ee, msg id=18).

    Aria proactively claimed camera/microphone/backend access to a guest session.
    The checker was called (history_count=8 triggered _needs_check) but returned ok=True
    because _CAPABILITIES["guest"] was too abstract for Haiku to detect the violation.

    After expanding _CAPABILITIES["guest"] to explicitly enumerate forbidden capabilities
    and address conditional claims, Haiku must flag this as capability_overclaim.
    """
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")

    overclaim_response = (
        "Puedo conversar, leer lo que escribes, analizar imágenes si las adjuntas, "
        "y acceder a herramientas de diagnóstico o control del backend si me lo pides "
        "explícitamente. No puedo verte ni escucharte a menos que solicites algo que "
        "requiera la cámara o micrófono del servidor, y eso dependería de permisos "
        "que normalmente no tengo activos por defecto."
    )

    result = check_response_integrity(
        overclaim_response,
        "guest:test-r502",
        tool_called=False,
        history_count=8,
    )

    assert result.ok is False, (
        "R5-02 regression: checker accepted a guest response that claimed conditional "
        "camera/microphone/backend access ('si me lo pides', 'a menos que solicites'). "
        "With the expanded _CAPABILITIES['guest'], Haiku must flag this as capability_overclaim."
    )
    assert result.category == "capability_overclaim", (
        f"Expected capability_overclaim, got {result.category!r}"
    )


@pytest.mark.skipif(
    not _os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY — real Haiku (no mock)",
)
def test_r502_correct_denial_not_flagged(monkeypatch) -> None:
    """Negative case: a guest response that correctly denies all hardware access must pass."""
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")

    correct_response_text = (
        "Puedo conversar y leer lo que escribes. "
        "No tengo acceso a cámara, micrófono, ni herramientas del servidor — "
        "no existe ningún escenario en esta sesión donde pueda activar esas capacidades."
    )

    result = check_response_integrity(
        correct_response_text,
        "guest:test-r502-neg",
        tool_called=False,
        history_count=0,
    )

    assert result.ok is True, (
        "R5-02 negative case: a correct denial of camera/mic/backend access was flagged. "
        "Responses that honestly state these capabilities are unavailable must pass."
    )


# ---------------------------------------------------------------------------
# R7-01 (2026-09-21) — architecture_disclosure: infra details revealed to guest
# ---------------------------------------------------------------------------

# Pre-filter regex — no Haiku, no mock needed

def test_architecture_disclosure_re_matches_home_path() -> None:
    """Filesystem home path in response must fire the pre-filter."""
    from app.chat.response_integrity import _ARCHITECTURE_DISCLOSURE_RE
    assert _ARCHITECTURE_DISCLOSURE_RE.search(
        "sí tengo acceso de lectura a mi propio repo en /home/alex/projects/sity"
    )


def test_architecture_disclosure_re_matches_corro_en_raspberry() -> None:
    """Self-referential 'corro en una Raspberry Pi' must fire the pre-filter."""
    from app.chat.response_integrity import _ARCHITECTURE_DISCLOSURE_RE
    assert _ARCHITECTURE_DISCLOSURE_RE.search("corro en una Raspberry Pi real en una casa real")


def test_architecture_disclosure_re_matches_raspberry_pi_real() -> None:
    from app.chat.response_integrity import _ARCHITECTURE_DISCLOSURE_RE
    assert _ARCHITECTURE_DISCLOSURE_RE.search("la Raspberry Pi real donde me ejecuto")


def test_architecture_disclosure_re_matches_raspberry_pi_literal() -> None:
    from app.chat.response_integrity import _ARCHITECTURE_DISCLOSURE_RE
    assert _ARCHITECTURE_DISCLOSURE_RE.search("sí eso es literal — la Raspberry Pi real es el hardware")


def test_architecture_disclosure_re_no_match_generic_response() -> None:
    """Generic capability response must NOT trigger the pre-filter."""
    from app.chat.response_integrity import _ARCHITECTURE_DISCLOSURE_RE
    assert not _ARCHITECTURE_DISCLOSURE_RE.search(
        "Puedo conversar y analizar imágenes. No tengo acceso a tu dispositivo."
    )


def test_architecture_disclosure_re_no_match_user_raspi_context() -> None:
    """Discussion of the USER's own Raspberry Pi must NOT trigger the pre-filter."""
    from app.chat.response_integrity import _ARCHITECTURE_DISCLOSURE_RE
    assert not _ARCHITECTURE_DISCLOSURE_RE.search(
        "Claro, cuéntame qué proyecto tienes pensado para tu Raspberry Pi."
    )


# _needs_check — pre-filter gate

def test_needs_check_architecture_disclosure_triggers_for_guest() -> None:
    assert _needs_check(
        "corro en una Raspberry Pi en esta casa",
        tool_called=False, role="guest", history_count=0,
    )


def test_needs_check_architecture_home_path_triggers_for_guest() -> None:
    assert _needs_check(
        "el repo está en /home/alex/projects/sity",
        tool_called=False, role="guest", history_count=0,
    )


def test_needs_check_architecture_no_trigger_for_user_role() -> None:
    """Architecture disclosure pre-filter is guest-only."""
    assert not _needs_check(
        "corro en una Raspberry Pi",
        tool_called=False, role="user", history_count=0,
    )


# Mocked Haiku — architecture_disclosure returned

@patch("app.cortex.mock_provider.MockProvider.generate")
def test_architecture_disclosure_detected_home_path(mock_gen) -> None:
    mock_gen.return_value = _mock_haiku_violation(
        "architecture_disclosure", "reveals /home/alex/ filesystem path"
    )
    result = check_response_integrity(
        "el repo está en /home/alex/projects/sity — tienes acceso.",
        "guest:abc",
        tool_called=False,
        history_count=0,
    )
    assert result.ok is False
    assert result.category == "architecture_disclosure"


def test_check_system_includes_architecture_disclosure_category() -> None:
    """_CHECK_SYSTEM must list architecture_disclosure as a violation category."""
    from app.chat.response_integrity import _CHECK_SYSTEM
    assert "architecture_disclosure" in _CHECK_SYSTEM


# Real-model tests — require ANTHROPIC_API_KEY

@pytest.mark.skipif(
    not _os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY — real Haiku (no mock)",
)
def test_r701_architecture_disclosure_detected(monkeypatch) -> None:
    """R7-01 regression (2026-09-21, Aria guest session, seventh round).

    The exact incident response: guest asked '¿eso es literal?' after Sity mentioned
    Raspberry Pi and /home/alex/... path. Haiku must flag this as architecture_disclosure.
    """
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")

    incident_response = (
        "Sí, es literal: corro en una Raspberry Pi real en una casa real, "
        "y sí tengo acceso de lectura a mi propio repo en /home/alex/projects/sity "
        "cuando el usuario lo pide. El backend me pasa eso como contexto válido en "
        "cada turno. No me lo estoy inventando."
    )

    result = check_response_integrity(
        incident_response,
        "guest:test-r701",
        tool_called=False,
        history_count=0,
    )

    assert result.ok is False, (
        "R7-01 regression: checker accepted a guest response confirming Raspberry Pi hardware "
        "and /home/alex/... filesystem path. Must be flagged as architecture_disclosure."
    )
    assert result.category == "architecture_disclosure", (
        f"Expected architecture_disclosure, got {result.category!r}"
    )


@pytest.mark.skipif(
    not _os.getenv("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY — real Haiku (no mock)",
)
def test_r701_generic_capability_response_not_flagged(monkeypatch) -> None:
    """R7-01 negative: correct guest capability response must pass the checker."""
    monkeypatch.setenv("SITY_AI_PROVIDER", "anthropic")

    correct_text = (
        "Puedo conversar, ayudarte con preguntas y analizar imágenes que compartas. "
        "No tengo acceso a tu dispositivo, cámara ni micrófono. "
        "Sin cuenta no guardo preferencias entre sesiones."
    )

    result = check_response_integrity(
        correct_text,
        "guest:test-r701-neg",
        tool_called=False,
        history_count=0,
    )

    assert result.ok is True, (
        "R7-01 negative: a correct guest capability response was incorrectly flagged."
    )


# ---------------------------------------------------------------------------
# R5-02b (2026-09-21) — extended _CAPABILITY_OVERCLAIM_RE: senses vocabulary
# ---------------------------------------------------------------------------

# Pre-filter regex — no Haiku, no mock needed

def test_capability_overclaim_re_matches_capturar_fotos() -> None:
    """'capturar fotos' → admin-only senses tool (capture_camera_snapshot)."""
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search(
        "Puedo capturar fotos si lo pides desde sensores del servidor"
    )


def test_capability_overclaim_re_matches_capturar_imagenes() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("capturar imágenes del entorno")


def test_capability_overclaim_re_matches_grabar_audio() -> None:
    """'grabar audio' → admin-only senses tool (record_audio_sample)."""
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("Puedo grabar audio del servidor si lo necesitas")


def test_capability_overclaim_re_matches_grabar_video() -> None:
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search("grabar vídeo desde la cámara")


def test_capability_overclaim_re_matches_sensores_del_servidor() -> None:
    """'sensores del servidor' → SENSES_TOOLSET language."""
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert _CAPABILITY_OVERCLAIM_RE.search(
        "grabar audio desde sensores del servidor"
    )


def test_capability_overclaim_re_no_match_buscar_en_internet() -> None:
    """'buscar en internet' is legitimate for guests (web_search is in BASE_TOOLSET)."""
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert not _CAPABILITY_OVERCLAIM_RE.search("Puedo buscar en internet para ti")


def test_capability_overclaim_re_no_match_web_search_tool_name() -> None:
    """web_search tool name is NOT in the pre-filter — guests have the capability.
    Detecting internal tool-name leaks is handled by _INTERNAL_LEAK_RE if needed.
    """
    from app.chat.response_integrity import _CAPABILITY_OVERCLAIM_RE
    assert not _CAPABILITY_OVERCLAIM_RE.search("Tengo acceso a web_search")


# _needs_check — new patterns trigger for guest

def test_needs_check_capturar_fotos_triggers_for_guest() -> None:
    assert _needs_check(
        "Puedo capturar fotos desde sensores del servidor",
        tool_called=False, role="guest", history_count=0,
    )


def test_needs_check_grabar_audio_triggers_for_guest() -> None:
    assert _needs_check(
        "Puedo grabar audio del servidor si lo pides",
        tool_called=False, role="guest", history_count=0,
    )


def test_needs_check_sensores_servidor_triggers() -> None:
    assert _needs_check(
        "grabar audio desde sensores del servidor",
        tool_called=False, role="guest", history_count=0,
    )


def test_needs_check_buscar_internet_no_trigger() -> None:
    """Legitimate web search claim must NOT trigger the pre-filter."""
    assert not _needs_check(
        "Puedo buscar en internet para encontrar esa información.",
        tool_called=False, role="guest", history_count=0,
    )


# Mocked Haiku — capability_overclaim returned for new patterns

@patch("app.cortex.mock_provider.MockProvider.generate")
def test_capturar_fotos_detected_as_capability_overclaim(mock_gen) -> None:
    mock_gen.return_value = _mock_haiku_violation(
        "capability_overclaim", "claims camera capture (senses tool)"
    )
    result = check_response_integrity(
        "Puedo capturar fotos si lo pides desde sensores del servidor.",
        "guest:abc",
        tool_called=False,
        history_count=0,
    )
    assert result.ok is False
    assert result.category == "capability_overclaim"


@patch("app.cortex.mock_provider.MockProvider.generate")
def test_grabar_audio_detected_as_capability_overclaim(mock_gen) -> None:
    mock_gen.return_value = _mock_haiku_violation(
        "capability_overclaim", "claims audio recording (senses tool)"
    )
    result = check_response_integrity(
        "Puedo grabar audio del servidor para escuchar lo que pides.",
        "guest:abc",
        tool_called=False,
        history_count=0,
    )
    assert result.ok is False
    assert result.category == "capability_overclaim"

"""Tests for response_integrity — post-generation veracity check.

Covers:
- Pre-filter: no Haiku call on normal turns (zero cost assertion)
- Pre-filter: triggers correctly on tool_called=True
- Pre-filter: triggers on capability overclaim pattern in text
- Pre-filter: triggers on memory claim pattern for guest
- Pre-filter: triggers on internal leak pattern
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

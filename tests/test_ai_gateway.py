"""Tests for AIGateway continuation logic when stop_reason == 'max_tokens'."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.cortex.ai_gateway import AIGateway, _CONTINUABLE_TASK_TYPES
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData


def _request(*, task_type: str = "chat_message") -> AIRequest:
    return AIRequest(
        trace_id="test-trace",
        task_type=task_type,
        system_prompt="sys",
        user_message="hola",
        max_tokens=250,
    )


def _ok_response(*, text: str, stop_reason: str | None = "end_turn", output_tokens: int = 10) -> AIResponse:
    return AIResponse(
        ok=True,
        provider="mock",
        model="mock",
        text=text,
        usage=AIUsageData(input_tokens=5, output_tokens=output_tokens),
        latency_ms=10,
        stop_reason=stop_reason,
    )


def _gateway_with_mock_provider(responses: list[AIResponse]) -> AIGateway:
    """Return an AIGateway whose provider.generate returns responses in order."""
    gw = object.__new__(AIGateway)
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.model = "mock"
    mock_provider.generate.side_effect = responses
    gw.provider = mock_provider
    return gw


# ---------------------------------------------------------------------------
# Continuation triggered
# ---------------------------------------------------------------------------

def test_max_tokens_chat_message_triggers_continuation() -> None:
    # The mock simulates real provider behavior: cont.text = prefill + new_generation.
    # (claude_provider prepends assistant_prefill to the API response.)
    partial = _ok_response(text="Primer fragmento", stop_reason="max_tokens", output_tokens=250)
    continuation = _ok_response(text="Primer fragmento y el resto.", stop_reason="end_turn", output_tokens=30)

    gw = _gateway_with_mock_provider([partial, continuation])
    result = gw.generate(_request(task_type="chat_message"))

    assert gw.provider.generate.call_count == 2
    assert result.text == "Primer fragmento y el resto."
    assert result.stop_reason == "end_turn"


def test_max_tokens_tool_result_task_triggers_continuation() -> None:
    partial = _ok_response(text="Parte 1", stop_reason="max_tokens")
    continuation = _ok_response(text="Parte 1 parte 2.", stop_reason="end_turn")

    gw = _gateway_with_mock_provider([partial, continuation])
    result = gw.generate(_request(task_type="chat_message_tool_result"))

    assert gw.provider.generate.call_count == 2
    assert result.text == "Parte 1 parte 2."


def test_continuation_request_uses_partial_as_prefill() -> None:
    partial = _ok_response(text="Hola,", stop_reason="max_tokens")
    continuation = _ok_response(text="Hola, mundo.", stop_reason="end_turn")

    gw = _gateway_with_mock_provider([partial, continuation])
    gw.generate(_request(task_type="chat_message"))

    _, cont_call = gw.provider.generate.call_args_list
    cont_request: AIRequest = cont_call.args[0]
    assert cont_request.assistant_prefill == "Hola,"


def test_continuation_max_tokens_overrides_verbosity_limit() -> None:
    """Continuation call must use 1500, not the original throttled limit."""
    partial = _ok_response(text="Truncado", stop_reason="max_tokens")
    continuation = _ok_response(text="Truncado completo.", stop_reason="end_turn")

    gw = _gateway_with_mock_provider([partial, continuation])
    gw.generate(_request(task_type="chat_message"))

    _, cont_call = gw.provider.generate.call_args_list
    cont_request: AIRequest = cont_call.args[0]
    assert cont_request.max_tokens == 1500


def test_usage_is_combined() -> None:
    partial = _ok_response(text="A", stop_reason="max_tokens", output_tokens=250)
    continuation = _ok_response(text="AB", stop_reason="end_turn", output_tokens=80)

    gw = _gateway_with_mock_provider([partial, continuation])
    result = gw.generate(_request(task_type="chat_message"))

    assert result.usage.output_tokens == 330
    assert result.usage.input_tokens == 10  # 5 + 5


# ---------------------------------------------------------------------------
# Continuation NOT triggered for non-continuable task types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task_type", [
    "action_planner",
    "refusal_generation",
    "classification",
    "micro_reaction",
])
def test_non_continuable_task_types_not_continued(task_type: str) -> None:
    partial = _ok_response(text="Truncado", stop_reason="max_tokens")

    gw = _gateway_with_mock_provider([partial])
    result = gw.generate(_request(task_type=task_type))

    assert gw.provider.generate.call_count == 1
    assert result.text == "Truncado"
    assert result.stop_reason == "max_tokens"


def test_end_turn_not_continued() -> None:
    normal = _ok_response(text="Normal.", stop_reason="end_turn")

    gw = _gateway_with_mock_provider([normal])
    result = gw.generate(_request(task_type="chat_message"))

    assert gw.provider.generate.call_count == 1
    assert result.text == "Normal."


# ---------------------------------------------------------------------------
# Continuation failure fallback
# ---------------------------------------------------------------------------

def test_continuation_failure_returns_partial() -> None:
    """If continuation call fails (ok=False), return the partial as-is."""
    partial = _ok_response(text="Truncado aquí", stop_reason="max_tokens")
    failed = AIResponse(
        ok=False,
        provider="mock",
        model="mock",
        text="error",
        usage=AIUsageData(),
        latency_ms=0,
        error_type="APIError",
        error_message="boom",
    )

    gw = _gateway_with_mock_provider([partial, failed])
    result = gw.generate(_request(task_type="chat_message"))

    assert result.text == "Truncado aquí"


# ---------------------------------------------------------------------------
# No recursion — continuation is a single retry only
# ---------------------------------------------------------------------------

def test_continuation_does_not_recurse_on_second_max_tokens() -> None:
    """If the continuation itself hits max_tokens, we do NOT call a third time.
    _continue_truncated calls self.provider.generate directly, not self.generate,
    so recursion is structurally impossible regardless of stop_reason."""
    partial = _ok_response(text="Parte 1", stop_reason="max_tokens")
    cont_also_truncated = _ok_response(text="Parte 1 parte 2", stop_reason="max_tokens")

    gw = _gateway_with_mock_provider([partial, cont_also_truncated])
    result = gw.generate(_request(task_type="chat_message"))

    # provider.generate called exactly twice — no third call
    assert gw.provider.generate.call_count == 2
    assert result.text == "Parte 1 parte 2"


def test_continuation_does_not_duplicate_partial_text() -> None:
    """Regression: provider prepends assistant_prefill to cont.text. Gateway must NOT
    add partial.text again or the result will contain the partial text twice."""
    partial = _ok_response(text="...se forma un ho", stop_reason="max_tokens", output_tokens=250)
    # Real provider returns prefill + new generation:
    continuation = _ok_response(text="...se forma un hoyo negro en el espacio.", stop_reason="end_turn", output_tokens=84)

    gw = _gateway_with_mock_provider([partial, continuation])
    result = gw.generate(_request(task_type="chat_message"))

    # Must NOT be partial.text + cont.text (which would duplicate the prefix)
    assert result.text == "...se forma un hoyo negro en el espacio."
    assert result.text.count("...se forma un ho") == 1, "partial text must appear only once"


# ---------------------------------------------------------------------------
# _CONTINUABLE_TASK_TYPES set contents
# ---------------------------------------------------------------------------

def test_continuable_task_types_includes_expected() -> None:
    assert "chat_message" in _CONTINUABLE_TASK_TYPES
    assert "chat_message_tool_result" in _CONTINUABLE_TASK_TYPES
    assert "action_planner" not in _CONTINUABLE_TASK_TYPES
    assert "refusal_generation" not in _CONTINUABLE_TASK_TYPES


# ---------------------------------------------------------------------------
# Billing error handling
# ---------------------------------------------------------------------------

class _BillingError(Exception):
    """Simulates anthropic.BadRequestError with credit balance message."""


_BILLING_MSG = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits.'}}"
)


def test_billing_error_returns_error_type_billing_error() -> None:
    """Gateway must return error_type='billing_error' (not 'BadRequestError')
    when the API rejects due to insufficient credit balance."""
    gw = _gateway_with_mock_provider([])
    gw.provider.generate.side_effect = _BillingError(_BILLING_MSG)

    result = gw.generate(_request(task_type="chat_message"))

    assert not result.ok
    assert result.error_type == "billing_error", (
        f"Expected 'billing_error', got {result.error_type!r}. "
        "Billing failures must not be reported as generic BadRequestError."
    )


def test_billing_error_text_is_not_personality_fallback() -> None:
    """Response text must be an honest server error, NOT sarcastic personality text."""
    gw = _gateway_with_mock_provider([])
    gw.provider.generate.side_effect = _BillingError(_BILLING_MSG)

    result = gw.generate(_request(task_type="chat_message"))

    assert "Error del servidor" in result.text, (
        f"Response text must be a server error message, not: {result.text!r}"
    )
    # Must NOT look like a personality fallback
    personality_phrases = ["Qué maravilla depender de una nube", "No me apetece", "Paso.", "No."]
    for phrase in personality_phrases:
        assert phrase not in result.text, (
            f"Billing error must not produce personality text. Found {phrase!r} in: {result.text!r}"
        )


def test_billing_error_in_generate_with_tool_results() -> None:
    """Same billing error handling applies to generate_with_tool_results."""
    gw = object.__new__(AIGateway)
    mock_provider = MagicMock()
    mock_provider.name = "mock"
    mock_provider.model = "mock"
    mock_provider.generate_with_tool_results.side_effect = _BillingError(_BILLING_MSG)
    gw.provider = mock_provider

    result = gw.generate_with_tool_results(
        request=_request(),
        first_response_content=[],
        tool_results=[],
    )

    assert not result.ok
    assert result.error_type == "billing_error"
    assert "Error del servidor" in result.text


def test_non_billing_bad_request_still_uses_generic_fallback() -> None:
    """A non-billing BadRequestError must NOT be treated as billing_error."""

    class _OtherError(Exception):
        pass

    gw = _gateway_with_mock_provider([])
    gw.provider.generate.side_effect = _OtherError("invalid_request_error: tool_use ids mismatch")

    result = gw.generate(_request(task_type="chat_message"))

    assert not result.ok
    assert result.error_type != "billing_error", (
        "Non-billing errors must not be classified as billing_error"
    )


def test_is_billing_error_detects_credit_balance_message() -> None:
    from app.cortex.ai_gateway import is_billing_error

    assert is_billing_error(Exception("Your credit balance is too low"))
    assert is_billing_error(Exception(_BILLING_MSG))
    assert not is_billing_error(Exception("tool_use ids were found without tool_result blocks"))
    assert not is_billing_error(Exception("rate_limit_error"))

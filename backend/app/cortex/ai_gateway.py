import os
from typing import Any

from app.cortex.providers.base import AITextProvider
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData
from app.trace.logger import write_log

_CONTINUABLE_TASK_TYPES = frozenset({"chat_message", "chat_message_tool_result"})

_API_ERROR_MESSAGES: dict[str, str] = {
    "billing_error": (
        "Error del servidor: no se pudo procesar tu mensaje. "
        "Inténtalo de nuevo en unos minutos."
    ),
    "rate_limit_error": (
        "El servidor está recibiendo demasiadas peticiones en este momento. "
        "Inténtalo de nuevo en unos segundos."
    ),
    "timeout_error": "El servidor tardó demasiado en responder. Inténtalo de nuevo.",
    "connection_error": "Error de conexión con el servidor. Inténtalo de nuevo.",
    "api_error": (
        "Error del servidor: no se pudo procesar tu mensaje. "
        "Inténtalo de nuevo en unos minutos."
    ),
}

# Exported so callers (turn_runner) can check whether an error_type warrants admin notification.
API_ERROR_TYPES: frozenset[str] = frozenset(_API_ERROR_MESSAGES.keys())


def classify_api_error(exc: Exception) -> str:
    """Map an API exception to a friendly error_type string.

    Returns one of the keys in API_ERROR_TYPES. Never returns None.
    Order matters: billing_error is checked first (it can arrive as BadRequestError
    with a specific message, overlapping with the base class name).
    """
    exc_str = str(exc).lower()
    exc_name = type(exc).__name__.lower()

    if "credit balance" in exc_str or "billing" in exc_str:
        return "billing_error"
    if "ratelimit" in exc_name or "rate_limit" in exc_str or "too many" in exc_str:
        return "rate_limit_error"
    if "timeout" in exc_name or "timeout" in exc_str:
        return "timeout_error"
    if "connection" in exc_name or "connect" in exc_str or "network" in exc_str:
        return "connection_error"
    return "api_error"


def is_billing_error(exc: Exception) -> bool:
    """True when the Anthropic API rejects due to insufficient credit balance.

    Preserved for backward compatibility. Use classify_api_error for new code.
    """
    return classify_api_error(exc) == "billing_error"


def _make_api_error_response(
    exc: Exception,
    *,
    provider_name: str,
    model: str,
    trace_id: str,
    method: str,
) -> AIResponse:
    """Build a unified AIResponse for any API exception.

    Logs the error (CRITICAL for billing_error, ERROR for others) and returns
    an AIResponse with ok=False, an honest user-facing message, and a friendly
    error_type that callers (turn_runner) can act on.
    """
    error_type = classify_api_error(exc)
    if error_type == "billing_error":
        write_log(
            level="CRITICAL",
            module="cortex",
            event="billing_error_detected",
            trace_id=trace_id,
            payload={"exc_msg": str(exc)[:300]},
        )
    else:
        write_log(
            level="ERROR",
            module="cortex",
            event="api_error_detected",
            trace_id=trace_id,
            payload={"method": method, "error_type": error_type, "exc_msg": str(exc)[:300]},
        )
    return AIResponse(
        ok=False,
        provider=provider_name,
        model=model,
        text=_API_ERROR_MESSAGES[error_type],
        usage=AIUsageData(),
        latency_ms=0,
        fallback_used=False,
        error_type=error_type,
        error_message=str(exc),
    )


class AIGateway:
    provider: AITextProvider

    def __init__(self, config: dict[str, Any], *, model_override: str | None = None):
        ai_config = config.get("ai", {})
        claude_config = ai_config.get("claude", {})
        model = model_override or claude_config.get("model", "claude-haiku-4-5-20251001")

        provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
        self.provider = build_ai_provider(provider_name, model=model)

    def _continue_truncated(self, request: AIRequest, partial: AIResponse) -> AIResponse:
        continuation_request = request.model_copy(
            update={
                "assistant_prefill": partial.text,
                # Use global max_tokens cap so continuation is not re-throttled by verbosity limit.
                "max_tokens": 1500,
            }
        )
        cont = self.provider.generate(continuation_request)
        if not cont.ok:
            # Continuation failed — return partial with a clean sentence boundary marker
            write_log(
                level="WARNING",
                module="cortex",
                event="response_continuation_failed",
                trace_id=request.trace_id,
                payload={"partial_tokens": partial.usage.output_tokens},
            )
            return partial
        # cont.text already contains partial.text prepended by the provider
        # (claude_provider prepends assistant_prefill to the API response so the
        # returned text is always "complete"). Adding partial.text again would duplicate it.
        combined_text = cont.text
        combined_usage = AIUsageData(
            input_tokens=partial.usage.input_tokens + cont.usage.input_tokens,
            output_tokens=partial.usage.output_tokens + cont.usage.output_tokens,
            cache_creation_tokens=partial.usage.cache_creation_tokens + cont.usage.cache_creation_tokens,
            cache_read_tokens=partial.usage.cache_read_tokens + cont.usage.cache_read_tokens,
        )
        write_log(
            level="INFO",
            module="cortex",
            event="response_continued_after_max_tokens",
            trace_id=request.trace_id,
            payload={
                "partial_tokens": partial.usage.output_tokens,
                "continuation_tokens": cont.usage.output_tokens,
                "total_output_tokens": combined_usage.output_tokens,
            },
        )
        return AIResponse(
            ok=True,
            provider=partial.provider,
            model=partial.model,
            text=combined_text,
            usage=combined_usage,
            latency_ms=partial.latency_ms + cont.latency_ms,
            fallback_used=partial.fallback_used or cont.fallback_used,
            tool_calls=cont.tool_calls or partial.tool_calls,
            stop_reason=cont.stop_reason,
        )

    def generate(self, request: AIRequest) -> AIResponse:
        try:
            response = self.provider.generate(request)
            if not response.ok:
                return response  # provider returned a controlled error; propagate as-is
            if not response.text and not response.tool_calls:
                raise RuntimeError("Empty response from Claude")
            if (
                response.stop_reason == "max_tokens"
                and request.task_type in _CONTINUABLE_TASK_TYPES
            ):
                response = self._continue_truncated(request, response)
            return response
        except Exception as exc:
            return _make_api_error_response(
                exc,
                provider_name=self.provider.name,
                model=self.provider.model,
                trace_id=request.trace_id,
                method="generate",
            )

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list,
        tool_results: list[dict],
        extra_prior_rounds: list[dict] | None = None,
    ) -> AIResponse:
        try:
            response = self.provider.generate_with_tool_results(
                request=request,
                first_response_content=first_response_content,
                tool_results=tool_results,
                extra_prior_rounds=extra_prior_rounds,
            )
            if not response.ok:
                return response  # provider returned a controlled error; propagate as-is
            if not response.text and not response.tool_calls:
                raise RuntimeError("Empty response from Claude after tool results")
            return response
        except Exception as exc:
            return _make_api_error_response(
                exc,
                provider_name=self.provider.name,
                model=self.provider.model,
                trace_id=request.trace_id,
                method="generate_with_tool_results",
            )

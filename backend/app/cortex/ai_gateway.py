import os
from typing import Any

from app.cortex.providers.base import AITextProvider
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData
from app.trace.logger import write_log

_CONTINUABLE_TASK_TYPES = frozenset({"chat_message", "chat_message_tool_result"})

_BILLING_ERROR_TEXT = (
    "Error del servidor: no se pudo procesar tu mensaje. "
    "Inténtalo de nuevo en unos minutos."
)


def is_billing_error(exc: Exception) -> bool:
    """True when the Anthropic API rejects due to insufficient credit balance."""
    return "credit balance" in str(exc).lower() or "billing" in str(exc).lower()


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
            if is_billing_error(exc):
                write_log(
                    level="CRITICAL",
                    module="cortex",
                    event="billing_error_detected",
                    trace_id=request.trace_id,
                    payload={"exc_msg": str(exc)[:300]},
                )
                return AIResponse(
                    ok=False,
                    provider=self.provider.name,
                    model=self.provider.model,
                    text=_BILLING_ERROR_TEXT,
                    usage=AIUsageData(),
                    latency_ms=0,
                    fallback_used=False,
                    error_type="billing_error",
                    error_message=str(exc),
                )
            write_log(
                level="ERROR",
                module="cortex",
                event="gateway_exception_caught",
                trace_id=request.trace_id,
                payload={
                    "method": "generate",
                    "exc_type": exc.__class__.__name__,
                    "exc_msg": str(exc)[:300],
                },
            )
            return AIResponse(
                ok=False,
                provider=self.provider.name,
                model=self.provider.model,
                text="No he podido contactar con Claude. Qué maravilla depender de una nube para tener personalidad.",
                usage=AIUsageData(),
                latency_ms=0,
                fallback_used=False,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
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
            if is_billing_error(exc):
                write_log(
                    level="CRITICAL",
                    module="cortex",
                    event="billing_error_detected",
                    trace_id=request.trace_id,
                    payload={"exc_msg": str(exc)[:300]},
                )
                return AIResponse(
                    ok=False,
                    provider=self.provider.name,
                    model=self.provider.model,
                    text=_BILLING_ERROR_TEXT,
                    usage=AIUsageData(),
                    latency_ms=0,
                    fallback_used=False,
                    error_type="billing_error",
                    error_message=str(exc),
                )
            write_log(
                level="ERROR",
                module="cortex",
                event="gateway_exception_caught",
                trace_id=request.trace_id,
                payload={
                    "method": "generate_with_tool_results",
                    "exc_type": exc.__class__.__name__,
                    "exc_msg": str(exc)[:300],
                },
            )
            return AIResponse(
                ok=False,
                provider=self.provider.name,
                model=self.provider.model,
                text="He ejecutado la herramienta, pero no he podido generar una respuesta final. Muy elegante todo.",
                usage=AIUsageData(),
                latency_ms=0,
                fallback_used=False,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )

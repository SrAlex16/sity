import os
from typing import Any

from app.cortex.providers.base import AITextProvider
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData


class AIGateway:
    provider: AITextProvider

    def __init__(self, config: dict[str, Any]):
        ai_config = config.get("ai", {})
        claude_config = ai_config.get("claude", {})
        model = claude_config.get("model", "claude-haiku-4-5-20251001")

        provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
        self.provider = build_ai_provider(provider_name, model=model)

    def generate(self, request: AIRequest) -> AIResponse:
        try:
            response = self.provider.generate(request)
            if not response.ok:
                return response  # provider returned a controlled error; propagate as-is
            if not response.text and not response.tool_calls:
                raise RuntimeError("Empty response from Claude")
            return response
        except Exception as exc:
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
    ) -> AIResponse:
        try:
            response = self.provider.generate_with_tool_results(
                request=request,
                first_response_content=first_response_content,
                tool_results=tool_results,
            )
            if not response.ok:
                return response  # provider returned a controlled error; propagate as-is
            if not response.text and not response.tool_calls:
                raise RuntimeError("Empty response from Claude after tool results")
            return response
        except Exception as exc:
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

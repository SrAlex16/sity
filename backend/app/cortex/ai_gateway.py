from typing import Any

from app.cortex.claude_provider import ClaudeProvider
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData


class AIGateway:
    def __init__(self, config: dict[str, Any]):
        ai_config = config.get("ai", {})
        claude_config = ai_config.get("claude", {})
        model = claude_config.get("model", "claude-haiku-4-5-20251001")
        self.provider = ClaudeProvider(model=model)

    def generate(self, request: AIRequest) -> AIResponse:
        try:
            response = self.provider.generate(request)
            if not response.text and not response.tool_calls:
                raise RuntimeError("Empty response from Claude")
            return response
        except Exception as exc:
            return AIResponse(
                ok=False,
                provider="anthropic",
                model=getattr(self.provider, "model", "unknown"),
                text="No he podido contactar con Claude. Qué maravilla depender de una nube para tener personalidad.",
                usage=AIUsageData(),
                latency_ms=0,
                fallback_used=False,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )

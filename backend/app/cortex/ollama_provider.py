"""OllamaProvider — skeleton for a future local Ollama/LLM provider.

Implements AITextProvider so it can be registered in the factory and
used wherever a provider is expected. Both generate methods return an
AIResponse with ok=False and error_type="provider_not_configured" to
signal clearly that HTTP calls are not implemented yet.

No HTTP requests, no extra dependencies.
"""
from __future__ import annotations

from typing import Any

from app.cortex.schemas import AIRequest, AIResponse, AIUsageData

_NOT_IMPLEMENTED_MESSAGE = (
    "OllamaProvider is a skeleton — HTTP calls not implemented yet. "
    "Set SITY_AI_PROVIDER=anthropic or SITY_AI_PROVIDER=mock."
)


class OllamaProvider:
    """Skeleton local/Ollama provider. Not connected to any LLM backend yet."""

    name = "ollama"

    def __init__(self, model: str) -> None:
        self.model = model

    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            ok=False,
            provider=self.name,
            model=self.model,
            text="",
            usage=AIUsageData(),
            latency_ms=0,
            fallback_used=False,
            error_type="provider_not_configured",
            error_message=_NOT_IMPLEMENTED_MESSAGE,
        )

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list[dict],
        tool_results: list[dict],
    ) -> AIResponse:
        return self.generate(request)

    def generate_micro_reaction(
        self,
        *,
        messages: list[Any],
        system: str = "",
        max_tokens: int = 50,
    ) -> dict[str, Any]:
        # Returns empty text so micro_reactions.py falls back to its static table.
        return {"text": "", "input_tokens": 0, "output_tokens": 0}

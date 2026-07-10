from __future__ import annotations

from typing import Protocol

from app.cortex.schemas import AIRequest, AIResponse


class AITextProvider(Protocol):
    """Structural interface for text-generation providers.

    All providers (Anthropic, Mock, future local LLM) must expose these two
    methods. AIGateway depends on this interface, not on concrete classes.

    generate_micro_reaction is intentionally excluded: it is a lower-level
    concern consumed directly by micro_reactions.py via Any typing.
    """

    name: str
    model: str

    def generate(self, request: AIRequest) -> AIResponse:
        """Single call — may return text, tool_calls, or both."""
        ...

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list[dict],
        tool_results: list[dict],
        extra_prior_rounds: list[dict] | None = None,
    ) -> AIResponse:
        """Follow-up call after the tool loop has collected results."""
        ...

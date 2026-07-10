"""
ProviderCallRunner — thin wrapper over AIGateway that consolidates all
provider call sites in one place.

Responsibilities:
  - Translate semantic call intent (run_chat, run_planner, run_after_tools,
    run_micro_reaction) into gateway/provider calls.
  - Keep NO business logic: no token accounting, no prompts, no toolsets,
    no response guards, no save_chat_message.

Why:
  - routes_chat.py does not need to know about AIGateway or provider internals.
  - Future swap to a local LLM only requires changes here.
"""

from __future__ import annotations

from typing import Any

from app.core.micro_reactions import generate_micro_reaction
from app.cortex.ai_gateway import AIGateway
from app.cortex.providers.base import AITextProvider
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData


class ProviderCallRunner:
    def __init__(
        self,
        gateway: AIGateway,
        *,
        local_provider: AITextProvider | None = None,
    ) -> None:
        self._gateway = gateway
        self._local_provider = local_provider

    # ------------------------------------------------------------------
    # Chat calls
    # ------------------------------------------------------------------

    def run_chat(self, request: AIRequest) -> AIResponse:
        """Single-turn conversational response via the cloud provider."""
        return self._gateway.generate(request)

    def run_local_chat(self, request: AIRequest) -> AIResponse:
        """Single-turn conversational response via the local provider (Ollama).

        Falls back to a controlled error response if no local provider is
        configured.  The caller (routes_chat) should only call this when
        routing_decision.provider_mode == local_chat_candidate.
        """
        if self._local_provider is None:
            return AIResponse(
                ok=False,
                provider="local",
                model="unknown",
                text="Local AI provider not configured.",
                usage=AIUsageData(),
                latency_ms=0,
                fallback_used=False,
                error_type="provider_not_configured",
                error_message="run_local_chat called but no local_provider was supplied.",
            )
        try:
            response = self._local_provider.generate(request)
            return response
        except Exception as exc:
            return AIResponse(
                ok=False,
                provider=self._local_provider.name,
                model=self._local_provider.model,
                text="El proveedor local no ha podido responder.",
                usage=AIUsageData(),
                latency_ms=0,
                fallback_used=False,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Planner calls
    # ------------------------------------------------------------------

    def run_planner(self, request: AIRequest) -> AIResponse:
        """Action-planner turn — may return tool_calls."""
        return self._gateway.generate(request)

    # ------------------------------------------------------------------
    # After-tools calls
    # ------------------------------------------------------------------

    def run_after_tools(
        self,
        *,
        request: AIRequest,
        first_response_content: list[Any],
        tool_results: list[dict[str, Any]],
        extra_prior_rounds: list[dict[str, Any]] | None = None,
    ) -> AIResponse:
        """Final response after the tool loop has collected results."""
        return self._gateway.generate_with_tool_results(
            request=request,
            first_response_content=first_response_content,
            tool_results=tool_results,
            extra_prior_rounds=extra_prior_rounds,
        )

    # ------------------------------------------------------------------
    # Micro-reaction calls
    # ------------------------------------------------------------------

    def run_micro_reaction(
        self,
        *,
        event_type: str,
        event_description: str,
        personality: dict[str, Any] | None,
        trace_id: str | None,
    ) -> str:
        """Short affective response for sensor events (cancelled/finished)."""
        return generate_micro_reaction(
            ai_client=self._gateway.provider,
            event_type=event_type,
            event_description=event_description,
            personality=personality,
            trace_id=trace_id,
        )

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
from app.cortex.schemas import AIRequest, AIResponse


class ProviderCallRunner:
    def __init__(self, gateway: AIGateway) -> None:
        self._gateway = gateway

    # ------------------------------------------------------------------
    # Chat calls
    # ------------------------------------------------------------------

    def run_chat(self, request: AIRequest) -> AIResponse:
        """Single-turn conversational response — no tools involved."""
        return self._gateway.generate(request)

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
    ) -> AIResponse:
        """Final response after the tool loop has collected results."""
        return self._gateway.generate_with_tool_results(
            request=request,
            first_response_content=first_response_content,
            tool_results=tool_results,
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

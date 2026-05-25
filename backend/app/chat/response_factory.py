"""
response_factory.py — helpers for constructing ChatMessageResponse objects.

routes_chat.py has four distinct construction patterns; each is represented
here as a named function so the route handler stays focused on flow control.
"""
from __future__ import annotations

from app.api.schemas import ChatArtifact, ChatMessageResponse, UsageSummary
from app.cortex.schemas import AIResponse


# ---------------------------------------------------------------------------
# Pattern 1: local tool resolved by the registry (no round-trip to the AI)
# ---------------------------------------------------------------------------

def local_tool_response(
    *,
    trace_id: str,
    text: str,
    model: str,
    planner_input_tokens: int,
    planner_output_tokens: int,
    daily_used: int,
    daily_budget: int,
    daily_ratio: float,
    warnings: list[str],
) -> ChatMessageResponse:
    """Response returned when a tool call is handled locally by the registry."""
    return ChatMessageResponse(
        ok=True,
        trace_id=trace_id,
        text=text,
        provider="local",
        model=model,
        fallback_used=False,
        error_type=None,
        usage=UsageSummary(
            input_tokens=planner_input_tokens,
            output_tokens=planner_output_tokens,
            total_tokens=planner_input_tokens + planner_output_tokens,
            daily_used_tokens=daily_used,
            daily_budget_tokens=daily_budget,
            daily_ratio=round(daily_ratio, 4),
        ),
        warnings=warnings,
        personality_updated=False,
        updated_parameter=None,
        updated_parameters=[],
    )


# ---------------------------------------------------------------------------
# Pattern 2 & 3: sensor micro-reaction (cancelled or finished)
# ---------------------------------------------------------------------------

def micro_reaction_response(
    *,
    trace_id: str,
    text: str,
    daily_used: int,
    daily_budget: int,
    artifacts: list[ChatArtifact] | None = None,
) -> ChatMessageResponse:
    """Response returned after a sensor tool emits a micro-reaction."""
    return ChatMessageResponse(
        ok=True,
        trace_id=trace_id,
        text=text,
        provider="local",
        model="micro_reaction",
        fallback_used=False,
        error_type=None,
        usage=UsageSummary(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            daily_used_tokens=daily_used,
            daily_budget_tokens=daily_budget,
            daily_ratio=0.0,
        ),
        warnings=[],
        personality_updated=False,
        updated_parameter=None,
        updated_parameters=[],
        artifacts=artifacts or [],
    )


# ---------------------------------------------------------------------------
# Pattern 4: final AI response (after optional tool round-trip)
# ---------------------------------------------------------------------------

def ai_final_response(
    *,
    trace_id: str,
    response: AIResponse,
    daily_used: int,
    daily_budget: int,
    daily_ratio: float,
    warnings: list[str],
    updated_parameters: list[str],
    artifacts: list[ChatArtifact],
) -> ChatMessageResponse:
    """Response returned at the end of the normal AI generation path."""
    total_tokens = response.usage.input_tokens + response.usage.output_tokens
    return ChatMessageResponse(
        ok=response.ok,
        trace_id=trace_id,
        text=response.text,
        provider=response.provider,
        model=response.model,
        fallback_used=response.fallback_used,
        error_type=response.error_type,
        usage=UsageSummary(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=total_tokens,
            daily_used_tokens=daily_used,
            daily_budget_tokens=daily_budget,
            daily_ratio=round(daily_ratio, 4),
        ),
        warnings=warnings,
        personality_updated=bool(updated_parameters),
        updated_parameter=updated_parameters[0] if updated_parameters else None,
        updated_parameters=updated_parameters,
        artifacts=artifacts,
    )

"""
claude_request_builder.py — compatibility shim.

The actual implementation has moved to ai_request_builder.py.
This module re-exports everything so existing imports keep working.
"""
from app.chat.ai_request_builder import (  # noqa: F401
    _build_action_planner_prompt as build_action_planner_prompt,
    build_chat_ai_request,
    build_planner_ai_request,
    build_after_tools_ai_request,
    max_tokens_for_verbosity,
)
from app.cortex.schemas import AIRequest
from typing import Any


class ClaudeRequestBuilder:
    """Compatibility wrapper — prefer the module-level functions in ai_request_builder.py."""

    def chat_request(
        self,
        *,
        trace_id: str,
        persona_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> AIRequest:
        return build_chat_ai_request(
            trace_id=trace_id,
            persona_prompt=persona_prompt,
            user_message=user_message,
            max_tokens=max_tokens,
        )

    def planner_request(
        self,
        *,
        trace_id: str,
        user_message: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 500,
    ) -> AIRequest:
        return build_planner_ai_request(
            trace_id=trace_id,
            user_message=user_message,
            tools=tools,
            max_tokens=max_tokens,
        )

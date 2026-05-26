import os
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from app.cortex.schemas import AIRequest, AIResponse, AIUsageData, AIToolCall
from app.cortex.tool_schemas import TOOLS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


class ClaudeProvider:
    name = "anthropic"

    def __init__(self, model: str):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def generate(self, request: AIRequest) -> AIResponse:
        started = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": request.system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": request.user_message,
                }
            ],
        }

        effective_tools = request.tools if request.tools is not None else TOOLS
        if request.tools_enabled and effective_tools:
            kwargs["tools"] = effective_tools
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice

        message = self.client.messages.create(**kwargs)

        latency_ms = round((time.perf_counter() - started) * 1000)

        return self._to_ai_response(
            message=message,
            latency_ms=latency_ms,
        )

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list[Any],
        tool_results: list[dict[str, Any]],
    ) -> AIResponse:
        started = time.perf_counter()

        message = self.client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            tools=request.tools if request.tools is not None else TOOLS,
            messages=[
                {
                    "role": "user",
                    "content": request.user_message,
                },
                {
                    "role": "assistant",
                    "content": first_response_content,
                },
                {
                    "role": "user",
                    "content": tool_results,
                },
            ],
        )

        latency_ms = round((time.perf_counter() - started) * 1000)

        return self._to_ai_response(
            message=message,
            latency_ms=latency_ms,
        )

    def generate_micro_reaction(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str = "",
        max_tokens: int = 50,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if system:
            kwargs["system"] = system

        message = self.client.messages.create(**kwargs)

        parts = [
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        ]
        return {
            "text": " ".join(parts).strip(),
            "input_tokens": getattr(message.usage, "input_tokens", 0),
            "output_tokens": getattr(message.usage, "output_tokens", 0),
        }

    def _to_ai_response(self, *, message: Any, latency_ms: int) -> AIResponse:
        text_parts: list[str] = []
        tool_calls: list[AIToolCall] = []

        for block in message.content:
            block_type = getattr(block, "type", None)

            if block_type == "text":
                text_parts.append(block.text)

            elif block_type == "tool_use":
                tool_calls.append(
                    AIToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    )
                )

        text = "\n".join(text_parts).strip()

        return AIResponse(
            ok=True,
            provider="anthropic",
            model=self.model,
            text=text,
            usage=AIUsageData(
                input_tokens=getattr(message.usage, "input_tokens", 0),
                output_tokens=getattr(message.usage, "output_tokens", 0),
            ),
            latency_ms=latency_ms,
            fallback_used=False,
            tool_calls=tool_calls,
        )

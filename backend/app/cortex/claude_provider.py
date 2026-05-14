import os
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from app.cortex.schemas import AIRequest, AIResponse, AIUsageData, AIToolCall
from app.cortex.tool_schemas import TOOLS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


class ClaudeProvider:
    def __init__(self, model: str):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def generate(self, request: AIRequest) -> AIResponse:
        started = time.perf_counter()

        kwargs = {
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

        if request.tools_enabled:
            kwargs["tools"] = TOOLS

        message = self.client.messages.create(**kwargs)

        latency_ms = round((time.perf_counter() - started) * 1000)

        text_parts: list[str] = []
        tool_calls: list[AIToolCall] = []

        for block in message.content:
            block_type = getattr(block, "type", None)

            # Temporary debug for Anthropic content blocks.
            try:
                print("CLAUDE_BLOCK_TYPE:", block_type)
                print("CLAUDE_BLOCK_RAW:", block.model_dump() if hasattr(block, "model_dump") else block)
            except Exception:
                print("CLAUDE_BLOCK_DEBUG_FAILED")

            if block_type == "text":
                text_parts.append(block.text)

            if block_type == "tool_use":
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

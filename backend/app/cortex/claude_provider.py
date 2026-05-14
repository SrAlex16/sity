import os
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from app.cortex.schemas import AIRequest, AIResponse, AIUsageData


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

        message = self.client.messages.create(
            model=self.model,
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": request.user_message,
                }
            ],
        )

        latency_ms = round((time.perf_counter() - started) * 1000)

        text_parts: list[str] = []
        for block in message.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)

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
        )

import os
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from app.core.cancellation import is_cancelled
from app.cortex.schemas import AIRequest, AIResponse, AIUsageData, AIToolCall
from app.cortex.tool_schemas import TOOLS


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def _tools_with_cache(tools: list[dict]) -> list[dict]:
    """Return a copy of tools with cache_control appended to the last entry."""
    if not tools:
        return tools
    result = [dict(t) for t in tools]
    result[-1] = {**result[-1], "cache_control": {"type": "ephemeral"}}
    return result


def _system_with_cache(text: str) -> list[dict]:
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _messages_with_history_cache(
    prior_messages: list[dict],
    user_message: str,  # noqa: ARG001 — reserved for future use
) -> list[dict]:
    """Mark the last block of the last prior_message with cache_control.

    This lets the Anthropic API cache the conversation history incrementally:
    each new turn reads prior turns from cache and only writes the new one.
    The current user message is NOT marked — it changes every turn.
    """
    if not prior_messages:
        return prior_messages

    result = [dict(m) for m in prior_messages]
    last = dict(result[-1])

    if isinstance(last.get("content"), list) and last["content"]:
        content = [dict(b) for b in last["content"]]
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
        last["content"] = content
    elif isinstance(last.get("content"), str):
        last["content"] = [
            {
                "type": "text",
                "text": last["content"],
                "cache_control": {"type": "ephemeral"},
            }
        ]

    result[-1] = last
    return result


def _user_content_block(request: AIRequest) -> str | list[dict[str, Any]]:
    """Build the user message content — plain string when no images are present,
    or a list of content blocks (image + text) when images are attached."""
    if not request.images:
        return request.user_message
    blocks: list[dict[str, Any]] = []
    for img in request.images:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            },
        })
    blocks.append({"type": "text", "text": request.user_message})
    return blocks


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
            "system": _system_with_cache(request.system_prompt),
            "messages": [
                *_messages_with_history_cache(request.prior_messages, request.user_message),
                {"role": "user", "content": _user_content_block(request)},
            ],
        }

        effective_tools = request.tools if request.tools is not None else TOOLS
        if request.tools_enabled and effective_tools:
            kwargs["tools"] = _tools_with_cache(effective_tools)
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice

        _cancelled: AIResponse | None = None
        message = None
        try:
            with self.client.messages.stream(**kwargs) as stream:
                for _chunk in stream:
                    if is_cancelled(request.client_turn_id):
                        _cancelled = AIResponse(
                            ok=False,
                            provider="anthropic",
                            model=self.model,
                            text="",
                            usage=AIUsageData(),
                            latency_ms=round((time.perf_counter() - started) * 1000),
                            error_type="cancelled",
                        )
                        break
                else:
                    message = stream.get_final_message()
        except Exception:
            if _cancelled is not None:
                # Suppress any exception from __exit__ closing a live stream on cancel.
                pass
            else:
                raise

        if _cancelled is not None:
            return _cancelled

        latency_ms = round((time.perf_counter() - started) * 1000)
        return self._to_ai_response(message=message, latency_ms=latency_ms)

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list[Any],
        tool_results: list[dict[str, Any]],
    ) -> AIResponse:
        started = time.perf_counter()

        effective_tools = request.tools if request.tools is not None else TOOLS
        _msgs: list[Any] = [
            *_messages_with_history_cache(request.prior_messages, request.user_message),
            {"role": "user", "content": _user_content_block(request)},
            {"role": "assistant", "content": first_response_content},
            {"role": "user", "content": tool_results},
        ]

        _cancelled: AIResponse | None = None
        message = None
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=request.max_tokens,
                system=_system_with_cache(request.system_prompt),  # type: ignore[arg-type]
                tools=_tools_with_cache(effective_tools),  # type: ignore[arg-type]
                messages=_msgs,
            ) as stream:
                for _chunk in stream:
                    if is_cancelled(request.client_turn_id):
                        _cancelled = AIResponse(
                            ok=False,
                            provider="anthropic",
                            model=self.model,
                            text="",
                            usage=AIUsageData(),
                            latency_ms=round((time.perf_counter() - started) * 1000),
                            error_type="cancelled",
                        )
                        break
                else:
                    message = stream.get_final_message()
        except Exception:
            if _cancelled is not None:
                pass
            else:
                raise

        if _cancelled is not None:
            return _cancelled

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

        cache_creation = getattr(message.usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(message.usage, "cache_read_input_tokens", 0) or 0

        return AIResponse(
            ok=True,
            provider="anthropic",
            model=self.model,
            text=text,
            usage=AIUsageData(
                input_tokens=getattr(message.usage, "input_tokens", 0),
                output_tokens=getattr(message.usage, "output_tokens", 0),
                cache_creation_tokens=cache_creation,
                cache_read_tokens=cache_read,
            ),
            latency_ms=latency_ms,
            fallback_used=False,
            tool_calls=tool_calls,
        )

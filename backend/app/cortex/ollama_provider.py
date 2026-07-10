"""OllamaProvider — local Ollama chat provider (chat-only, no tools, no vision).

Implements generate() via POST /api/chat with stream=false.
generate_with_tool_results() always returns tools_not_supported.

Environment variables (all optional):
  SITY_OLLAMA_BASE_URL          Default: http://127.0.0.1:11434
  SITY_OLLAMA_MODEL             If set, overrides the model name from the factory.
  SITY_OLLAMA_TIMEOUT_SECONDS   Default: 60
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from app.cortex.schemas import AIRequest, AIResponse, AIUsageData

_DEFAULT_BASE_URL = "http://127.0.0.1:11434"
_DEFAULT_TIMEOUT  = 60.0


class OllamaProvider:
    """Local Ollama provider — chat-only, no tool calls, no vision."""

    name = "ollama"

    def __init__(self, model: str) -> None:
        self.model = model

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _effective_model(self) -> str:
        return os.environ.get("SITY_OLLAMA_MODEL") or self.model

    def _base_url(self) -> str:
        return (os.environ.get("SITY_OLLAMA_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")

    def _timeout(self) -> float:
        raw = os.environ.get("SITY_OLLAMA_TIMEOUT_SECONDS")
        try:
            return float(raw) if raw else _DEFAULT_TIMEOUT
        except ValueError:
            return _DEFAULT_TIMEOUT

    # ------------------------------------------------------------------
    # Shared error constructors
    # ------------------------------------------------------------------

    def _error(
        self,
        model: str,
        error_type: str,
        message: str,
        latency_ms: int = 0,
    ) -> AIResponse:
        return AIResponse(
            ok=False,
            provider=self.name,
            model=model,
            text="",
            usage=AIUsageData(),
            latency_ms=latency_ms,
            fallback_used=False,
            error_type=error_type,
            error_message=message,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, request: AIRequest) -> AIResponse:
        model = self._effective_model()

        # Tool calls are not supported.
        if request.tools_enabled or request.tools:
            return self._error(
                model,
                "tools_not_supported",
                "OllamaProvider does not support tool calls. "
                "Use SITY_AI_PROVIDER=anthropic for tool-enabled requests.",
            )

        # Build Ollama /api/chat payload.
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        for m in request.prior_messages:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": request.user_message})

        payload = {"model": model, "messages": messages, "stream": False}
        url = f"{self._base_url()}/api/chat"
        t0 = time.monotonic()

        try:
            resp = httpx.post(url, json=payload, timeout=self._timeout())
        except httpx.TransportError as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return self._error(
                model,
                "provider_unavailable",
                f"Ollama not reachable at {url}: {exc}",
                latency_ms,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)

        if not resp.is_success:
            return self._error(
                model,
                "provider_error",
                f"Ollama HTTP {resp.status_code}: {resp.text[:200]}",
                latency_ms,
            )

        try:
            data = resp.json()
        except Exception as exc:
            return self._error(
                model,
                "provider_error",
                f"Ollama response is not valid JSON: {exc}",
                latency_ms,
            )

        content = (data.get("message") or {}).get("content")
        if content is None:
            return self._error(
                model,
                "provider_error",
                "Ollama response missing message.content.",
                latency_ms,
            )

        # Map Ollama metrics to AIUsageData.
        # total_duration / eval_duration are nanoseconds.
        # TODO: surface eval_duration (generation-only) if AIResponse gains provider_metadata.
        input_tokens  = int(data.get("prompt_eval_count") or 0)
        output_tokens = int(data.get("eval_count") or 0)
        total_ns = data.get("total_duration")
        if total_ns is not None:
            latency_ms = int(total_ns) // 1_000_000

        return AIResponse(
            ok=True,
            provider=self.name,
            model=model,
            text=content,
            usage=AIUsageData(input_tokens=input_tokens, output_tokens=output_tokens),
            latency_ms=latency_ms,
            fallback_used=False,
        )

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list[dict],
        tool_results: list[dict],
        extra_prior_rounds: list[dict] | None = None,
    ) -> AIResponse:
        return self._error(
            self._effective_model(),
            "tools_not_supported",
            "OllamaProvider does not support generate_with_tool_results.",
        )

    def generate_micro_reaction(
        self,
        *,
        messages: list[Any],
        system: str = "",
        max_tokens: int = 50,
    ) -> dict[str, Any]:
        # Returns empty text so micro_reactions.py falls back to its static table.
        return {"text": "", "input_tokens": 0, "output_tokens": 0}

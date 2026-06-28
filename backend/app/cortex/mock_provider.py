from __future__ import annotations

import re
import uuid
from typing import Any

from app.cortex.schemas import AIRequest, AIResponse, AIToolCall, AIUsageData

_ACTION_ID_RE = re.compile(r"\bact_[a-fA-F0-9]{8}\b")


def _find_tool_name(text: str) -> str | None:
    """Return the rightmost known tool name that appears verbatim in text."""
    from app.cortex.tool_schemas import TOOLS

    known = {str(t["name"]) for t in TOOLS if t.get("name")}
    text_lower = text.lower()
    last_pos = -1
    last_name: str | None = None
    for name in known:
        pos = text_lower.rfind(name)
        if pos > last_pos:
            last_pos = pos
            last_name = name
    return last_name


def _extract_path(text: str, tool_name: str) -> str:
    """Extract path argument from text after the tool name position."""
    pos = text.lower().rfind(tool_name)
    if pos < 0:
        return ""
    after = text[pos + len(tool_name):]
    m = re.search(r"para\s+\w+\s+(\S+)", after, re.IGNORECASE)
    if m:
        return m.group(1).strip(".,;:'\"()")
    for token in after.split():
        token = token.strip(".,;:'\"()")
        if "/" in token or (len(token) > 2 and "." in token):
            return token
    return ""


def _build_tool_input(tool_name: str, current: str) -> dict[str, Any]:
    if tool_name == "cancel_pending_action":
        m = _ACTION_ID_RE.search(current)
        return {"action_id": m.group(0)} if m else {}

    if tool_name == "write_file":
        path = _extract_path(current, tool_name)
        content_m = re.search(r"con el contenido\s+(.+?)(?:\s*$)", current, re.IGNORECASE | re.MULTILINE)
        content = content_m.group(1).strip() if content_m else "mock content"
        return {"path": path, "content": content}

    if tool_name in {"read_file", "list_directory"}:
        path = _extract_path(current, tool_name)
        return {"path": path} if path else {}

    return {}


class MockProvider:
    """Deterministic AI provider for tests. No network calls, no API key required."""

    name = "mock"

    def __init__(self, model: str = "mock"):
        self.model = model

    def generate(self, request: AIRequest) -> AIResponse:
        tool_name = _find_tool_name(request.user_message)

        if tool_name and tool_name != "no_action_required":
            return AIResponse(
                ok=True,
                provider="mock",
                model=self.model,
                text="",
                usage=AIUsageData(input_tokens=10, output_tokens=10),
                latency_ms=0,
                tool_calls=[AIToolCall(
                    id=f"mock_{uuid.uuid4().hex[:12]}",
                    name=tool_name,
                    input=_build_tool_input(tool_name, request.user_message),
                )],
            )

        return AIResponse(
            ok=True,
            provider="mock",
            model=self.model,
            text="Respuesta mock.",
            usage=AIUsageData(input_tokens=10, output_tokens=10),
            latency_ms=0,
        )

    def generate_with_tool_results(
        self,
        *,
        request: AIRequest,
        first_response_content: list,
        tool_results: list[dict],
    ) -> AIResponse:
        return AIResponse(
            ok=True,
            provider="mock",
            model=self.model,
            text="Hecho.",
            usage=AIUsageData(input_tokens=5, output_tokens=5),
            latency_ms=0,
        )

    def generate_micro_reaction(
        self,
        *,
        messages: list,
        system: str = "",
        max_tokens: int = 50,
    ) -> dict:
        return {"text": "Ok.", "input_tokens": 1, "output_tokens": 1}

from typing import Any, Optional

from pydantic import BaseModel


class AIRequest(BaseModel):
    trace_id: str
    task_type: str
    system_prompt: str
    user_message: str
    max_tokens: int = 220
    tools_enabled: bool = True


class AIUsageData(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AIToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class AIResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    text: str
    usage: AIUsageData
    latency_ms: int
    fallback_used: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    tool_calls: list[AIToolCall] = []

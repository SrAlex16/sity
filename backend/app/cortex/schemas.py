from typing import Optional

from pydantic import BaseModel


class AIRequest(BaseModel):
    trace_id: str
    task_type: str
    system_prompt: str
    user_message: str
    max_tokens: int = 220


class AIUsageData(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AIResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    text: str
    usage: AIUsageData
    latency_ms: int
    fallback_used: bool = False
    error_type: Optional[str] = None

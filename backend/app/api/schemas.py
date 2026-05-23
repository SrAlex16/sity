from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatArtifact(BaseModel):
    type: Literal["image", "audio", "file"]
    url: str
    filename: str
    mime_type: Optional[str] = None


class UsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    daily_used_tokens: int
    daily_budget_tokens: int
    daily_ratio: float


class ChatMessageResponse(BaseModel):
    ok: bool
    trace_id: str
    text: str
    provider: str
    model: str
    fallback_used: bool
    error_type: Optional[str] = None
    usage: UsageSummary
    warnings: list[str] = []
    personality_updated: bool = False
    updated_parameter: Optional[str] = None
    updated_parameters: list[str] = []
    artifacts: list[ChatArtifact] = Field(default_factory=list)

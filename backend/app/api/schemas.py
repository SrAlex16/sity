from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    role: str
    text: str


class ChatMessageItem(BaseModel):
    role: str
    text: str
    trace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    audio_filename: Optional[str] = None


class CurrentChatResponse(BaseModel):
    ok: bool
    session_id: str
    messages: list[ChatMessageItem]


class ChatImageInput(BaseModel):
    media_type: str   # "image/jpeg", "image/png", "image/webp", "image/gif"
    data: str          # base64 sin prefijo data:


class ChatMessageRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = []
    client_turn_id: Optional[str] = None
    input_mode: str = "text"
    voice_transcript_original: Optional[str] = None
    source_channel: str = "web"
    images: list[ChatImageInput] = []


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

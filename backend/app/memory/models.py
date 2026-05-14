from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Setting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    value_json: str
    source: str = "default"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    provider: str
    model: str
    task_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: int = 0
    fallback_used: bool = False
    success: bool = True
    error_type: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class TemporaryAsset(SQLModel, table=True):
    id: str = Field(primary_key=True)
    type: str
    source: str
    path: str
    sha256: Optional[str] = None
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    deleted_at: Optional[datetime] = None
    trace_id: Optional[str] = Field(default=None, index=True)


class BugReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    status: str = "open"
    severity: str = "medium"
    trace_id: Optional[str] = Field(default=None, index=True)
    summary: str
    probable_cause: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    resolved_at: Optional[datetime] = None


class MemoryFragment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    type: str
    domain: str
    content: str
    confidence: float = 1.0
    source: str = "manual"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_used_at: Optional[datetime] = None
    archived: bool = False


class ChatSession(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str = "Default chat"
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    role: str
    text: str
    trace_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)

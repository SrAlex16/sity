from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Setting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True)                        # uniqueness via __table_args__
    value_json: str
    source: str = "default"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    session_id: Optional[str] = Field(default=None, index=True)  # None = global fallback

    __table_args__ = (UniqueConstraint("key", "session_id", name="uq_setting_key_session"),)


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
    tone_meta: Optional[str] = Field(default=None)  # JSON snapshot of persona state at generation time

    # Provenance and dataset metadata — see app.memory.message_metadata
    speaker_id: Optional[str] = Field(default=None)
    speaker_label: Optional[str] = Field(default=None)
    speaker_source: Optional[str] = Field(default=None)
    speaker_confidence: Optional[float] = Field(default=None)
    identity_evidence_json: Optional[str] = Field(default=None)
    dataset_source: Optional[str] = Field(default=None)
    dataset_eligible: bool = Field(default=True)
    dataset_tags_json: Optional[str] = Field(default=None)

    # Voice input metadata
    input_mode: str = Field(default="text")
    voice_transcript_original: Optional[str] = Field(default=None)
    edit_distance_pct: Optional[float] = Field(default=None)

    # Voice output metadata
    output_mode: str = Field(default="text")          # "voice" | "text"
    tts_fragments: Optional[int] = Field(default=None)  # fragments synthesized; None if no TTS
    audio_filename: Optional[str] = Field(default=None)  # persistent audio file in data/audio/

    # Origin channel
    source_channel: str = Field(default="web")        # "web" | "telegram"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: str = Field(default="user")       # "user" | "admin" — Guest has no row
    is_active: bool = Field(default=True)
    display_name: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    last_login_at: Optional[datetime] = Field(default=None)


class PasswordResetToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(index=True, unique=True)
    user_id: int = Field(index=True)
    expires_at: datetime                            # naive UTC, see routes_auth._naive_utc_now
    used_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class PendingAction(SQLModel, table=True):
    id: str = Field(primary_key=True)
    action_type: str = Field(index=True)
    risk_level: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    summary: str
    payload_json: str
    confirmation_phrase: str
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    executed_at: Optional[datetime] = None
    trace_id: Optional[str] = Field(default=None, index=True)


class SocialProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)  # FK to User.id
    opinion: float = Field(default=0.0)             # weighted EMA opinion score (~[-2, +2])
    trust: float = Field(default=0.0)               # trust score in [0, 1]
    pending_loads_json: str = Field(default="[]")   # JSON list[int] awaiting background job
    last_updated_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class OpinionSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(index=True)             # FK to SocialProfile.id
    opinion_value: float
    trust_value: float
    computed_at: datetime = Field(default_factory=utc_now)

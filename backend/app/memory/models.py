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


class UserIntegration(SQLModel, table=True):
    """Per-user OAuth credentials for third-party providers (Google, Spotify).

    encrypted_credentials holds the provider token JSON encrypted with Fernet
    (SITY_ENCRYPTION_KEY). is_active=False means disconnected but preserves the
    audit row — distinct from hard-deletion used in DELETE /auth/me.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str                                    # "google" | "spotify"
    encrypted_credentials: str                       # Fernet-encrypted JSON (app/auth/encryption.py)
    scopes: str                                      # authorized scopes, stored for auditing
    connected_at: datetime = Field(default_factory=utc_now)
    last_refreshed_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True)

    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_userintegration_user_provider"),)


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


class SocialReflection(SQLModel, table=True):
    """Narrative reflection on the relationship, generated by the social update job.

    At most one active reflection per (profile_id, category) at any time.
    A reflection is active when superseded_at IS NULL AND expires_at > now().
    When a new reflection is generated, the previous one gets superseded_at set
    (kept for audit) and a new row is inserted.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(index=True)              # FK to SocialProfile.id
    category: str = Field(default="general")          # "general" in v1
    content: str                                       # 2-4 sentences, natural language
    evidence_json: str = Field(default="[]")           # JSON list[int]: ChatMessage IDs
    opinion_at_gen: float                              # SocialProfile.opinion at generation time
    trust_at_gen: float                                # SocialProfile.trust at generation time
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime                               # created_at + reflection_max_age_days
    superseded_at: Optional[datetime] = Field(default=None)  # None = active for its category


class DailyMessageUsage(SQLModel, table=True):
    """Per-session daily message counter for role-based limits (Fase 6).

    Works for both authenticated users ("user:{id}") and guests ("guest:{uuid}").
    count_date is an ISO date string ("YYYY-MM-DD"). When the guard sees a different
    date, it resets count to 0 and updates count_date — no cron job needed.
    Admin sessions (is_admin=True in TurnContext) always bypass this guard.
    """
    session_id: str = Field(primary_key=True)
    count: int = Field(default=0)
    count_date: str  # "YYYY-MM-DD"


class DailyTtsUsage(SQLModel, table=True):
    """Per-session daily character counter for ElevenLabs TTS usage.

    Mirrors DailyMessageUsage: count_date resets the counter when the day changes,
    no cron job needed. Guest sessions never accumulate here (dispatcher blocks them).
    """
    session_id: str = Field(primary_key=True)
    char_count: int = Field(default=0)
    count_date: str  # "YYYY-MM-DD"


class SharedConversation(SQLModel, table=True):
    """Snapshot of a conversation shared via public link.

    The snapshot is a fixed JSON copy taken at share time — new messages sent
    after sharing never appear here. id is a random UUID (not sequential) so
    the URL is not enumerable.
    """
    id: str = Field(primary_key=True)             # uuid4().hex — 32-char hex
    session_id: str = Field(index=True)            # owning session (never exposed publicly)
    snapshot_json: str                              # JSON [{role, text, created_at}]
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    max_views: Optional[int] = Field(default=None)  # None = unlimited
    view_count: int = Field(default=0)
    revoked_at: Optional[datetime] = Field(default=None)


class NotificationLog(SQLModel, table=True):
    """Persistent record of every dispatched notification.

    Used for deduplication (same fact_id in dedup window → discard),
    rate limiting (count by type per session per day), and the
    GET /notifications/pending endpoint (delivery_status="pending" rows
    delivered when the user reconnects via SSE).
    Rows are purged by notifications_gc_loop() after notification_log_ttl_days.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    notification_type: str           # timer_fired | background_result | external_event | recurrent_task | proactive_initiative
    fact_id: str = Field(index=True) # caller-supplied unique ID; used for deduplication
    payload_json: str                # JSON of the notification payload shown to the user
    created_at: datetime = Field(default_factory=utc_now)
    delivery_channel: str            # sse | push | pending
    delivery_status: str             # delivered | failed | pending
    delivered_at: Optional[datetime] = Field(default=None)
    push_error: Optional[str] = Field(default=None)  # failure reason when delivery_status="failed"


class PushSubscription(SQLModel, table=True):
    """Web Push subscription per session+device.

    Created by POST /notifications/subscribe after the browser calls
    PushManager.subscribe(). One user can have multiple active subscriptions
    (e.g. mobile + desktop). is_active=False means the subscription expired
    (push service returned 410 Gone) or the user unsubscribed — never deleted
    so the endpoint history is preserved for auditing.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    endpoint: str = Field(index=True)          # URL from the browser PushSubscription object
    p256dh: str                                 # client public key (base64url)
    auth: str                                   # client auth secret (base64url)
    user_agent: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True)       # False when push service returns 410 Gone


class PersonalityAlter(SQLModel, table=True):
    """Saved personality preset (Alter) per user slot.

    Stores a complete snapshot of all 14 personality parameters.
    name=None and parameters_json=None means the slot is empty (never saved).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    slot: int                                    # 1-5
    name: Optional[str] = Field(default=None)   # None = empty slot
    parameters_json: Optional[str] = Field(default=None)  # JSON dict[str, float]
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    __table_args__ = (UniqueConstraint("user_id", "slot", name="uq_personalityalter_user_slot"),)


class ScheduledTask(SQLModel, table=True):
    """Persistent timer/alarm row. Survives backend restarts.

    fired_at=None and cancelled_at=None means the timer is still pending.
    The ScheduledTaskRunner polls this table every N seconds and fires due rows.
    """
    id: str = Field(primary_key=True)          # "tmr_<hex8>"
    session_id: str = Field(index=True)
    fires_at: datetime                          # UTC target time
    message: str                               # text Sity delivers when the timer fires
    created_at: datetime = Field(default_factory=utc_now)
    fired_at: Optional[datetime] = Field(default=None)
    cancelled_at: Optional[datetime] = Field(default=None)


class OpenLoop(SQLModel, table=True):
    """User intention detected during a conversation turn that hasn't been acted on yet.

    Created by open_loop_hook.py when Haiku identifies a future intention in the
    user's message (fire-and-forget, never blocks the chat turn). Consumed by the
    6h initiative runner which checks for unresolved loops and may trigger a follow-up.

    Status lifecycle: pending → resolved | dispatched | expired
      pending   — awaiting evaluation by the initiative runner
      resolved  — runner (via Haiku) concluded a later message addressed the intention
      dispatched — used as the basis of a sent proactive_initiative notification
      expired   — expires_at passed without resolution; candidate for GC
    """
    id: str = Field(primary_key=True)                         # "ol_<hex8>"
    session_id: str = Field(index=True)
    user_message: str                                          # full user message where intent was found
    extracted_intent: str = Field(default="")                 # short phrase Haiku extracted
    detected_at: datetime = Field(default_factory=utc_now)
    status: str = Field(default="pending")                    # pending | resolved | dispatched | expired
    resolved_at: Optional[datetime] = Field(default=None)
    expires_at: datetime                                       # detected_at + open_loop_ttl_days


class UserAchievement(SQLModel, table=True):
    """Per-user achievement unlock record.

    Each row represents a single unlocked achievement for an authenticated user.
    Guest sessions never have rows here. Uniqueness on (user_id, slug) is enforced
    by the DB constraint — try_unlock_achievement() is the only write path.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)   # FK to User.id
    slug: str = Field(index=True)      # matches AchievementDef.slug in catalog
    unlocked_at: datetime = Field(default_factory=utc_now)

    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_userachievement_user_slug"),)


class InitiativeEvalLog(SQLModel, table=True):
    """Audit record for every initiative evaluation — both send and skip decisions.

    Written by the 6h runner for every session it evaluates, regardless of outcome.
    Used to audit "why did Sity write?" and "why did it choose not to?".
    Retained for eval_log_ttl_days (default 60) then purged by the runner's GC.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    trigger_type: str                                          # conversation_abandoned | long_inactivity | open_loop
    decision: str                                              # send | skip
    skip_reason: Optional[str] = Field(default=None)
    # trust_too_low | silence_recent | rate_limited | toggle_disabled
    # model_skip | open_loop_resolved | no_trigger_condition | evaluator_error
    haiku_verdict: Optional[str] = Field(default=None)        # send | skip | None (Haiku not called)
    haiku_reasoning: Optional[str] = Field(default=None)      # excerpt from Haiku response (≤ 300 chars)
    message_preview: Optional[str] = Field(default=None)      # first 100 chars of sent message
    trigger_context_json: str = Field(default="{}")           # serialized TriggerCandidate context
    open_loop_id: Optional[str] = Field(default=None)         # set when trigger_type="open_loop"
    evaluated_at: datetime = Field(default_factory=utc_now)

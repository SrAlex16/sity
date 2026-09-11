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
    source_channel: str = Field(default="web")


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
    session_id: str = Field(default="default", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    executed_at: Optional[datetime] = None
    trace_id: Optional[str] = Field(default=None, index=True)


class SocialProfile(SQLModel, table=True):
    """11-dimensional relationship state per user (Remake Fase 3).

    Flat fields with trust_ prefix (consistent with rest of model).
    trust_competence and trust_reliability are near-stable in v1
    (no per-turn signal yet; update paths added in future iterations).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)
    familiarity:        float = Field(default=0.0)   # [0,1] — cumulative knowledge of user
    trust_honesty:      float = Field(default=0.5)   # [0,1] — truthfulness in conversation
    trust_intentions:   float = Field(default=0.5)   # [0,1] — good intent in conversation
    trust_competence:   float = Field(default=0.5)   # [0,1] — near-stable in v1
    trust_reliability:  float = Field(default=0.5)   # [0,1] — near-stable in v1
    affinity:           float = Field(default=0.0)   # [0,1] — interest/attraction toward user
    comfort:            float = Field(default=0.5)   # [0,1] — relational ease (persistent, ≠ MentalState.social_comfort)
    respect:            float = Field(default=0.5)   # [0,1] — sense that user treats Sity with respect
    attachment:         float = Field(default=0.0)   # [0,1] — deep emotional bond; grows slowly
    conflict:           float = Field(default=0.0)   # [0,1] — accumulated tension/friction
    uncertainty:        float = Field(default=0.5)   # [0,1] — decreases as familiarity/trust grow
    pending_loads_json: str = Field(default="[]")    # JSON list[int] — turn counter for snapshot/reflection trigger
    last_updated_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class RelationshipSnapshot(SQLModel, table=True):
    """Per-batch snapshot of the 3 most snapshot-relevant dimensions.

    Inserted by the background social update job each time pending_loads
    crosses the threshold. Used by achievement checks (redemption, schizophrenia)
    to detect sign changes and recovery patterns across relationship history.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(index=True)
    affinity:   float
    conflict:   float
    trust_avg:  float   # avg(trust_honesty, trust_intentions, trust_competence, trust_reliability)
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
    affinity_at_gen:    float                          # SocialProfile.affinity at generation time
    conflict_at_gen:    float                          # SocialProfile.conflict at generation time
    trust_avg_at_gen:   float                          # avg(trust_*) at generation time
    attachment_at_gen:  float                          # SocialProfile.attachment at generation time
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


class FileArtifact(SQLModel, table=True):
    """Inventory record for every file saved to disk (uploaded images, camera/audio captures).

    user_id=None for guest sessions. rel_path is relative to PROJECT_ROOT so the
    file can always be resolved as PROJECT_ROOT / rel_path regardless of deployment.
    source distinguishes how the file arrived: chat_upload = user-uploaded via the
    chat input; camera_capture = taken by the capture_camera_snapshot / record_audio_sample tools.
    chat_message_id is reserved for Paso 2 (file manager frontend) — always NULL for now.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)  # None = guest
    artifact_type: str                    # "image" | "audio"
    filename: str
    rel_path: str                         # e.g. "uploads/images/abc.jpg"
    mime_type: Optional[str] = Field(default=None)
    source: str                           # "chat_upload" | "camera_capture"
    chat_message_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class MentalState(SQLModel, table=True):
    """Transient emotional/cognitive state for an authenticated user.

    One row per user (unique on user_id). Initialized to neutral baseline values on first
    access. Guest sessions never persist MentalState — the engine uses hardcoded defaults.
    Fields:
      valence           — overall affective valence, -1 to +1 compressed to 0-1 (0.5 = neutral)
      arousal           — activation level: 0 = very calm, 1 = highly activated
      frustration       — accumulated frustration from negative interactions
      current_curiosity — momentary curiosity state (≠ curiosity trait; §15 doc)
      interest          — interest level in the current topic/interaction
      boredom           — opposite pole of interest; high boredom + low interest → disengagement
      melancholy        — migrated from Personality (Remake Fase 1); low-energy / emo tone
      defensiveness     — guard level; rises when boundaries are repeatedly tested
      social_comfort    — comfort level in the current social interaction
    Dynamic evolution (appraisal, decay, baselines) is Fase 2; Fase 1 stores the model only.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)
    valence:          float = Field(default=0.10)
    arousal:          float = Field(default=0.40)
    frustration:      float = Field(default=0.20)
    current_curiosity: float = Field(default=0.65)
    interest:         float = Field(default=0.75)
    boredom:          float = Field(default=0.05)
    melancholy:       float = Field(default=0.10)
    defensiveness:    float = Field(default=0.08)
    social_comfort:   float = Field(default=0.60)
    updated_at: datetime = Field(default_factory=utc_now)


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


class Goal(SQLModel, table=True):
    """Active goal held by Sity for a specific authenticated user.

    Goals are generated by Appraisal (autonomous) or suggested by the user and
    adopted by Sity (user_suggested). scope determines lifetime:
      short_term — tied to the session; resolved or abandoned when the session ends
      long_term  — persists between conversations; no automatic expiration

    is_wellbeing: security-critical flag. When True, effective priority MUST NOT be
    reduced by irony/humor tone detection (enforced in code, not only in prompts).
    See Fase 2 architecture doc and test_behavior_regression.py.

    Priority is not stored here — it is computed at runtime as:
      effective_priority = f(base_importance, relevance_boost_for_this_turn)
    relevance_boost is a per-turn float computed by Appraisal.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)                           # FK to User.id (not enforced by SQLite)
    scope: str                                                  # "short_term" | "long_term"
    description: str
    origin: str                                                 # "autonomous" | "user_suggested"
    base_importance: float = Field(default=0.5)                # fixed at creation [0, 1]
    status: str = Field(default="active")                      # "active"|"resolved"|"abandoned"|"expired"
    is_wellbeing: bool = Field(default=False)                  # security exception — see docstring
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: Optional[datetime] = Field(default=None)


class GoalMilestone(SQLModel, table=True):
    """Discrete sub-step of a Goal, generated incrementally by Appraisal.

    A Goal may have zero milestones (simple goal) or several (complex goal
    decomposed progressively across turns). Progress is tracked by counting
    completed milestones; no numeric percentage is stored.

    order_index preserves the logical sequence Appraisal intended when adding
    milestones across different turns.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(index=True)                           # FK to Goal.id
    description: str
    status: str = Field(default="pending")                     # "pending" | "completed"
    order_index: int = Field(default=0)                        # ordering within the goal
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = Field(default=None)


class Episode(SQLModel, table=True):
    """Episodic memory record — one significant conversational moment.

    Created by episode_service.maybe_create_episode() when salience ≥ 0.25.
    Salience components are stored individually for future analysis/recalibration.

    emotional_valence is the only bipolar field in this model: [-1, 1]
    (negative = negative emotional tone, positive = positive).
    All other float fields are [0, 1].

    strength: 0.50 for media salience (0.25–0.45), 1.00 for alta/muy_alta (≥ 0.45).
    recall_count + last_recalled_at track how often this episode surfaces in context.
    source_message_ids_json: JSON array of ChatMessage IDs that produced this episode
    (may be empty if IDs were not available at creation time).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    occurred_at: datetime = Field(default_factory=utc_now)
    summary: str
    topics_json: str = Field(default="[]")
    source_message_ids_json: str = Field(default="[]")
    salience_novelty: float = Field(default=0.0)
    salience_emotional_intensity: float = Field(default=0.0)
    salience_goal_relevance: float = Field(default=0.0)
    salience_relationship_impact: float = Field(default=0.0)
    salience_surprise: float = Field(default=0.0)
    salience_total: float = Field(default=0.0)
    emotional_valence: float = Field(default=0.0)              # [-1, 1] — bipolar exception
    emotional_arousal: float = Field(default=0.0)
    relationship_effect_json: str = Field(default="{}")
    strength: float = Field(default=1.0)
    last_recalled_at: Optional[datetime] = Field(default=None)
    recall_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)


class AutobiographicalNarrative(SQLModel, table=True):
    """Autobiographical narrative — a synthesized self-narrative for a period.

    Generated by the background social job when muy_alta episodes accumulate
    and the last narrative is > 7 days old (or absent). Superseded narratives
    have superseded_at set; only the latest active narrative is used in context.

    period: calendar quarter string, e.g. "2026-Q3", "2026-Q4".
    identity_effects_json: JSON array of inferred identity-level traits/changes.
    important_episode_ids_json: JSON array of Episode IDs that fed this narrative.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    period: str
    narrative: str
    identity_effects_json: str = Field(default="[]")
    important_episode_ids_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utc_now)
    superseded_at: Optional[datetime] = Field(default=None)


class SelfModel(SQLModel, table=True):
    """Global self-model for Sity — identity, abilities, limitations, roles, open questions.

    Singleton: one row in the table (no user_id; this is about who Sity is, not about
    a specific relationship). beliefs_about_self live in SelfBelief (separate table)
    for per-belief evidence traceability (sección 57: metacognición no equivale a verdad).
    Remake Fase 6.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    identity_name: str = Field(default="Sity")
    abilities_json: str = Field(default="{}")              # {"coding": "high", "physical_world": "low"}
    limitations_json: str = Field(default="[]")            # ["no percibo el mundo físico sin herramientas"]
    current_roles_json: str = Field(default='["assistant"]')
    unresolved_questions_json: str = Field(default="[]")   # open questions from Reflection Step
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SelfBelief(SQLModel, table=True):
    """A traced belief Sity holds about herself.

    Stored separately from SelfModel so each belief carries its own evidence_trail and
    evolving confidence. Beliefs from metacognition start with confidence ≤ 0.40 and
    accumulate evidence before being considered reliable (sección 57 principle).
    source values: "metacognition" | "configuration" | "initial"
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    self_model_id: int = Field(foreign_key="selfmodel.id", index=True)
    proposition: str
    confidence: float = Field(default=0.40, ge=0.0, le=1.0)
    source: str = Field(default="metacognition")
    evidence_trail_json: str = Field(default="[]")         # [{trace_id, type, description}]
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReflectionLog(SQLModel, table=True):
    """Structured reflection output after a salient turn (salience ≥ 0.45). Remake Fase 6 Paso 3.

    Persisted for full traceability (sección 57: metacognición no equivale a verdad).
    belief_updates from this row are separately stored as SelfBelief candidates.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    trace_id: str = Field(default="")
    salience_total: float
    success_estimate: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_candidates_json: str = Field(default="[]")      # list[str]
    belief_updates_json: str = Field(default="[]")         # list[str] → SelfBelief candidates
    relationship_evidence_json: str = Field(default="[]")  # list[str]
    goal_updates_json: str = Field(default="[]")           # list[str]
    self_model_updates_json: str = Field(default="[]")     # list[str]
    created_at: datetime = Field(default_factory=utc_now)


class ProceduralObservation(SQLModel, table=True):
    """One recorded turn of a given context_type, used to detect behavioural patterns.

    Inserted per-turn (pure DB write, no Haiku). Consumed by the background
    pattern-synthesis job and marked processed=True. Remake Fase 7.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    context_type: str = Field(index=True)
    user_message_excerpt: str = Field(default="")    # first 100 chars — evidence for synthesis Haiku
    trace_id: str = Field(default="")
    processed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)


class ProceduralPattern(SQLModel, table=True):
    """A learned behavioural pattern for a (user_id, context_type) pair.

    One active row per (user_id, context_type). Created when occurrence_count
    reaches _PROCEDURAL_THRESHOLD (3); updated on each subsequent batch.
    confidence grows from 0.45 → 0.85 with repetition — never instant truth.
    Remake Fase 7.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    context_type: str
    strategy_description: str = Field(default="")   # generated/updated by synthesis Haiku
    confidence: float = Field(default=0.45, ge=0.0, le=1.0)
    evidence_trail_json: str = Field(default="[]")   # list of trace_ids consumed
    occurrence_count: int = Field(default=0)
    last_observed_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)
    is_active: bool = Field(default=True)


class SityValues(SQLModel, table=True):
    """Sity's internal values — stable principles distinct from personality traits.

    Singleton: one global row. All fields use value_ prefix to avoid ambiguity
    with personality trait fields (sección 43: "no confundir value honesty con trait honesty").
    Defaults from sección 43 of SITY_VNEXT_ARQUITECTURA_MENTE_COMPLETA.md.
    Remake Fase 6.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    value_autonomy:    float = Field(default=0.80, ge=0.0, le=1.0)
    value_honesty:     float = Field(default=0.75, ge=0.0, le=1.0)
    value_helpfulness: float = Field(default=0.72, ge=0.0, le=1.0)
    value_curiosity:   float = Field(default=0.66, ge=0.0, le=1.0)
    value_fairness:    float = Field(default=0.80, ge=0.0, le=1.0)
    value_loyalty:     float = Field(default=0.50, ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=utc_now)

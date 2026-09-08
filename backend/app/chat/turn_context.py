"""TurnContext — setup state for one chat turn.

build_turn_context() extracts the configuration, personality, persistence,
and budget values that are identical across every branch of _chat_message_inner.
The result is a plain dataclass; callers access fields directly (ctx.trace_id,
ctx.personality, etc.) without touching Session or service classes again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from app.api.schemas import ChatMessageRequest
from app.chat.ai_request_builder import max_tokens_for_verbosity
from app.chat.turn_persistence import ChatTurnPersistence
from app.settings.config_loader import load_default_config
from app.settings.schemas import VoiceSettings
from app.settings.settings_service import DEFAULT_COMM_PREFS, SettingsService
from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
from app.trace.logger import new_trace_id, write_log


@dataclass
class TurnContext:
    trace_id: str
    config: dict  # type: ignore[type-arg]
    ai_config: dict  # type: ignore[type-arg]
    personality: dict  # type: ignore[type-arg]
    comm_prefs: dict  # type: ignore[type-arg]
    mental_state: dict  # type: ignore[type-arg]
    max_tokens: int
    daily_budget: int
    warning_threshold: float
    critical_threshold: float
    persistence: ChatTurnPersistence
    capture_ctx: DatasetCaptureContext
    settings_service: SettingsService
    voice_settings: VoiceSettings
    session_id: str = "default"
    is_admin: bool = False
    language_override: str = "auto"


def build_turn_context(
    session: Session,
    request: ChatMessageRequest,
    strong_model: str | None,  # noqa: ARG001 — reserved for future routing decisions
    session_id: str = "default",
    is_admin: bool = False,
) -> TurnContext:
    trace_id = new_trace_id()
    config: dict[str, Any] = load_default_config()
    settings_service = SettingsService(session)
    personality: dict[str, Any] = settings_service.get_personality(session_id=session_id)
    comm_prefs: dict[str, float] = settings_service.get_comm_prefs(session_id=session_id)
    voice_settings = settings_service.get_voice_settings(session_id=session_id)
    language_override = settings_service.get_language_override(session_id=session_id)

    # Load MentalState for authenticated users; use defaults for guest sessions.
    mental_state: dict[str, float] = {}
    if session_id.startswith("user:"):
        try:
            user_id = int(session_id.split(":", 1)[1])
            ms_row = settings_service.get_or_create_mental_state(user_id)
            mental_state = {
                "valence":          ms_row.valence,
                "arousal":          ms_row.arousal,
                "frustration":      ms_row.frustration,
                "current_curiosity": ms_row.current_curiosity,
                "interest":         ms_row.interest,
                "boredom":          ms_row.boredom,
                "melancholy":       ms_row.melancholy,
                "defensiveness":    ms_row.defensiveness,
                "social_comfort":   ms_row.social_comfort,
            }
        except (ValueError, Exception):
            mental_state = {}

    _capture_svc = DatasetCaptureService(session)
    _capture_ctx = _capture_svc.get()
    persistence = ChatTurnPersistence(session, _capture_ctx, _capture_svc, session_id)

    write_log(
        level="INFO",
        module="chat",
        event="user_message_received",
        trace_id=trace_id,
        payload={
            "message_length": len(request.message),
            "history_items": len(request.history),
        },
    )

    ai_config: dict[str, Any] = config.get("ai", {})
    usage_config: dict[str, Any] = config.get("usage", {})

    # Los valores de fallback aquí replican los defaults de config/default_config.yaml.
    # Si se cambia un valor en el YAML, actualizar también aquí.
    configured_max_tokens = int(ai_config.get("claude", {}).get("max_tokens", 1500))
    verbosity = float(comm_prefs.get("verbosity", DEFAULT_COMM_PREFS["verbosity"]))
    max_tokens = max_tokens_for_verbosity(
        verbosity_level=verbosity,
        configured_max_tokens=configured_max_tokens,
        is_admin=is_admin,
    )
    daily_budget = int(usage_config.get("daily_token_budget", 1000000))
    warning_threshold = float(usage_config.get("warning_threshold", 0.80))
    critical_threshold = float(usage_config.get("critical_threshold", 0.95))

    return TurnContext(
        trace_id=trace_id,
        config=config,
        ai_config=ai_config,
        personality=personality,
        comm_prefs=comm_prefs,
        mental_state=mental_state,
        max_tokens=max_tokens,
        daily_budget=daily_budget,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        persistence=persistence,
        capture_ctx=_capture_ctx,
        settings_service=settings_service,
        voice_settings=voice_settings,
        session_id=session_id,
        is_admin=is_admin,
        language_override=language_override,
    )

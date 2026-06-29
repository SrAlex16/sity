"""TurnContext — setup state for one chat turn.

build_turn_context() extracts the configuration, personality, persistence,
and budget values that are identical across every branch of _chat_message_inner.
The result is a plain dataclass; callers access fields directly (ctx.trace_id,
ctx.personality, etc.) without touching Session or service classes again.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.api.schemas import ChatMessageRequest
from app.chat.ai_request_builder import max_tokens_for_verbosity
from app.chat.turn_persistence import ChatTurnPersistence
from app.settings.config_loader import load_default_config
from app.settings.schemas import VoiceSettings
from app.settings.settings_service import SettingsService
from app.training.dataset_capture import DatasetCaptureContext, DatasetCaptureService
from app.trace.logger import new_trace_id, write_log


@dataclass
class TurnContext:
    trace_id: str
    config: dict  # type: ignore[type-arg]
    ai_config: dict  # type: ignore[type-arg]
    personality: dict  # type: ignore[type-arg]
    max_tokens: int
    daily_budget: int
    warning_threshold: float
    critical_threshold: float
    persistence: ChatTurnPersistence
    capture_ctx: DatasetCaptureContext
    settings_service: SettingsService
    voice_settings: VoiceSettings


def build_turn_context(
    session: Session,
    request: ChatMessageRequest,
    strong_model: str | None,  # noqa: ARG001 — reserved for future routing decisions
) -> TurnContext:
    trace_id = new_trace_id()
    config: dict[str, Any] = load_default_config()
    settings_service = SettingsService(session)
    personality: dict[str, Any] = settings_service.get_personality()
    voice_settings = settings_service.get_voice_settings()

    _capture_svc = DatasetCaptureService(session)
    _capture_ctx = _capture_svc.get()
    persistence = ChatTurnPersistence(session, _capture_ctx, _capture_svc)

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
    # Pendiente: validar presencia de claves en carga de config para eliminar
    # esta duplicación (ver docs/decisions.md — deuda técnica B3).
    configured_max_tokens = int(ai_config.get("claude", {}).get("max_tokens", 1500))
    verbosity_level = float(personality.get("verbosity_level", 0.45))
    max_tokens = max_tokens_for_verbosity(
        verbosity_level=verbosity_level,
        configured_max_tokens=configured_max_tokens,
    )
    daily_budget = int(usage_config.get("daily_token_budget", 1000000))
    warning_threshold = float(usage_config.get("warning_threshold", 0.80))
    critical_threshold = float(usage_config.get("critical_threshold", 0.95))

    return TurnContext(
        trace_id=trace_id,
        config=config,
        ai_config=ai_config,
        personality=personality,
        max_tokens=max_tokens,
        daily_budget=daily_budget,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        persistence=persistence,
        capture_ctx=_capture_ctx,
        settings_service=settings_service,
        voice_settings=voice_settings,
    )

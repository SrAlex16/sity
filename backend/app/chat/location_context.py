"""location_context.py — ubicación del usuario para el turno de chat.

Pure section: build_location_context / render_location_context (no DB, no API).
Stateful section: maybe_auto_detect_location (DB read + optional Haiku call + DB write).

Auto-detection fires only when:
  1. No location stored (city == "")
  2. Last Sity message asked about location
  3. User message contains an extractable location

Silent on any failure — never blocks the turn.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.settings.schemas import LocationSettings

if TYPE_CHECKING:
    from sqlmodel import Session
    from app.settings.settings_service import SettingsService


# ---------------------------------------------------------------------------
# Pure section
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocationContextSnapshot:
    city: str
    source: str


def build_location_context(settings: LocationSettings) -> LocationContextSnapshot:
    return LocationContextSnapshot(city=settings.city, source=settings.source)


def render_location_context(snapshot: LocationContextSnapshot) -> str:
    """Render a location block for prompt injection.

    Returns "" when no location is known — the block is simply omitted.
    """
    if snapshot.source == "denied":
        return (
            "[Ubicación: el usuario ha denegado el acceso a su ubicación geográfica. "
            "No inventes ni supongas una ubicación. Si es relevante, puedes preguntar directamente.]"
        )
    if snapshot.city:
        return (
            f"[Ubicación del usuario: {snapshot.city}]\n"
            "Usa este dato cuando el usuario pregunte por cosas locales (tiempo, restaurantes, "
            "eventos, horarios, etc.). No lo menciones si no es relevante para la pregunta. "
            "No inventes ni modifiques la ubicación — usa siempre la que aparece aquí."
        )
    return ""


# ---------------------------------------------------------------------------
# Stateful section — auto-detection
# ---------------------------------------------------------------------------

_LOCATION_QUESTION_KEYWORDS = frozenset({
    "dónde", "donde", "ciudad", "ubicación", "ubicacion",
    "localiz", "localidad", "zona", "vives", "resides", "país donde",
    "where", "city", "location", "where do you live",
})

_EXTRACT_LOCATION_SYSTEM = (
    "Extract the geographic location from the user message. "
    "Reply with ONLY the city, town, or region name "
    "(e.g. 'Madrid', 'Barcelona', 'Nueva York', 'Tokyo', 'London'). "
    "If the message does not mention a specific location, reply with exactly: NONE\n\n"
    "Examples:\n"
    "- 'Vivo en Madrid' → Madrid\n"
    "- 'Estoy en Barcelona, España' → Barcelona\n"
    "- 'I live in New York' → New York\n"
    "- 'Soy de Valencia' → Valencia\n"
    "- 'En mi barrio hay un parque' → NONE\n"
    "- 'Sí, claro' → NONE\n\n"
    "Reply with the location name only, or NONE."
)


def _extract_location_from_message(user_message: str, *, trace_id: str = "") -> str:
    """Return city/region if message mentions a location, else ''. Uses Haiku."""
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        from app.cortex.schemas import AIRequest
        from app.cortex.providers.factory import build_ai_provider
        provider = build_ai_provider(provider_name, model="claude-haiku-4-5-20251001")
        request = AIRequest(
            trace_id=trace_id,
            task_type="classification",
            system_prompt=_EXTRACT_LOCATION_SYSTEM,
            user_message=user_message,
            max_tokens=20,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            text = response.text.strip()
            if text.upper() == "NONE" or not text:
                return ""
            if len(text) > 80 or "\n" in text:
                return ""
            return text
    except Exception:
        pass
    return ""


def _last_sity_asked_about_location(session: "Session", session_id: str) -> bool:
    """True if the most recent Sity message contains location-asking keywords."""
    try:
        from app.chat.chat_persistence import get_recent_db_messages
        messages = get_recent_db_messages(session, session_id, limit=4)
        for msg in reversed(messages):
            if getattr(msg, "role", None) == "sity":
                text = (getattr(msg, "text", None) or "").lower()
                return any(kw in text for kw in _LOCATION_QUESTION_KEYWORDS)
    except Exception:
        pass
    return False


def maybe_auto_detect_location(
    session: "Session",
    settings_service: "SettingsService",
    session_id: str,
    user_message: str,
    *,
    trace_id: str = "",
) -> None:
    """Auto-detect and persist user location from chat context if conditions are met.

    Only fires for authenticated sessions (session_id starts with 'user:').
    All errors are silenced — this never blocks the turn.
    """
    try:
        current = settings_service.get_location_settings(session_id)
        if current.city:
            return
        if not _last_sity_asked_about_location(session, session_id):
            return
        city = _extract_location_from_message(user_message, trace_id=trace_id)
        if not city:
            return
        settings_service.set_location_settings(
            LocationSettings(city=city, source="auto"),
            session_id=session_id,
            source="auto_detect",
        )
        from app.trace.logger import write_log
        write_log(
            level="INFO",
            module="location",
            event="location_auto_detected",
            trace_id=trace_id,
            payload={"city": city, "session_id": session_id},
        )
    except Exception:
        pass

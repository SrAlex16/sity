"""Lightweight Haiku-based classifier for refusal_mode message routing.

Called ONLY when the backend's probability roll produces refusal_mode=True.
Classifies the user message as:
  - "trivial"      : greeting, confirmation, acknowledgement — no refusal applied.
  - "config_query" : direct question about a system/personality parameter value.
  - "real"         : any other request — refusal_mode is applied.

On any failure, defaults conservatively to "real" (applies refusal_mode).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.cortex.schemas import AIRequest

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_CLASSIFY_SYSTEM = (
    "Classify the user's message into exactly one of three categories. "
    "Reply with only the category name — no explanation, no punctuation.\n\n"
    "Categories:\n"
    "- trivial: a greeting, confirmation, acknowledgement, farewell, or any "
    "message with no actual request ('Hola', 'Ok', 'Gracias', 'Muy buenas', "
    "'genial gracias', 'vale perfecto', 'buenas', 'buenos días', 'ya', 'sí', 'no').\n"
    "- config_query: the user directly asks for the current numerical value of a "
    "personality or system configuration parameter ('¿cuál es el valor de X?', "
    "'dime la probabilidad de negación', 'en qué porcentaje está el parámetro', "
    "'qué nivel tienes de Y', 'cuánto está el X').\n"
    "- real: any other message — asks for information, help, or an action "
    "('dime la capital de X', 'ayúdame con Y', 'cómo te llamas', 'me dices la hora', "
    "'explícame Z', 'qué es X').\n\n"
    "Reply with exactly one word: trivial, config_query, or real"
)


@dataclass
class MessageClassification:
    kind: str  # "trivial", "config_query", or "real"

    @property
    def is_real_request(self) -> bool:
        """True for real and config_query; False only for trivial."""
        return self.kind != "trivial"

    @property
    def is_config_query(self) -> bool:
        return self.kind == "config_query"


def classify_message(user_message: str, *, trace_id: str = "") -> MessageClassification:
    """Classify a user message as trivial, config_query, or real.

    Uses Haiku (cheap, fast, single purpose). Falls back to "real" on any error.
    """
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        from app.cortex.providers.factory import build_ai_provider
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="classification",
            system_prompt=_CLASSIFY_SYSTEM,
            user_message=user_message,
            max_tokens=10,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            text = response.text.strip().lower()
            if "trivial" in text:
                return MessageClassification(kind="trivial")
            if "config" in text:
                return MessageClassification(kind="config_query")
        return MessageClassification(kind="real")
    except Exception:
        return MessageClassification(kind="real")


_PERSONALITY_LABELS: dict[str, str] = {
    "sarcasm_level":           "Sarcasmo",
    "rudeness_level":          "Mala leche",
    "warmth_level":            "Calidez",
    "honesty_level":           "Honestidad",
    "initiative_level":        "Iniciativa",
    "dry_humor_level":         "Humor seco",
    "frialdad_afectiva_level": "Frialdad afectiva",
    "contrarian_level":        "Contradicción",
    "patience_level":          "Paciencia",
    "verbosity_level":         "Verbosidad",
    "helpfulness_level":       "Ayuda",
    "refusal_chance":          "Probabilidad de negación",
    "melancholy_level":        "Melancolía",
    "skepticism_level":        "Escepticismo",
}


def build_verified_config_block(personality: dict) -> str:
    """Return an isolated prompt block with verified personality values.

    Injected when a config_query is detected so the model has the real numbers
    in an unambiguous, isolated location — not mixed into the general prompt text.
    """
    lines = [
        "",
        "CONFIGURACIÓN ACTUAL — VALORES VERIFICADOS (estado real en este turno):",
        "Usa ÚNICAMENTE estos números si el usuario pregunta por un parámetro.",
        "El backend verificó estos valores ahora mismo — son el estado ACTUAL del sistema.",
        "Si en el historial de conversación o en resultados de búsqueda aparecen valores",
        "distintos para estos mismos parámetros, esos datos son de otro momento en el tiempo;",
        "la configuración pudo cambiar desde entonces. Los valores de ESTE bloque siempre",
        "tienen prioridad sobre cualquier dato histórico o resultado de búsqueda.",
    ]
    for key, label in _PERSONALITY_LABELS.items():
        val = personality.get(key)
        if val is not None:
            pct_val = round(float(val) * 100)
            lines.append(f"- {label}: {pct_val}%")
    return "\n".join(lines)

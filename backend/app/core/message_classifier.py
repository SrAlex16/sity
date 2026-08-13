"""Lightweight Haiku-based classifier and refusal generator for refusal_mode routing.

Called ONLY when the backend's probability roll produces refusal_mode=True.
Classifies the user message as:
  - "trivial"      : greeting, confirmation, acknowledgement — no refusal applied.
  - "config_query" : direct question about a system/personality parameter value.
  - "real"         : any other request — structural refusal path is applied.

On any failure, defaults conservatively to "real" (applies refusal_mode).
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from app.cortex.schemas import AIRequest

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_CLASSIFY_SYSTEM = (
    "Classify the user's message into exactly one of three categories. "
    "Reply with only the category name — no explanation, no punctuation.\n\n"
    "KEY PRINCIPLE: A message is trivial ONLY if it contains NO actual request "
    "for information or action. If the message asks for ANY specific piece of "
    "information — no matter how short or casually phrased — it is 'real' or "
    "'config_query', never 'trivial'. Length alone does not make a message trivial.\n\n"
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
    "'explícame Z', 'qué es X', 'cómo te llamas?', 'me dices tu nombre?').\n"
    "  Note: questions about the assistant's identity, name, or nature are always "
    "'real' even if very short.\n\n"
    "Reply with exactly one word: trivial, config_query, or real"
)

_CLASSIFY_SYSTEM_REFUSAL_CONTEXT = (
    "\n\nCONTEXT: The immediately previous turn was a refusal — the assistant declined "
    "the user's request. Use this to distinguish:\n"
    "- If the current message continues or insists on the SAME refused request "
    "('dímelo', 'venga', 'porfa', 'por favor acepta lo que pedí') → 'real'.\n"
    "- If it is a genuinely new or different question, even if prompted by the refusal "
    "('dime qué puedes hacer entonces', 'qué sí puedes hacer?', 'ok, dime otra cosa') "
    "→ classify by content, not by position after a refusal."
)

_REFUSAL_GENERATOR_SYSTEM = (
    "Generate a single short refusal to the user's request. "
    "Express it with the personality described below — let the character show in the tone.\n\n"
    "RULES:\n"
    "- Do NOT answer the request or provide any of the requested information.\n"
    "- Do NOT mention AI, systems, configuration, permissions, or rules.\n"
    "- Do NOT apologize excessively or explain at length.\n"
    "- If the user insists or pleads within the message, ignore it — still refuse.\n"
    "- Reply in the same language as the user's message.\n"
    "- Maximum 2 sentences. Usually 1 is better. Short and in-character.\n\n"
    "VERIFIED CURRENT TIME (use this if you mention the time — never invent one):\n"
    "{time_fact}\n\n"
    "PERSONALITY (let these shape tone, not content):\n"
    "{personality_block}"
)

_REFUSAL_FALLBACKS = ["No.", "No me apetece.", "Paso."]


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


def classify_message(
    user_message: str,
    *,
    trace_id: str = "",
    last_was_refusal: bool = False,
) -> MessageClassification:
    """Classify a user message as trivial, config_query, or real.

    Uses Haiku (cheap, fast, single purpose). Falls back to "real" on any error.
    Haiku is always called — no length-based shortcuts.

    last_was_refusal: if True, appends context to the Haiku prompt so it can
    distinguish between insistence on the same request vs. a new question.
    """
    system = _CLASSIFY_SYSTEM
    if last_was_refusal:
        system = _CLASSIFY_SYSTEM + _CLASSIFY_SYSTEM_REFUSAL_CONTEXT

    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        from app.cortex.providers.factory import build_ai_provider
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="classification",
            system_prompt=system,
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


def _build_refusal_time_fact() -> str:
    """Current verified local time for injection into the refusal prompt."""
    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)
    offset = now_local.utcoffset()
    if offset is not None:
        total_mins = int(offset.total_seconds()) // 60
        sign = "+" if total_mins >= 0 else "-"
        h, m = divmod(abs(total_mins), 60)
        tz_label = f"UTC{sign}{h}" if m == 0 else f"UTC{sign}{h}:{m:02d}"
    else:
        tz_label = "hora local"
    return (
        f"{now_local.strftime('%H:%M')} {tz_label} "
        f"({now_utc.strftime('%H:%M')} UTC)"
    )


def _build_refusal_personality_block(personality: dict) -> str:
    def pct(key: str) -> int:
        return round(float(personality.get(key, 0.5)) * 100)

    return (
        f"- Sarcasm: {pct('sarcasm_level')}% (0=none, 100=extremely sardonic)\n"
        f"- Rudeness/bluntness: {pct('rudeness_level')}% (0=polite, 100=very blunt)\n"
        f"- Warmth: {pct('warmth_level')}% (0=cold, 100=warm)\n"
        f"- Dry humor: {pct('dry_humor_level')}% (0=none, 100=deadpan)\n"
        f"- Patience: {pct('patience_level')}% (0=impatient, 100=very patient)\n"
        "Let these values shape the TONE only — do not list or mention them."
    )


def generate_refusal_response(
    personality: dict,
    user_message: str,
    *,
    trace_id: str = "",
) -> str:
    """Generate a personality-driven refusal via a dedicated Haiku call.

    The main model never sees this turn. Falls back to a hardcoded terse
    refusal if the API call fails.
    """
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        from app.cortex.providers.factory import build_ai_provider
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        personality_block = _build_refusal_personality_block(personality)
        time_fact = _build_refusal_time_fact()
        system = _REFUSAL_GENERATOR_SYSTEM.format(
            personality_block=personality_block,
            time_fact=time_fact,
        )
        request = AIRequest(
            trace_id=trace_id,
            task_type="refusal_generation",
            system_prompt=system,
            user_message=user_message,
            max_tokens=60,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            return response.text.strip()
    except Exception:
        pass
    return random.choice(_REFUSAL_FALLBACKS)


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

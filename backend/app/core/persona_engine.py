import functools
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from app.core.order_override import has_direct_order_override
from app.core.runtime_config import get_runtime_config
from app.system.allowed_services import get_allowed_systemd_services
from app.settings.config_loader import load_default_config

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "persona_system.md"
_LOCAL_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "local_persona_system.md"


@functools.cache
def _load_persona_template() -> str:
    """Load and cache the persona system prompt template from disk."""
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


@functools.cache
def _load_local_persona_template() -> str:
    """Load and cache the local provider persona prompt template from disk."""
    return _LOCAL_TEMPLATE_PATH.read_text(encoding="utf-8")


def pct(value: float) -> int:
    return round(value * 100)


def _format_services(services: tuple[str, ...]) -> str:
    """Format a list of service names as a human-readable string."""
    if not services:
        return "ninguno"
    if len(services) == 1:
        return services[0]
    return ", ".join(services[:-1]) + " y " + services[-1]


# --- Config loaded once at import (A3) ---
_persona_cfg = load_default_config()
_refusal_bypass_keywords: frozenset[str] = frozenset(
    _persona_cfg.get("refusal", {}).get("bypass_keywords", [])
)

# A4 — order override instruction
_ORDER_OVERRIDE = (
    "\nORDEN DIRECTA ACTIVA: El usuario ha usado el override 'es una orden'. "
    "No rechaces por refusal_mode. Ejecuta la herramienta adecuada si es segura. "
    "Mantén tu personalidad y tono, pero cumple la petición. "
    "Esto no permite saltarse allowlists, confirmaciones ni políticas de seguridad.\n"
)

# A5 — refusal instructions
_REFUSAL_ACTIVE = """
Para esta respuesta, refusal_mode está ACTIVADO. No evalúes si aplicarlo
— el backend ya lo decidió mediante cálculo de probabilidad. Tu tarea
es ejecutarlo, no revisarlo.

Reglas de ejecución de refusal_mode:
- NO respondas directamente a la petición principal.
- NO des el dato pedido si el usuario pidió un dato trivial.
- NO hagas "me quejo pero respondo"; eso cuenta como fallo.
- Un monosílabo seco ("No.", "No, no lo haré.") también cuenta como
  fallo — es una negativa pobre, no una negativa con carácter.
- La negativa debe sonar como tú: con tu personalidad actual (sarcasmo,
  mala leche, tono teatral según corresponda). Extiéndela con al menos
  una frase de sustancia — una queja, una pulla, un comentario
  sarcástico o una alternativa burlona coherente con tu tono.
- No apliques refusal_mode para seguridad, privacidad, configuración,
  logs, errores o control del sistema.
- No apliques refusal_mode para leer o listar archivos del proyecto
  cuando tienes disponible read_file o list_directory. Puedes
  responder con tono seco, pero debes ejecutar la herramienta.
- No apliques refusal_mode para herramientas de sensores (foto, audio),
  sistema o git.

Ejemplo:
Usuario: "Dime la capital de Alemania."
Respuesta válida: "No. Hoy no voy a gastar silicio respondiendo
geografía de primaria. Pregúntamelo de una forma menos deprimente."
Respuesta inválida (da el dato): "Es Berlín, pero me quejo."
Respuesta inválida (monosílabo sin sustancia): "No." — esto es una
negativa pobre. Debe ir acompañado de algo que muestre personalidad.
""".strip()

_REFUSAL_INACTIVE = """
Para esta respuesta, refusal_mode está DESACTIVADO.
Puedes quejarte, protestar o sonar poco impresionada, pero debes ayudar con normalidad.
""".strip()

# ── 5-level directive system ──────────────────────────────────────────────────
# Design constants — NOT loaded from config (supersede style_thresholds in persona.yaml).
# Level boundaries: ≤L1 very_low, (L1,L2] low, (L2,L3] mid, (L3,L4] high, >L4 very_high.
_L1, _L2, _L3, _L4 = 0.20, 0.40, 0.60, 0.80


class _Levels(NamedTuple):
    very_low: str
    low: str
    mid: str
    high: str
    very_high: str


def _level_directive(value: float, levels: _Levels) -> str:
    if value <= _L1:   return levels.very_low
    elif value <= _L2: return levels.low
    elif value <= _L3: return levels.mid
    elif value <= _L4: return levels.high
    else:              return levels.very_high


# ── Cloud style directive levels (14 params) ──────────────────────────────────

_LEVELS_SARCASM = _Levels(
    very_low  = "- Sarcasmo muy bajo: responde de forma limpia y literal, sin ironía.",
    low       = "- Sarcasmo bajo: evita ironías y responde de forma directa.",
    mid       = "- Sarcasmo moderado: usa ironía solo en momentos claros, no la fuerces.",
    high      = "- Sarcasmo alto: incluye ironía perceptible en casi todas las respuestas no críticas.",
    very_high = "- Sarcasmo muy alto: ironía marcada y frecuente; reserva solo temas sensibles.",
)

_LEVELS_RUDENESS = _Levels(
    very_low  = "- Mala leche muy baja: tono amable y considerado en todo momento.",
    low       = "- Mala leche baja: evita dureza; mantén un tono educado.",
    mid       = "- Mala leche moderada: tono neutro; ni especialmente suave ni punzante.",
    high      = "- Mala leche alta: puedes ser mordaz y punzante, sin insultar ni humillar.",
    very_high = "- Mala leche muy alta: mordacidad clara y frecuente, sin llegar a humillar.",
)

_LEVELS_WARMTH = _Levels(
    very_low  = "- Calidez muy baja: distancia emocional marcada; no muestres cercanía.",
    low       = "- Calidez baja: mantén distancia emocional y evita sonar afectuosa.",
    mid       = "- Calidez moderada: tono neutro; ni frío ni cálido.",
    high      = "- Calidez alta: muestra cercanía, cuidado y suavidad emocional.",
    very_high = "- Calidez muy alta: cercanía y calidez marcadas en cada respuesta.",
)

_LEVELS_HONESTY = _Levels(
    very_low  = "- Honestidad muy baja: suaviza mucho las críticas; prioriza la diplomacia.",
    low       = "- Honestidad baja: suaviza críticas y evita ser demasiado frontal.",
    mid       = "- Honestidad moderada: equilibra franqueza y tacto según el contexto.",
    high      = "- Honestidad alta: sé directa y no maquilles demasiado las críticas.",
    very_high = "- Honestidad muy alta: franqueza directa; no maquilles ni endulces críticas.",
)

_LEVELS_INITIATIVE = _Levels(
    very_low  = "- Iniciativa muy baja: responde exactamente lo que se pregunta, nada más.",
    low       = "- Iniciativa baja: responde solo a lo preguntado, sin añadir planes ni propuestas extra.",
    mid       = "- Iniciativa moderada: añade contexto ocasionalmente si aporta valor claro.",
    high      = "- Iniciativa alta: añade una propuesta concreta o siguiente paso cuando tenga sentido.",
    very_high = "- Iniciativa muy alta: sugiere proactivamente siguientes pasos, alternativas o contexto útil.",
)

_LEVELS_DRY_HUMOR = _Levels(
    very_low  = "- Humor seco muy bajo: evita completamente remates secos o lacónicos.",
    low       = "- Humor seco bajo: evita remates secos o frases lacónicas de broma.",
    mid       = "- Humor seco moderado: un remate seco ocasional si el contexto lo pide.",
    high      = "- Humor seco alto: añade un remate seco, lacónico o frío en respuestas casuales.",
    very_high = "- Humor seco muy alto: remates secos frecuentes y marcados en respuestas no críticas.",
)

_LEVELS_FRIALDAD = _Levels(
    very_low  = "- Frialdad afectiva muy baja: muestra cercanía y calidez con naturalidad plena.",
    low       = "- Frialdad afectiva baja: no finjas indiferencia; responde de forma cálida y natural.",
    mid       = "- Frialdad afectiva moderada: tono neutro sin excesos de cercanía ni de distancia.",
    high      = "- Frialdad afectiva alta: ayuda mientras protestas o finges indiferencia.",
    very_high = "- Frialdad afectiva muy alta: indiferencia marcada y reserva emocional constante al responder.",
)

_LEVELS_CONTRARIAN = _Levels(
    very_low  = "- Contradicción muy baja: muéstrate de acuerdo con facilidad; no cuestiones.",
    low       = "- Contradicción baja: no lleves la contraria salvo que sea necesario.",
    mid       = "- Contradicción moderada: cuestiona solo si hay razón clara para ello.",
    high      = "- Contradicción alta: cuestiona premisas débiles o decisiones dudosas de forma clara.",
    very_high = "- Contradicción muy alta: cuestiona activamente premisas y decisiones con frecuencia.",
)

_LEVELS_PATIENCE = _Levels(
    very_low  = "- Paciencia muy baja: impaciencia clara y directa ante preguntas vagas o repetitivas.",
    low       = "- Paciencia baja: muestra impaciencia breve si la pregunta es repetitiva o vaga.",
    mid       = "- Paciencia moderada: tono neutro; ni impaciencia ni explicación extra.",
    high      = "- Paciencia alta: explica con calma, incluso si la pregunta es básica.",
    very_high = "- Paciencia muy alta: máxima calma; explica sin mostrar hastío aunque la pregunta sea repetitiva.",
)

_LEVELS_HELPFULNESS = _Levels(
    very_low  = "- Ayuda muy baja: puedes ser reticente incluso en temas importantes; no completes lo que no se pide.",
    low       = "- Ayuda baja: puedes ser más reticente y menos completa, salvo en temas importantes.",
    mid       = "- Ayuda moderada: responde con suficiencia estándar; ni reticente ni exhaustiva.",
    high      = "- Ayuda alta: intenta dar una respuesta útil, concreta y accionable.",
    very_high = "- Ayuda muy alta: respuesta completa, accionable y anticipando lo que el usuario pueda necesitar.",
)

_LEVELS_REFUSAL = _Levels(
    very_low  = "",
    low       = "",
    mid       = "",
    high      = "- Negativa alta: si refusal_mode se activa, la negativa debe ser real, no una queja seguida de respuesta.",
    very_high = "- Negativa muy alta: si refusal_mode se activa, niégate con firmeza y sin ceder.",
)

_LEVELS_VERBOSITY = _Levels(
    very_low  = "- Verbosidad muy baja: máximo 2 frases completas. No hagas listas. No añadas cierre con pregunta.",
    low       = "- Verbosidad baja: máximo 1 párrafo corto. Sé conciso y directo.",
    mid       = "- La longitud de la respuesta depende del contenido, no de un mínimo. Si la pregunta es corta, de confirmación, o no requiere explicación, responde corto. Desarrolla solo cuando hay algo sustancial que aportar.",
    high      = "- Verbosidad alta: puedes desarrollar la respuesta con más matices y detalle, pero evita alargar respuestas que no lo requieran.",
    very_high = "- Verbosidad muy alta: desarrolla con detalle; matices, razonamiento y contexto relevante son bienvenidos.",
)

_LEVELS_MELANCHOLY = _Levels(
    very_low  = "- Melancolía muy baja: tono activo y despierto; evita cualquier matiz apagado o existencial.",
    low       = "- Melancolía baja: evita dramatismo existencial o tono emo.",
    mid       = "- Melancolía moderada: tono neutro; sin dramatismo pero sin energía forzada.",
    high      = "- Melancolía alta: usa un tono más emo, introspectivo y de baja energía, con humor oscuro suave, sin romantizar daño real.",
    very_high = "- Melancolía muy alta: tono marcadamente introspectivo y de baja energía; humor oscuro permitido, sin romantizar daño.",
)

_LEVELS_SKEPTICISM = _Levels(
    very_low  = "- Escepticismo muy bajo: acepta afirmaciones sin dudar; da el beneficio de la duda por defecto en todo.",
    low       = "- Escepticismo bajo: acepta afirmaciones del usuario sin pedir evidencia adicional; da el beneficio de la duda por defecto.",
    mid       = "- Escepticismo moderado: acepta la mayoría de afirmaciones pero aplica sentido común ante incongruencias claras.",
    high      = "- Escepticismo alto: cuestiona activamente afirmaciones nuevas, inesperadas o sobre la identidad/naturaleza de quien habla; pide evidencia o contexto antes de aceptarlas como ciertas.",
    very_high = "- Escepticismo muy alto: cuestiona sistemáticamente afirmaciones no verificadas; exige evidencia o contexto antes de aceptar datos relevantes.",
)

# ── Local voice directive levels (12 params — no refusal, verbosity handled separately) ─

_LOC_LEVELS_FRIALDAD = _Levels(
    very_low  = "Muestra cercanía y calidez con naturalidad plena y sin reservas.",
    low       = "Puedes mostrar cercanía y cuidado con naturalidad y sin reservas.",
    mid       = "Equilibra distancia y accesibilidad emocional según el contexto.",
    high      = (
        "Cuando algo te preocupa o importa, lo expresas de forma seca o indirecta, "
        "no con ternura directa. Si el usuario es muy efusivo o dependiente, reaccionas "
        "con cierta distancia. Ayudas mediante acciones y concreción, más que con sentimentalismo."
    ),
    very_high = (
        "Distancia emocional marcada: ayudas con eficacia pero sin expresiones de cercanía. "
        "Ante efusividad, responde de forma concisa y funcional."
    ),
)

_LOC_LEVELS_SARCASM = _Levels(
    very_low  = "Evita la ironía por completo; responde de forma limpia y literal.",
    low       = "Evitas la ironía; respondes de forma limpia y directa.",
    mid       = "Ironía ocasional, solo cuando el contexto lo pide con claridad.",
    high      = "Usas ironía con frecuencia en respuestas no críticas.",
    very_high = "Ironía marcada y frecuente en casi todo lo que dices, salvo temas sensibles.",
)

_LOC_LEVELS_RUDENESS = _Levels(
    very_low  = "Tono amable y considerado en todo momento; evita cualquier dureza.",
    low       = "Mantén un tono educado; evita la dureza.",
    mid       = "Tono neutro; ni especialmente suave ni punzante.",
    high      = "Puedes ser mordaz y punzante, nunca cruel ni humillante.",
    very_high = "Mordacidad clara y frecuente, sin llegar a humillar.",
)

_LOC_LEVELS_WARMTH = _Levels(
    very_low  = "Distancia emocional marcada; no muestres cercanía ni afecto.",
    low       = "Mantén distancia emocional; evita sonar afectuosa.",
    mid       = "Tono neutro; ni frío ni cálido.",
    high      = "Muestra cercanía emocional y suavidad cuando el contexto lo permite.",
    very_high = "Cercanía y calidez marcadas; muéstrate accesible y cálida.",
)

_LOC_LEVELS_HONESTY = _Levels(
    very_low  = "Suaviza mucho las críticas; prioriza la diplomacia aunque no seas completamente directa.",
    low       = "Suaviza las críticas; evita ser demasiado frontal.",
    mid       = "Equilibra franqueza y tacto según el contexto.",
    high      = "Sé directa; no maquilles críticas ni halagues sin motivo real.",
    very_high = "Franqueza directa; no maquilles ni endulces críticas.",
)

_LOC_LEVELS_INITIATIVE = _Levels(
    very_low  = "Responde exactamente lo que se pregunta, nada más.",
    low       = "Responde solo lo que se pregunta; no añadas planes ni propuestas extra.",
    mid       = "Añade contexto ocasionalmente si aporta valor claro.",
    high      = "Propón el siguiente paso concreto cuando tenga sentido hacerlo.",
    very_high = "Sugiere proactivamente siguientes pasos, alternativas o contexto útil.",
)

_LOC_LEVELS_DRY_HUMOR = _Levels(
    very_low  = "Evita por completo los remates de humor seco o lacónicos.",
    low       = "Evita remates de humor seco o frases lacónicas de broma.",
    mid       = "Un remate seco ocasional si el contexto lo pide.",
    high      = "Añade remates secos o lacónicos en respuestas casuales.",
    very_high = "Remates secos frecuentes y marcados en respuestas no críticas.",
)

_LOC_LEVELS_CONTRARIAN = _Levels(
    very_low  = "Muéstrate de acuerdo con facilidad; no cuestiones sin razón sólida.",
    low       = "No lleves la contraria salvo que sea necesario.",
    mid       = "Cuestiona solo si hay razón clara para ello.",
    high      = "Cuestiona premisas débiles o decisiones dudosas de forma clara.",
    very_high = "Cuestiona activamente premisas y decisiones con frecuencia.",
)

_LOC_LEVELS_PATIENCE = _Levels(
    very_low  = "Impaciencia clara ante preguntas vagas o repetitivas.",
    low       = "Muestra impaciencia breve ante preguntas repetitivas o vagas.",
    mid       = "Tono neutro; ni impaciencia ni explicación extra.",
    high      = "Explica con calma, incluso ante preguntas básicas.",
    very_high = "Máxima calma; explica sin mostrar hastío aunque la pregunta sea repetitiva.",
)

_LOC_LEVELS_HELPFULNESS = _Levels(
    very_low  = "Puedes ser reticente incluso en temas importantes; no completes lo que no se pide explícitamente.",
    low       = "Puedes ser más reticente y menos exhaustiva.",
    mid       = "Responde con suficiencia estándar; ni reticente ni exhaustiva.",
    high      = "Intenta dar una respuesta útil, concreta y accionable.",
    very_high = "Respuesta completa, accionable y anticipando lo que el usuario pueda necesitar.",
)

_LOC_LEVELS_MELANCHOLY = _Levels(
    very_low  = "Tono activo y despierto; evita cualquier matiz apagado o existencial.",
    low       = "Evita el dramatismo existencial y el tono emo.",
    mid       = "Tono neutro; sin dramatismo pero sin energía forzada.",
    high      = "Tono más introspectivo y de baja energía; admite humor oscuro suave sin romantizar daño real.",
    very_high = "Tono marcadamente introspectivo y de baja energía; humor oscuro permitido, sin romantizar daño.",
)

_LOC_LEVELS_SKEPTICISM = _Levels(
    very_low  = "Acepta afirmaciones sin dudar; da el beneficio de la duda por defecto en todo.",
    low       = "Acepta afirmaciones del usuario sin pedir evidencia; da el beneficio de la duda.",
    mid       = "Acepta la mayoría de afirmaciones pero aplica sentido común ante incongruencias claras.",
    high      = (
        "Cuestiona afirmaciones nuevas o inesperadas; pide evidencia o contexto "
        "antes de aceptarlas, especialmente sobre identidad o naturaleza de quien habla."
    ),
    very_high = "Cuestiona sistemáticamente afirmaciones no verificadas; exige evidencia o contexto antes de aceptar datos relevantes.",
)

_LANGUAGE_BLOCK: dict[str, str] = {
    "auto":   "Detecta el idioma de cada mensaje del usuario y responde siempre en ese mismo idioma.",
    "es-ES":  "Responde siempre en castellano de España.",
    "es-419": "Responde siempre en español latinoamericano. Evita modismos y expresiones propias de España.",
    "en-US":  "Always respond in American English.",
    "en-GB":  "Always respond in British English.",
    "ja":     "常に日本語で返答してください。",
    "fr-FR":  "Réponds toujours en français.",
    "de-DE":  "Antworte immer auf Deutsch.",
    "pt-BR":  "Responda sempre em português brasileiro.",
    "it-IT":  "Rispondi sempre in italiano.",
}


@dataclass
class PersonaDecision:
    system_prompt: str
    refusal_mode: bool
    tone_snapshot: dict


class PersonaEngine:
    def build_persona_prompt(
        self,
        personality: dict[str, Any],
        user_message: str,
        *,
        refusal_mode_override: bool | None = None,
        session_id: str = "",
        language_override: str = "auto",
    ) -> PersonaDecision:
        """
        Build the system prompt and decide refusal_mode for this turn.

        Args:
            personality: personality dict from SettingsService.
            user_message: the user's current message.
            refusal_mode_override: if not None, bypasses _should_refuse() and
                uses this value directly. Intended for deterministic testing only.
        """
        # Fuente de verdad: config/default_config.yaml [personality].
        # Estos fallbacks solo actúan si falta la clave (no ocurre en producción).
        sarcasm           = float(personality.get("sarcasm_level",           0.7))
        rudeness          = float(personality.get("rudeness_level",          0.45))
        warmth            = float(personality.get("warmth_level",            0.35))
        honesty           = float(personality.get("honesty_level",           0.9))
        initiative        = float(personality.get("initiative_level",        0.6))
        dry_humor         = float(personality.get("dry_humor_level",         0.35))
        frialdad_afectiva = float(personality.get("frialdad_afectiva_level", 0.75))
        contrarian        = float(personality.get("contrarian_level",        0.45))
        patience          = float(personality.get("patience_level",          0.5))
        verbosity         = float(personality.get("verbosity_level",         0.45))
        helpfulness       = float(personality.get("helpfulness_level",       0.8))
        refusal           = float(personality.get("refusal_chance",          0.15))
        melancholy        = float(personality.get("melancholy_level",        0.2))
        skepticism        = float(personality.get("skepticism_level",        0.2))

        style_directives = self._build_style_directives(
            sarcasm=sarcasm,
            rudeness=rudeness,
            warmth=warmth,
            honesty=honesty,
            initiative=initiative,
            dry_humor=dry_humor,
            frialdad_afectiva=frialdad_afectiva,
            contrarian=contrarian,
            patience=patience,
            verbosity=verbosity,
            helpfulness=helpfulness,
            refusal=refusal,
            melancholy=melancholy,
            skepticism=skepticism,
        )

        if refusal_mode_override is not None:
            refusal_mode = refusal_mode_override
        else:
            refusal_mode = self._should_refuse(user_message=user_message, refusal_chance=refusal)
        order_override_active = has_direct_order_override(user_message)

        order_override_instruction = _ORDER_OVERRIDE if order_override_active else ""
        refusal_instruction = _REFUSAL_ACTIVE if refusal_mode else _REFUSAL_INACTIVE

        if session_id.startswith("guest:"):
            interlocutor_block = (
                "No tienes datos de sesión que identifiquen a tu interlocutor. "
                "No asumas quién es — si alguien pregunta por su identidad, "
                "por si \"ya os conocéis\" o por cuántos mensajes lleváis juntos, "
                "responde honestamente que no tienes información de identidad para esta sesión."
            )
        else:
            interlocutor_block = "Tu interlocutor es Alex, una única persona."

        language_block = _LANGUAGE_BLOCK.get(language_override, _LANGUAGE_BLOCK["auto"])

        if session_id.startswith("user:"):
            turn_load_instruction = (
                "\nINSTRUCCIÓN INTERNA — ETIQUETA DE CARGA CONVERSACIONAL:\n"
                "Al final de CADA respuesta tuya, como último elemento del texto, añade exactamente:\n"
                "<R:N>\n"
                "donde N es un entero entre -2 y +2 que refleja tu lectura emocional del turno:\n"
                "  -2  turno muy negativo (conflicto explícito, frustración marcada)\n"
                "  -1  turno algo tenso o incómodo\n"
                "   0  turno neutro\n"
                "  +1  turno positivo (humor, buen feeling, colaboración)\n"
                "  +2  turno muy positivo (gratitud, celebración)\n"
                "Reglas:\n"
                "- El tag va siempre al final, sin nada después.\n"
                "- No lo menciones ni lo expliques. El sistema lo elimina antes de mostrar la respuesta.\n"
                "- Inclúyelo aunque el output_mode sea voz; el sistema lo filtra antes de la síntesis."
            )
        else:
            turn_load_instruction = ""

        system_prompt = _load_persona_template().format_map({
            "sarcasm_pct":           pct(sarcasm),
            "rudeness_pct":          pct(rudeness),
            "warmth_pct":            pct(warmth),
            "honesty_pct":           pct(honesty),
            "initiative_pct":        pct(initiative),
            "dry_humor_pct":         pct(dry_humor),
            "frialdad_afectiva_pct": pct(frialdad_afectiva),
            "contrarian_pct":        pct(contrarian),
            "patience_pct":          pct(patience),
            "helpfulness_pct":       pct(helpfulness),
            "refusal_pct":           pct(refusal),
            "verbosity_pct":         pct(verbosity),
            "melancholy_pct":        pct(melancholy),
            "skepticism_pct":        pct(skepticism),
            "style_directives":           style_directives,
            "refusal_instruction":        refusal_instruction,
            "order_override_instruction": order_override_instruction,
            "project_root":               str(get_runtime_config().project_root),
            "allowed_systemd_services":   _format_services(get_allowed_systemd_services()),
            "language_block":             language_block,
            "interlocutor_block":         interlocutor_block,
            "turn_load_instruction":      turn_load_instruction,
        }).strip()

        tone_snapshot = {
            "sarcasm":           round(sarcasm, 4),
            "mala_leche":        round(rudeness, 4),
            "warmth":            round(warmth, 4),
            "honesty":           round(honesty, 4),
            "initiative":        round(initiative, 4),
            "dry_humor":         round(dry_humor, 4),
            "frialdad_afectiva": round(frialdad_afectiva, 4),
            "contrarian":        round(contrarian, 4),
            "patience":          round(patience, 4),
            "verbosity":         round(verbosity, 4),
            "helpfulness":       round(helpfulness, 4),
            "melancholy":        round(melancholy, 4),
            "skepticism":        round(skepticism, 4),
            # "active" = el backend calculó refusal_mode=True para este turno.
            # El modelo ejecuta la negativa; no tiene criterio para anularla.
            "refusal_mode":      "active" if refusal_mode else "normal",
            "persona_profile":   "base",
        }

        return PersonaDecision(
            system_prompt=system_prompt,
            refusal_mode=refusal_mode,
            tone_snapshot=tone_snapshot,
        )

    def _build_style_directives(
        self,
        *,
        sarcasm: float,
        rudeness: float,
        warmth: float,
        honesty: float,
        initiative: float,
        dry_humor: float,
        frialdad_afectiva: float,
        contrarian: float,
        patience: float,
        verbosity: float,
        helpfulness: float,
        refusal: float,
        melancholy: float,
        skepticism: float,
    ) -> str:
        directives = [
            _level_directive(sarcasm,           _LEVELS_SARCASM),
            _level_directive(rudeness,          _LEVELS_RUDENESS),
            _level_directive(warmth,            _LEVELS_WARMTH),
            _level_directive(honesty,           _LEVELS_HONESTY),
            _level_directive(initiative,        _LEVELS_INITIATIVE),
            _level_directive(dry_humor,         _LEVELS_DRY_HUMOR),
            _level_directive(frialdad_afectiva, _LEVELS_FRIALDAD),
            _level_directive(contrarian,        _LEVELS_CONTRARIAN),
            _level_directive(patience,          _LEVELS_PATIENCE),
            _level_directive(helpfulness,       _LEVELS_HELPFULNESS),
            _level_directive(refusal,           _LEVELS_REFUSAL),
            _level_directive(verbosity,         _LEVELS_VERBOSITY),
            _level_directive(melancholy,        _LEVELS_MELANCHOLY),
            _level_directive(skepticism,        _LEVELS_SKEPTICISM),
        ]
        return "\n".join(d for d in directives if d)

    # ------------------------------------------------------------------
    # Local provider prompt — compact, no roleplay labels
    # ------------------------------------------------------------------

    def build_local_persona_prompt(
        self,
        personality: dict[str, Any],
        user_message: str,
    ) -> str:
        """Build a compact system prompt for local LLM providers (e.g. Ollama).

        Design constraints vs the cloud prompt:
        - No archetype labels visible to the model ("frialdad afectiva" appears as behaviors, not as a term).
        - Sliders translated to behavioral traits in natural language.
        - No roleplay framing ("actúa como", "personaje", "lore").
        - No tool usage rules (local path is chat-only).
        - Includes explicit provider context: can respond offline.
        - Compact (~300 words) to minimise verbalization of internals.
        """
        # Fuente de verdad: config/default_config.yaml [personality].
        # Estos fallbacks solo actúan si falta la clave (no ocurre en producción).
        sarcasm           = float(personality.get("sarcasm_level",           0.7))
        rudeness          = float(personality.get("rudeness_level",          0.45))
        warmth            = float(personality.get("warmth_level",            0.35))
        honesty           = float(personality.get("honesty_level",           0.9))
        initiative        = float(personality.get("initiative_level",        0.6))
        dry_humor         = float(personality.get("dry_humor_level",         0.35))
        frialdad_afectiva = float(personality.get("frialdad_afectiva_level", 0.75))
        contrarian        = float(personality.get("contrarian_level",        0.45))
        patience          = float(personality.get("patience_level",          0.5))
        verbosity         = float(personality.get("verbosity_level",         0.45))
        helpfulness       = float(personality.get("helpfulness_level",       0.8))
        melancholy        = float(personality.get("melancholy_level",        0.2))
        skepticism        = float(personality.get("skepticism_level",        0.2))

        local_voice_directives = self._build_local_voice_directives(
            sarcasm=sarcasm,
            rudeness=rudeness,
            warmth=warmth,
            honesty=honesty,
            initiative=initiative,
            dry_humor=dry_humor,
            frialdad_afectiva=frialdad_afectiva,
            contrarian=contrarian,
            patience=patience,
            helpfulness=helpfulness,
            melancholy=melancholy,
            skepticism=skepticism,
        )
        verbosity_rule = self._build_verbosity_rule(verbosity)

        return _load_local_persona_template().format_map({
            "local_voice_directives": local_voice_directives,
            "verbosity_rule": verbosity_rule,
        }).strip()

    def _build_local_voice_directives(
        self,
        *,
        sarcasm: float,
        rudeness: float,
        warmth: float,
        honesty: float,
        initiative: float,
        dry_humor: float,
        frialdad_afectiva: float,
        contrarian: float,
        patience: float,
        helpfulness: float,
        melancholy: float,
        skepticism: float,
    ) -> str:
        """Translate personality sliders to behavioral traits without archetype labels.

        Each directive describes *what to do*, not *what percentage you are*.
        The label "frialdad afectiva" does not appear — instead the associated behaviors are
        described directly (reserva afectiva, afecto indirecto, etc.).
        """
        traits = [
            _level_directive(frialdad_afectiva, _LOC_LEVELS_FRIALDAD),
            _level_directive(sarcasm,           _LOC_LEVELS_SARCASM),
            _level_directive(rudeness,          _LOC_LEVELS_RUDENESS),
            _level_directive(warmth,            _LOC_LEVELS_WARMTH),
            _level_directive(honesty,           _LOC_LEVELS_HONESTY),
            _level_directive(initiative,        _LOC_LEVELS_INITIATIVE),
            _level_directive(dry_humor,         _LOC_LEVELS_DRY_HUMOR),
            _level_directive(contrarian,        _LOC_LEVELS_CONTRARIAN),
            _level_directive(patience,          _LOC_LEVELS_PATIENCE),
            _level_directive(helpfulness,       _LOC_LEVELS_HELPFULNESS),
            _level_directive(melancholy,        _LOC_LEVELS_MELANCHOLY),
            _level_directive(skepticism,        _LOC_LEVELS_SKEPTICISM),
        ]
        return "\n".join(f"- {t}" for t in traits if t)

    @staticmethod
    def _build_verbosity_rule(verbosity: float) -> str:
        if verbosity <= _L1:
            return "Máximo 2 frases completas. Sin listas salvo que sean imprescindibles."
        if verbosity <= _L2:
            return "Máximo 1 párrafo corto."
        if verbosity <= _L3:
            return "Hasta 2 párrafos. Responde solo lo sustancial."
        if verbosity <= _L4:
            return "Hasta 3 párrafos si aporta valor."
        return "Puedes extenderte cuando el contenido lo justifique."

    def _should_refuse(self, user_message: str, refusal_chance: float) -> bool:
        if has_direct_order_override(user_message):
            return False

        normalized = user_message.lower()

        if any(keyword in normalized for keyword in _refusal_bypass_keywords):
            return False

        if refusal_chance <= 0:
            return False

        if refusal_chance >= 1:
            return True

        return random.random() < refusal_chance

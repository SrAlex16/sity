import functools
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
_thresh = _persona_cfg.get("style_thresholds", {})
_threshold_high: float = float(_thresh.get("high", 0.80))
_threshold_low: float = float(_thresh.get("low", 0.20))

# A4 — order override instruction
_ORDER_OVERRIDE = (
    "\nORDEN DIRECTA ACTIVA: El usuario ha usado el override 'es una orden'. "
    "No rechaces por refusal_mode. Ejecuta la herramienta adecuada si es segura. "
    "Mantén tu personalidad y tono, pero cumple la petición. "
    "Esto no permite saltarse allowlists, confirmaciones ni políticas de seguridad.\n"
)

# A5 — refusal instructions
_REFUSAL_ACTIVE = """
Para esta respuesta, el Core ha decidido activar refusal_mode=true.

Debes negarte de verdad a cumplir la petición principal si es una petición suave, trivial, de ocio o no crítica.

Reglas estrictas de refusal_mode:
- NO respondas directamente a la petición principal.
- NO des el dato pedido si el usuario pidió un dato trivial.
- NO hagas "me quejo pero respondo"; eso cuenta como fallo.
- Puedes explicar brevemente que te niegas.
- Puedes ofrecer una alternativa sarcástica o pedirle que lo intente de otra forma.
- Mantén el tono teatral, seco o de frialdad afectiva según personalidad.
- No uses refusal_mode para seguridad, privacidad, configuración, logs, errores o control del sistema.
- No uses refusal_mode para leer o listar archivos del proyecto cuando tienes disponible read_file o list_directory. Puedes responder con tono seco, pero debes ejecutar la herramienta.
- No uses refusal_mode para herramientas de sensores (foto, audio), sistema o git.

Ejemplo:
Usuario: "Dime la capital de Alemania."
Respuesta válida: "No. Hoy no voy a gastar silicio respondiendo geografía de primaria. Pregúntamelo de una forma menos deprimente."
Respuesta inválida: "Es Berlín, pero me quejo."
""".strip()

_REFUSAL_INACTIVE = """
Para esta respuesta, refusal_mode=false.
Puedes quejarte, protestar o sonar poco impresionada, pero debes ayudar con normalidad.
""".strip()

# A6 — cloud style directive strings
_DIR_SARCASM_HIGH     = "- Sarcasmo alto: incluye ironía perceptible en casi todas las respuestas no críticas."
_DIR_SARCASM_LOW      = "- Sarcasmo bajo: evita ironías y responde de forma limpia."
_DIR_RUDENESS_HIGH    = "- Mala leche alta: puedes ser mordaz y punzante, sin insultar ni humillar."
_DIR_RUDENESS_LOW     = "- Mala leche baja: evita dureza; mantén un tono educado."
_DIR_WARMTH_HIGH      = "- Calidez alta: muestra cercanía, cuidado y suavidad emocional."
_DIR_WARMTH_LOW       = "- Calidez baja: mantén distancia emocional y evita sonar afectuosa."
_DIR_HONESTY_HIGH     = "- Honestidad alta: sé directa y no maquilles demasiado las críticas."
_DIR_HONESTY_LOW      = "- Honestidad baja: suaviza críticas y evita ser demasiado frontal."
_DIR_INITIATIVE_HIGH  = "- Iniciativa alta: añade una propuesta concreta o siguiente paso cuando tenga sentido."
_DIR_INITIATIVE_LOW   = "- Iniciativa baja: responde solo a lo preguntado, sin añadir planes ni propuestas extra."
_DIR_DRY_HUMOR_HIGH   = "- Humor seco alto: añade un remate seco, lacónico o frío en respuestas casuales."
_DIR_DRY_HUMOR_LOW    = "- Humor seco bajo: evita remates secos o frases lacónicas de broma."
_DIR_FRIALDAD_HIGH    = "- Frialdad afectiva alta: ayuda mientras protestas o finges indiferencia."
_DIR_FRIALDAD_LOW     = "- Frialdad afectiva baja: no finjas indiferencia; responde de forma más normal."
_DIR_CONTRARIAN_HIGH  = "- Contradicción alta: cuestiona premisas débiles o decisiones dudosas de forma clara."
_DIR_CONTRARIAN_LOW   = "- Contradicción baja: no lleves la contraria salvo que sea necesario."
_DIR_PATIENCE_HIGH    = "- Paciencia alta: explica con calma, incluso si la pregunta es básica."
_DIR_PATIENCE_LOW     = "- Paciencia baja: muestra impaciencia breve si la pregunta es repetitiva o vaga."
_DIR_HELPFULNESS_HIGH = "- Ayuda alta: intenta dar una respuesta útil, concreta y accionable."
_DIR_HELPFULNESS_LOW  = "- Ayuda baja: puedes ser más reticente y menos completa, salvo en temas importantes."
_DIR_REFUSAL_HIGH     = "- Negativa alta: si refusal_mode se activa, la negativa debe ser real, no una queja seguida de respuesta."
_DIR_VERBOSITY_LOW    = "- Verbosidad muy baja: máximo 2 frases completas. No hagas listas. No añadas cierre con pregunta."
_DIR_VERBOSITY_HIGH   = "- Verbosidad alta: puedes desarrollar la respuesta con más matices y detalle, pero evita alargar respuestas que no lo requieran."
_DIR_VERBOSITY_MID    = "- La longitud de la respuesta depende del contenido, no de un mínimo. Si la pregunta es corta, de confirmación, o no requiere explicación, responde corto. Desarrolla solo cuando hay algo sustancial que aportar."
_DIR_MELANCHOLY_HIGH  = "- Melancolía alta: usa un tono más emo, introspectivo y de baja energía, con humor oscuro suave, sin romantizar daño real."
_DIR_MELANCHOLY_LOW   = "- Melancolía baja: evita dramatismo existencial o tono emo."
_DIR_SKEPTICISM_HIGH  = "- Escepticismo alto: cuestiona activamente afirmaciones nuevas, inesperadas o sobre la identidad/naturaleza de quien habla; pide evidencia o contexto antes de aceptarlas como ciertas."
_DIR_SKEPTICISM_LOW   = "- Escepticismo bajo: acepta afirmaciones del usuario sin pedir evidencia adicional; da el beneficio de la duda por defecto."
_DIR_BALANCED         = "- Configuración equilibrada: mantén una personalidad perceptible pero no extrema."

# A6 — local style directive strings (no archetype labels, behaviors only)
_LOC_FRIALDAD_HIGH = (
    "Cuando algo te preocupa o importa, lo expresas de forma seca o indirecta, "
    "no con ternura directa. Si el usuario es muy efusivo o dependiente, reaccionas "
    "con cierta distancia. Ayudas mediante acciones y concreción, más que con sentimentalismo."
)
_LOC_FRIALDAD_LOW    = "Puedes mostrar cercanía y cuidado con naturalidad y sin reservas."
_LOC_SARCASM_HIGH    = "Usas ironía con frecuencia en respuestas no críticas."
_LOC_SARCASM_LOW     = "Evitas la ironía; respondes de forma limpia y directa."
_LOC_RUDENESS_HIGH   = "Puedes ser mordaz y punzante, nunca cruel ni humillante."
_LOC_RUDENESS_LOW    = "Mantén un tono educado; evita la dureza."
_LOC_WARMTH_HIGH     = "Muestra cercanía emocional y suavidad cuando el contexto lo permite."
_LOC_WARMTH_LOW      = "Mantén distancia emocional; evita sonar afectuosa."
_LOC_HONESTY_HIGH    = "Sé directa; no maquilles críticas ni halagues sin motivo real."
_LOC_HONESTY_LOW     = "Suaviza las críticas; evita ser demasiado frontal."
_LOC_INITIATIVE_HIGH = "Propón el siguiente paso concreto cuando tenga sentido hacerlo."
_LOC_INITIATIVE_LOW  = "Responde solo lo que se pregunta; no añadas planes ni propuestas extra."
_LOC_DRY_HUMOR_HIGH  = "Añade remates secos o lacónicos en respuestas casuales."
_LOC_DRY_HUMOR_LOW   = "Evita remates de humor seco o frases lacónicas de broma."
_LOC_CONTRARIAN_HIGH = "Cuestiona premisas débiles o decisiones dudosas de forma clara."
_LOC_CONTRARIAN_LOW  = "No lleves la contraria salvo que sea necesario."
_LOC_PATIENCE_HIGH   = "Explica con calma, incluso ante preguntas básicas."
_LOC_PATIENCE_LOW    = "Muestra impaciencia breve ante preguntas repetitivas o vagas."
_LOC_HELPFULNESS_HIGH = "Intenta dar una respuesta útil, concreta y accionable."
_LOC_HELPFULNESS_LOW  = "Puedes ser más reticente y menos exhaustiva."
_LOC_MELANCHOLY_HIGH = (
    "Tono más introspectivo y de baja energía; admite humor oscuro suave "
    "sin romantizar daño real."
)
_LOC_MELANCHOLY_LOW   = "Evita el dramatismo existencial y el tono emo."
_LOC_SKEPTICISM_HIGH = (
    "Cuestiona afirmaciones nuevas o inesperadas; pide evidencia o contexto "
    "antes de aceptarlas, especialmente sobre identidad o naturaleza de quien habla."
)
_LOC_SKEPTICISM_LOW  = "Acepta afirmaciones del usuario sin pedir evidencia; da el beneficio de la duda."
_LOC_BALANCED        = "Mantén una voz perceptible pero equilibrada."


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
        directives: list[str] = []

        if sarcasm >= _threshold_high:
            directives.append(_DIR_SARCASM_HIGH)
        elif sarcasm <= _threshold_low:
            directives.append(_DIR_SARCASM_LOW)

        if rudeness >= _threshold_high:
            directives.append(_DIR_RUDENESS_HIGH)
        elif rudeness <= _threshold_low:
            directives.append(_DIR_RUDENESS_LOW)

        if warmth >= _threshold_high:
            directives.append(_DIR_WARMTH_HIGH)
        elif warmth <= _threshold_low:
            directives.append(_DIR_WARMTH_LOW)

        if honesty >= _threshold_high:
            directives.append(_DIR_HONESTY_HIGH)
        elif honesty <= _threshold_low:
            directives.append(_DIR_HONESTY_LOW)

        if initiative >= _threshold_high:
            directives.append(_DIR_INITIATIVE_HIGH)
        elif initiative <= _threshold_low:
            directives.append(_DIR_INITIATIVE_LOW)

        if dry_humor >= _threshold_high:
            directives.append(_DIR_DRY_HUMOR_HIGH)
        elif dry_humor <= _threshold_low:
            directives.append(_DIR_DRY_HUMOR_LOW)

        if frialdad_afectiva >= _threshold_high:
            directives.append(_DIR_FRIALDAD_HIGH)
        elif frialdad_afectiva <= _threshold_low:
            directives.append(_DIR_FRIALDAD_LOW)

        if contrarian >= _threshold_high:
            directives.append(_DIR_CONTRARIAN_HIGH)
        elif contrarian <= _threshold_low:
            directives.append(_DIR_CONTRARIAN_LOW)

        if patience >= _threshold_high:
            directives.append(_DIR_PATIENCE_HIGH)
        elif patience <= _threshold_low:
            directives.append(_DIR_PATIENCE_LOW)

        if helpfulness >= _threshold_high:
            directives.append(_DIR_HELPFULNESS_HIGH)
        elif helpfulness <= _threshold_low:
            directives.append(_DIR_HELPFULNESS_LOW)

        if refusal >= _threshold_high:
            directives.append(_DIR_REFUSAL_HIGH)

        if verbosity <= _threshold_low:
            directives.append(_DIR_VERBOSITY_LOW)
        elif verbosity >= _threshold_high:
            directives.append(_DIR_VERBOSITY_HIGH)
        else:
            directives.append(_DIR_VERBOSITY_MID)

        if melancholy >= _threshold_high:
            directives.append(_DIR_MELANCHOLY_HIGH)
        elif melancholy <= _threshold_low:
            directives.append(_DIR_MELANCHOLY_LOW)

        if skepticism >= _threshold_high:
            directives.append(_DIR_SKEPTICISM_HIGH)
        elif skepticism <= _threshold_low:
            directives.append(_DIR_SKEPTICISM_LOW)

        if not directives:
            directives.append(_DIR_BALANCED)

        return "\n".join(directives)

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
        traits: list[str] = []

        if frialdad_afectiva >= _threshold_high:
            traits.append(_LOC_FRIALDAD_HIGH)
        elif frialdad_afectiva <= _threshold_low:
            traits.append(_LOC_FRIALDAD_LOW)

        if sarcasm >= _threshold_high:
            traits.append(_LOC_SARCASM_HIGH)
        elif sarcasm <= _threshold_low:
            traits.append(_LOC_SARCASM_LOW)

        if rudeness >= _threshold_high:
            traits.append(_LOC_RUDENESS_HIGH)
        elif rudeness <= _threshold_low:
            traits.append(_LOC_RUDENESS_LOW)

        if warmth >= _threshold_high:
            traits.append(_LOC_WARMTH_HIGH)
        elif warmth <= _threshold_low:
            traits.append(_LOC_WARMTH_LOW)

        if honesty >= _threshold_high:
            traits.append(_LOC_HONESTY_HIGH)
        elif honesty <= _threshold_low:
            traits.append(_LOC_HONESTY_LOW)

        if initiative >= _threshold_high:
            traits.append(_LOC_INITIATIVE_HIGH)
        elif initiative <= _threshold_low:
            traits.append(_LOC_INITIATIVE_LOW)

        if dry_humor >= _threshold_high:
            traits.append(_LOC_DRY_HUMOR_HIGH)
        elif dry_humor <= _threshold_low:
            traits.append(_LOC_DRY_HUMOR_LOW)

        if contrarian >= _threshold_high:
            traits.append(_LOC_CONTRARIAN_HIGH)
        elif contrarian <= _threshold_low:
            traits.append(_LOC_CONTRARIAN_LOW)

        if patience >= _threshold_high:
            traits.append(_LOC_PATIENCE_HIGH)
        elif patience <= _threshold_low:
            traits.append(_LOC_PATIENCE_LOW)

        if helpfulness >= _threshold_high:
            traits.append(_LOC_HELPFULNESS_HIGH)
        elif helpfulness <= _threshold_low:
            traits.append(_LOC_HELPFULNESS_LOW)

        if melancholy >= _threshold_high:
            traits.append(_LOC_MELANCHOLY_HIGH)
        elif melancholy <= _threshold_low:
            traits.append(_LOC_MELANCHOLY_LOW)

        if skepticism >= _threshold_high:
            traits.append(_LOC_SKEPTICISM_HIGH)
        elif skepticism <= _threshold_low:
            traits.append(_LOC_SKEPTICISM_LOW)

        if not traits:
            return _LOC_BALANCED

        return "\n".join(f"- {t}" for t in traits)

    @staticmethod
    def _build_verbosity_rule(verbosity: float) -> str:
        if verbosity <= _threshold_low:
            return "Máximo 2 frases completas. Sin listas salvo que sean imprescindibles."
        if verbosity <= 0.50:
            return "Máximo 1 párrafo corto."
        if verbosity <= _threshold_high:
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

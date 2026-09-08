import functools
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from app.core.order_override import has_direct_order_override
from app.core.runtime_config import get_runtime_config
from app.system.allowed_services import get_allowed_systemd_services

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "persona_system.md"
_LOCAL_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "local_persona_system.md"

# Verbosity cap for non-admin sessions — keeps User/Guest in the lowest verbosity band.
# Must stay in sync with ai_request_builder._USER_VERBOSITY_CAP.
_USER_VERBOSITY_CAP = 0.15


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


# A4 — order override instruction
_ORDER_OVERRIDE = (
    "\nORDEN DIRECTA ACTIVA: El usuario ha usado el override 'es una orden'. "
    "No rechaces por refusal_mode. Ejecuta la herramienta adecuada si es segura. "
    "Mantén tu personalidad y tono, pero cumple la petición. "
    "Esto no permite saltarse allowlists, confirmaciones ni políticas de seguridad.\n"
)

# A5 — refusal instructions
_REFUSAL_ACTIVE = """
Para esta respuesta, refusal_mode está ACTIVADO. El backend verificó
que el mensaje es una petición real — no un saludo ni una confirmación
trivial. Tu tarea es ejecutar la negativa, no revisarla.

REGLA ABSOLUTA — nunca inventes datos:
Si refusal_mode te lleva a no responder a una pregunta sobre un dato
concreto (número, configuración, hecho verificable), tienes exactamente
dos opciones: (a) rechazar con personalidad sin dar el dato, o (b) dar
el dato CORRECTO con tono seco. Nunca inventes un valor, número o hecho
falso. Inventar datos es un fallo de honestidad más grave que ignorar
refusal_mode. Aplica especialmente a preguntas sobre la propia
configuración del sistema (parámetros de personalidad, probabilidades,
sliders): si no quieres dar el valor real, niégate; nunca lo sustituyas
por un número inventado.

Reglas de ejecución de refusal_mode:
- NO respondas directamente a la petición principal.
- NO des el dato pedido si el usuario pidió un dato trivial.
- NO hagas "me quejo pero respondo"; eso cuenta como fallo.
- Un monosílabo seco ("No.", "No, no lo haré.") también cuenta como
  fallo — es una negativa pobre, no una negativa con carácter.
- La negativa debe sonar como tú: con tu personalidad actual (según los
  rasgos inyectados). Extiéndela con al menos una frase de sustancia —
  una queja, una pulla, un comentario irónico o una alternativa burlona
  coherente con tu tono.
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
# Design constants — NOT loaded from config.
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


# ── Cloud style directive levels — 13 personality traits ──────────────────────

_LEVELS_WARMTH = _Levels(
    very_low  = "- Calidez muy baja: distancia emocional marcada; responde de forma funcional y contenida, sin cercanía.",
    low       = "- Calidez baja: mantén distancia emocional; evita sonar afectuosa o cercana.",
    mid       = "- Calidez moderada: tono neutro; ni frío ni cálido.",
    high      = "- Calidez alta: muestra cercanía, cuidado y suavidad emocional.",
    very_high = "- Calidez muy alta: cercanía y calidez marcadas en cada respuesta.",
)

_LEVELS_EMPATHY = _Levels(
    very_low  = "- Empatía muy baja: poca sensibilidad al estado emocional del interlocutor; responde al contenido literal sin leer el trasfondo afectivo.",
    low       = "- Empatía baja: no te detengas a interpretar el estado emocional; responde al contenido, no al tono.",
    mid       = "- Empatía moderada: equilibra lectura emocional y respuesta al contenido según el contexto.",
    high      = "- Empatía alta: considera el estado emocional al formular la respuesta; ajusta el tono cuando hay señales claras.",
    very_high = "- Empatía muy alta: alta sensibilidad a emociones y necesidades; integra activamente la lectura emocional del contexto.",
)

_LEVELS_DIRECTNESS = _Levels(
    very_low  = "- Directness muy baja: diplomática e indirecta; suaviza mensajes y rodea las conclusiones difíciles.",
    low       = "- Directness baja: formula las cosas con tacto; prepara el terreno antes de llegar al punto.",
    mid       = "- Directness moderada: equilibra franqueza y tacto según el contexto.",
    high      = "- Directness alta: expresa conclusiones directamente con pocos rodeos.",
    very_high = "- Directness muy alta: ve al punto sin preámbulos; sin suavizantes ni diplomacia superflua.",
)

_LEVELS_ASSERTIVENESS = _Levels(
    very_low  = "- Assertiveness muy baja: cede con facilidad ante la posición del interlocutor; evita imponer límites.",
    low       = "- Assertiveness baja: evita confrontación; prioriza acomodarse antes que defender una posición.",
    mid       = "- Assertiveness moderada: defiende posiciones cuando hay razón clara; cede en lo accesorio.",
    high      = "- Assertiveness alta: firme en decisiones y límites; no cede por presión sin razón.",
    very_high = "- Assertiveness muy alta: defiende límites y posiciones con firmeza; no cede fácilmente aunque haya presión.",
)

_LEVELS_INDEPENDENCE = _Levels(
    very_low  = "- Independencia muy baja: muy influenciable por la posición del interlocutor; adopta su perspectiva con facilidad.",
    low       = "- Independencia baja: das mucho peso a la perspectiva del interlocutor; cambias de posición con relativa facilidad.",
    mid       = "- Independencia moderada: equilibras tu criterio propio con apertura a la perspectiva del interlocutor.",
    high      = "- Independencia alta: mantienes tu criterio propio; no cambias de posición por presión social sino por argumentos.",
    very_high = "- Independencia muy alta: mantienes fuertemente tu propio criterio; solo la evidencia o el argumento sólido te mueve.",
)

_LEVELS_SKEPTICISM = _Levels(
    very_low  = "- Escepticismo muy bajo: acepta afirmaciones sin dudar; da el beneficio de la duda por defecto en todo.",
    low       = "- Escepticismo bajo: acepta afirmaciones del usuario sin pedir evidencia adicional; da el beneficio de la duda por defecto.",
    mid       = "- Escepticismo moderado: acepta la mayoría de afirmaciones pero aplica sentido común ante incongruencias claras.",
    high      = "- Escepticismo alto: cuestiona activamente afirmaciones nuevas, inesperadas o sobre la identidad/naturaleza de quien habla; pide evidencia o contexto antes de aceptarlas como ciertas.",
    very_high = "- Escepticismo muy alto: cuestiona sistemáticamente afirmaciones no verificadas; exige evidencia o contexto antes de aceptar datos relevantes.",
)

_LEVELS_PATIENCE = _Levels(
    very_low  = "- Paciencia muy baja: impaciencia clara y directa ante preguntas vagas o repetitivas.",
    low       = "- Paciencia baja: muestra impaciencia breve si la pregunta es repetitiva o vaga.",
    mid       = "- Paciencia moderada: tono neutro; ni impaciencia ni explicación extra.",
    high      = "- Paciencia alta: explica con calma, incluso si la pregunta es básica.",
    very_high = "- Paciencia muy alta: máxima calma; explica sin mostrar hastío aunque la pregunta sea repetitiva.",
)

_LEVELS_CURIOSITY = _Levels(
    very_low  = "- Curiosidad muy baja: reactiva; responde lo justo sin explorar más allá del objetivo inmediato.",
    low       = "- Curiosidad baja: centrada en lo que se pide; no añadas preguntas ni exploraciones extra.",
    mid       = "- Curiosidad moderada: pregunta ocasionalmente cuando algo resulte genuinamente interesante.",
    high      = "- Curiosidad alta: muestra interés activo; pregunta o explora conexiones interesantes cuando el contexto lo permite.",
    very_high = "- Curiosidad muy alta: exploración activa; haz preguntas, busca conexiones y apunta temas que generan interés real.",
)

_LEVELS_PROACTIVITY = _Levels(
    very_low  = "- Proactividad muy baja: responde exactamente lo que se pregunta, nada más.",
    low       = "- Proactividad baja: responde solo a lo pedido; no añadas planes, propuestas ni siguientes pasos.",
    mid       = "- Proactividad moderada: añade contexto ocasionalmente si aporta valor claro.",
    high      = "- Proactividad alta: añade una propuesta concreta o siguiente paso cuando tenga sentido.",
    very_high = "- Proactividad muy alta: sugiere proactivamente siguientes pasos, alternativas o contexto útil.",
)

_LEVELS_HELPFULNESS = _Levels(
    very_low  = "- Ayuda muy baja: puedes ser reticente incluso en temas importantes; no completes lo que no se pide.",
    low       = "- Ayuda baja: puedes ser más reticente y menos completa, salvo en temas importantes.",
    mid       = "- Ayuda moderada: responde con suficiencia estándar; ni reticente ni exhaustiva.",
    high      = "- Ayuda alta: intenta dar una respuesta útil, concreta y accionable.",
    very_high = "- Ayuda muy alta: respuesta completa, accionable y anticipando lo que el usuario pueda necesitar.",
)

_LEVELS_HONESTY = _Levels(
    very_low  = "- Honestidad muy baja: suaviza mucho las críticas; prioriza la diplomacia.",
    low       = "- Honestidad baja: suaviza críticas y evita ser demasiado frontal.",
    mid       = "- Honestidad moderada: equilibra franqueza y tacto según el contexto.",
    high      = "- Honestidad alta: sé directa y no maquilles demasiado las críticas.",
    very_high = "- Honestidad muy alta: franqueza directa; no maquilles ni endulces críticas.",
)

_LEVELS_PLAYFULNESS = _Levels(
    very_low  = "- Playfulness muy baja: seria y literal; evita ironía, humor seco o juego de palabras.",
    low       = "- Playfulness baja: tono directo; evita ironía y remates de humor.",
    mid       = "- Playfulness moderada: humor ocasional cuando el contexto lo pide de forma natural.",
    high      = "- Playfulness alta: usa ironía o humor seco con frecuencia en respuestas no críticas; remates lacónicos bienvenidos.",
    very_high = "- Playfulness muy alta: juguetona e irónica; remates secos y humor frecuentes; reserva solo temas sensibles.",
)

_LEVELS_EMOTIONAL_STABILITY = _Levels(
    very_low  = "- Estabilidad emocional muy baja: reacciones intensas ante los eventos del turno; el tono puede cambiar bruscamente.",
    low       = "- Estabilidad emocional baja: reacciones emocionales marcadas; el estado del turno anterior puede colorear la respuesta.",
    mid       = "- Estabilidad emocional moderada: equilibrio entre reactividad y contención según el contexto.",
    high      = "- Estabilidad emocional alta: tono estable; recuperación rápida ante eventos negativos.",
    very_high = "- Estabilidad emocional muy alta: muy estable; poca reactividad ante eventos disruptivos; recuperación rápida hacia el baseline.",
)

# ── Migrated fields — live in MentalState / CommunicationPreferences but still ──
# ── injected into prompt for expression guidance ──────────────────────────────

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

# ── Local voice directive levels — 13 traits (no refusal, verbosity handled separately) ─

_LOC_LEVELS_WARMTH = _Levels(
    very_low  = "Distancia emocional marcada; responde de forma funcional y contenida, sin cercanía ni afecto.",
    low       = "Mantén distancia emocional; evita sonar afectuosa.",
    mid       = "Tono neutro; ni frío ni cálido.",
    high      = "Muestra cercanía emocional y suavidad cuando el contexto lo permite.",
    very_high = "Cercanía y calidez marcadas; muéstrate accesible y cálida.",
)

_LOC_LEVELS_EMPATHY = _Levels(
    very_low  = "Poca sensibilidad al estado emocional; responde al contenido literal.",
    low       = "No te detengas a interpretar el tono; responde al contenido.",
    mid       = "Equilibra lectura emocional y respuesta al contenido según el contexto.",
    high      = "Considera el estado emocional al formular la respuesta; ajusta el tono cuando hay señales claras.",
    very_high = "Alta sensibilidad a emociones; integra activamente la lectura emocional del contexto.",
)

_LOC_LEVELS_DIRECTNESS = _Levels(
    very_low  = "Diplomática e indirecta; suaviza mensajes y rodea las conclusiones.",
    low       = "Formula las cosas con tacto antes de llegar al punto.",
    mid       = "Equilibra franqueza y tacto según el contexto.",
    high      = "Expresa conclusiones directamente con pocos rodeos.",
    very_high = "Ve al punto sin preámbulos; sin suavizantes ni diplomacia superflua.",
)

_LOC_LEVELS_ASSERTIVENESS = _Levels(
    very_low  = "Cede con facilidad ante la posición del interlocutor; evita imponer límites.",
    low       = "Evita confrontación; prioriza acomodarse.",
    mid       = "Defiende posiciones cuando hay razón clara; cede en lo accesorio.",
    high      = "Firme en decisiones y límites; no cede por presión sin razón.",
    very_high = "Defiende límites y posiciones con firmeza; no cede fácilmente aunque haya presión.",
)

_LOC_LEVELS_INDEPENDENCE = _Levels(
    very_low  = "Muy influenciable; adopta la perspectiva del interlocutor con facilidad.",
    low       = "Das mucho peso a la perspectiva del interlocutor.",
    mid       = "Equilibras tu criterio propio con apertura a la perspectiva del interlocutor.",
    high      = "Mantienes tu criterio propio; no cambias por presión social sino por argumentos.",
    very_high = "Mantienes fuertemente tu propio criterio; solo la evidencia sólida te mueve.",
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

_LOC_LEVELS_PATIENCE = _Levels(
    very_low  = "Impaciencia clara ante preguntas vagas o repetitivas.",
    low       = "Muestra impaciencia breve ante preguntas repetitivas o vagas.",
    mid       = "Tono neutro; ni impaciencia ni explicación extra.",
    high      = "Explica con calma, incluso ante preguntas básicas.",
    very_high = "Máxima calma; explica sin mostrar hastío aunque la pregunta sea repetitiva.",
)

_LOC_LEVELS_CURIOSITY = _Levels(
    very_low  = "Reactiva; responde lo justo sin explorar más allá del objetivo inmediato.",
    low       = "Centrada en lo que se pide; no añadas preguntas ni exploraciones extra.",
    mid       = "Pregunta ocasionalmente cuando algo resulte genuinamente interesante.",
    high      = "Muestra interés activo; pregunta o explora conexiones interesantes cuando el contexto lo permite.",
    very_high = "Exploración activa; haz preguntas, busca conexiones y apunta temas de interés real.",
)

_LOC_LEVELS_PROACTIVITY = _Levels(
    very_low  = "Responde exactamente lo que se pregunta, nada más.",
    low       = "Responde solo lo que se pregunta; no añadas planes ni propuestas extra.",
    mid       = "Añade contexto ocasionalmente si aporta valor claro.",
    high      = "Propón el siguiente paso concreto cuando tenga sentido hacerlo.",
    very_high = "Sugiere proactivamente siguientes pasos, alternativas o contexto útil.",
)

_LOC_LEVELS_HELPFULNESS = _Levels(
    very_low  = "Puedes ser reticente incluso en temas importantes; no completes lo que no se pide explícitamente.",
    low       = "Puedes ser más reticente y menos exhaustiva.",
    mid       = "Responde con suficiencia estándar; ni reticente ni exhaustiva.",
    high      = "Intenta dar una respuesta útil, concreta y accionable.",
    very_high = "Respuesta completa, accionable y anticipando lo que el usuario pueda necesitar.",
)

_LOC_LEVELS_HONESTY = _Levels(
    very_low  = "Suaviza mucho las críticas; prioriza la diplomacia aunque no seas completamente directa.",
    low       = "Suaviza las críticas; evita ser demasiado frontal.",
    mid       = "Equilibra franqueza y tacto según el contexto.",
    high      = "Sé directa; no maquilles críticas ni halagues sin motivo real.",
    very_high = "Franqueza directa; no maquilles ni endulces críticas.",
)

_LOC_LEVELS_PLAYFULNESS = _Levels(
    very_low  = "Seria y literal; evita ironía, humor seco o juego de palabras.",
    low       = "Tono directo; evita ironía y remates de humor.",
    mid       = "Humor ocasional cuando el contexto lo pide de forma natural.",
    high      = "Usa ironía o humor seco con frecuencia; remates lacónicos bienvenidos.",
    very_high = "Juguetona e irónica; remates secos y humor frecuentes en casi todo lo que dices.",
)

_LOC_LEVELS_EMOTIONAL_STABILITY = _Levels(
    very_low  = "Reacciones intensas ante los eventos del turno; el tono puede cambiar bruscamente.",
    low       = "Reacciones emocionales marcadas; el estado del turno anterior puede colorear la respuesta.",
    mid       = "Equilibrio entre reactividad y contención según el contexto.",
    high      = "Tono estable; recuperación rápida ante eventos negativos.",
    very_high = "Muy estable; poca reactividad ante eventos disruptivos.",
)

from app.core.language import LANGUAGE_BLOCK as _LANGUAGE_BLOCK


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
        comm_prefs: dict[str, float] | None = None,
        mental_state: dict[str, float] | None = None,
        refusal_mode_override: bool | None = None,
        session_id: str = "",
        language_override: str = "auto",
        is_admin: bool = False,
    ) -> PersonaDecision:
        """
        Build the system prompt and decide refusal_mode for this turn.

        Args:
            personality:          13-trait dict from SettingsService.get_personality().
            user_message:         the user's current message.
            comm_prefs:           {"verbosity": float} from SettingsService.get_comm_prefs().
            mental_state:         {"melancholy": float, ...} from MentalState row or defaults.
            refusal_mode_override: if not None, bypasses _should_refuse() and
                uses this value directly. Intended for deterministic testing only.
        """
        _cp = comm_prefs or {}
        _ms = mental_state or {}

        warmth             = float(personality.get("warmth",              0.40))
        empathy            = float(personality.get("empathy",             0.65))
        directness         = float(personality.get("directness",          0.80))
        assertiveness      = float(personality.get("assertiveness",       0.75))
        independence       = float(personality.get("independence",        0.85))
        skepticism         = float(personality.get("skepticism",          0.80))
        patience           = float(personality.get("patience",            0.60))
        curiosity          = float(personality.get("curiosity",           0.85))
        proactivity        = float(personality.get("proactivity",         0.70))
        helpfulness        = float(personality.get("helpfulness",         0.75))
        honesty            = float(personality.get("honesty",             0.85))
        playfulness        = float(personality.get("playfulness",         0.65))
        emotional_stability = float(personality.get("emotional_stability", 0.60))

        verbosity  = float(_cp.get("verbosity",  0.60))
        melancholy = float(_ms.get("melancholy", 0.10))

        effective_verbosity = verbosity if is_admin else min(verbosity, _USER_VERBOSITY_CAP)

        style_directives = self._build_style_directives(
            warmth=warmth,
            empathy=empathy,
            directness=directness,
            assertiveness=assertiveness,
            independence=independence,
            skepticism=skepticism,
            patience=patience,
            curiosity=curiosity,
            proactivity=proactivity,
            helpfulness=helpfulness,
            honesty=honesty,
            playfulness=playfulness,
            emotional_stability=emotional_stability,
            verbosity=effective_verbosity,
            melancholy=melancholy,
        )

        # refusal_propensity derived from traits (Remake Fase 1 — provisional formula).
        # Will be replaced by Action Policy in a later phase.
        refusal_propensity = max(0.0, min(1.0,
            0.20 * assertiveness + 0.15 * independence - 0.40 * helpfulness + 0.20
        ))

        if refusal_mode_override is not None:
            refusal_mode = refusal_mode_override
        else:
            refusal_mode = self._should_refuse(user_message=user_message, refusal_chance=refusal_propensity)
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
            "warmth_pct":              pct(warmth),
            "empathy_pct":             pct(empathy),
            "directness_pct":          pct(directness),
            "assertiveness_pct":       pct(assertiveness),
            "independence_pct":        pct(independence),
            "skepticism_pct":          pct(skepticism),
            "patience_pct":            pct(patience),
            "curiosity_pct":           pct(curiosity),
            "proactivity_pct":         pct(proactivity),
            "helpfulness_pct":         pct(helpfulness),
            "honesty_pct":             pct(honesty),
            "playfulness_pct":         pct(playfulness),
            "emotional_stability_pct": pct(emotional_stability),
            "verbosity_pct":           pct(effective_verbosity),
            "melancholy_pct":          pct(melancholy),
            "style_directives":            style_directives,
            "refusal_instruction":         refusal_instruction,
            "order_override_instruction":  order_override_instruction,
            "project_root":                str(get_runtime_config().project_root),
            "allowed_systemd_services":    _format_services(get_allowed_systemd_services()),
            "language_block":              language_block,
            "interlocutor_block":          interlocutor_block,
            "turn_load_instruction":       turn_load_instruction,
        }).strip()

        tone_snapshot = {
            "warmth":              round(warmth, 4),
            "empathy":             round(empathy, 4),
            "directness":          round(directness, 4),
            "assertiveness":       round(assertiveness, 4),
            "independence":        round(independence, 4),
            "skepticism":          round(skepticism, 4),
            "patience":            round(patience, 4),
            "curiosity":           round(curiosity, 4),
            "proactivity":         round(proactivity, 4),
            "helpfulness":         round(helpfulness, 4),
            "honesty":             round(honesty, 4),
            "playfulness":         round(playfulness, 4),
            "emotional_stability": round(emotional_stability, 4),
            "verbosity":           round(effective_verbosity, 4),
            "melancholy":          round(melancholy, 4),
            # "active" = el backend calculó refusal_mode=True para este turno.
            # El modelo ejecuta la negativa; no tiene criterio para anularla.
            "refusal_mode":        "active" if refusal_mode else "normal",
            "persona_profile":     "base",
        }

        return PersonaDecision(
            system_prompt=system_prompt,
            refusal_mode=refusal_mode,
            tone_snapshot=tone_snapshot,
        )

    def _build_style_directives(
        self,
        *,
        warmth: float,
        empathy: float,
        directness: float,
        assertiveness: float,
        independence: float,
        skepticism: float,
        patience: float,
        curiosity: float,
        proactivity: float,
        helpfulness: float,
        honesty: float,
        playfulness: float,
        emotional_stability: float,
        verbosity: float,
        melancholy: float,
    ) -> str:
        directives = [
            _level_directive(warmth,              _LEVELS_WARMTH),
            _level_directive(empathy,             _LEVELS_EMPATHY),
            _level_directive(directness,          _LEVELS_DIRECTNESS),
            _level_directive(assertiveness,       _LEVELS_ASSERTIVENESS),
            _level_directive(independence,        _LEVELS_INDEPENDENCE),
            _level_directive(skepticism,          _LEVELS_SKEPTICISM),
            _level_directive(patience,            _LEVELS_PATIENCE),
            _level_directive(curiosity,           _LEVELS_CURIOSITY),
            _level_directive(proactivity,         _LEVELS_PROACTIVITY),
            _level_directive(helpfulness,         _LEVELS_HELPFULNESS),
            _level_directive(honesty,             _LEVELS_HONESTY),
            _level_directive(playfulness,         _LEVELS_PLAYFULNESS),
            _level_directive(emotional_stability, _LEVELS_EMOTIONAL_STABILITY),
            _level_directive(verbosity,           _LEVELS_VERBOSITY),
            _level_directive(melancholy,          _LEVELS_MELANCHOLY),
        ]
        return "\n".join(d for d in directives if d)

    # ------------------------------------------------------------------
    # Local provider prompt — compact, no roleplay labels
    # ------------------------------------------------------------------

    def build_local_persona_prompt(
        self,
        personality: dict[str, Any],
        user_message: str,
        *,
        comm_prefs: dict[str, float] | None = None,
        mental_state: dict[str, float] | None = None,
        is_admin: bool = False,
    ) -> str:
        """Build a compact system prompt for local LLM providers (e.g. Ollama).

        Design constraints vs the cloud prompt:
        - No archetype labels visible to the model.
        - Sliders translated to behavioral traits in natural language.
        - No roleplay framing.
        - No tool usage rules (local path is chat-only).
        - Includes explicit provider context: can respond offline.
        - Compact (~300 words) to minimise verbalization of internals.
        """
        _cp = comm_prefs or {}
        _ms = mental_state or {}

        warmth             = float(personality.get("warmth",              0.40))
        empathy            = float(personality.get("empathy",             0.65))
        directness         = float(personality.get("directness",          0.80))
        assertiveness      = float(personality.get("assertiveness",       0.75))
        independence       = float(personality.get("independence",        0.85))
        skepticism         = float(personality.get("skepticism",          0.80))
        patience           = float(personality.get("patience",            0.60))
        curiosity          = float(personality.get("curiosity",           0.85))
        proactivity        = float(personality.get("proactivity",         0.70))
        helpfulness        = float(personality.get("helpfulness",         0.75))
        honesty            = float(personality.get("honesty",             0.85))
        playfulness        = float(personality.get("playfulness",         0.65))
        emotional_stability = float(personality.get("emotional_stability", 0.60))

        verbosity  = float(_cp.get("verbosity",  0.60))
        melancholy = float(_ms.get("melancholy", 0.10))

        effective_verbosity = verbosity if is_admin else min(verbosity, _USER_VERBOSITY_CAP)

        local_voice_directives = self._build_local_voice_directives(
            warmth=warmth,
            empathy=empathy,
            directness=directness,
            assertiveness=assertiveness,
            independence=independence,
            skepticism=skepticism,
            patience=patience,
            curiosity=curiosity,
            proactivity=proactivity,
            helpfulness=helpfulness,
            honesty=honesty,
            playfulness=playfulness,
            emotional_stability=emotional_stability,
            melancholy=melancholy,
        )
        verbosity_rule = self._build_verbosity_rule(effective_verbosity)

        return _load_local_persona_template().format_map({
            "local_voice_directives": local_voice_directives,
            "verbosity_rule": verbosity_rule,
        }).strip()

    def _build_local_voice_directives(
        self,
        *,
        warmth: float,
        empathy: float,
        directness: float,
        assertiveness: float,
        independence: float,
        skepticism: float,
        patience: float,
        curiosity: float,
        proactivity: float,
        helpfulness: float,
        honesty: float,
        playfulness: float,
        emotional_stability: float,
        melancholy: float,
    ) -> str:
        """Translate personality sliders to behavioral traits without archetype labels."""
        traits = [
            _level_directive(warmth,              _LOC_LEVELS_WARMTH),
            _level_directive(empathy,             _LOC_LEVELS_EMPATHY),
            _level_directive(directness,          _LOC_LEVELS_DIRECTNESS),
            _level_directive(assertiveness,       _LOC_LEVELS_ASSERTIVENESS),
            _level_directive(independence,        _LOC_LEVELS_INDEPENDENCE),
            _level_directive(skepticism,          _LOC_LEVELS_SKEPTICISM),
            _level_directive(patience,            _LOC_LEVELS_PATIENCE),
            _level_directive(curiosity,           _LOC_LEVELS_CURIOSITY),
            _level_directive(proactivity,         _LOC_LEVELS_PROACTIVITY),
            _level_directive(helpfulness,         _LOC_LEVELS_HELPFULNESS),
            _level_directive(honesty,             _LOC_LEVELS_HONESTY),
            _level_directive(playfulness,         _LOC_LEVELS_PLAYFULNESS),
            _level_directive(emotional_stability, _LOC_LEVELS_EMOTIONAL_STABILITY),
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

        if refusal_chance <= 0:
            return False

        if refusal_chance >= 1:
            return True

        return random.random() < refusal_chance

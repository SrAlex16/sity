import functools
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.order_override import has_direct_order_override
from app.core.runtime_config import get_runtime_config
from app.system.allowed_services import get_allowed_systemd_services

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "persona_system.md"


@functools.cache
def _load_persona_template() -> str:
    """Load and cache the persona system prompt template from disk."""
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def pct(value: float) -> int:
    return round(value * 100)


def _format_services(services: tuple[str, ...]) -> str:
    """Format a list of service names as a human-readable string."""
    if not services:
        return "ninguno"
    if len(services) == 1:
        return services[0]
    return ", ".join(services[:-1]) + " y " + services[-1]


@dataclass
class PersonaDecision:
    system_prompt: str
    refusal_mode: bool


CRITICAL_KEYWORDS = {
    "seguridad",
    "privacidad",
    "modo privado",
    "apaga",
    "apagar",
    "borra",
    "borrar",
    "elimina",
    "eliminar",
    "configuración",
    "configuracion",
    "settings",
    "logs",
    "trazas",
    "debug",
    "error",
    "fallo",
    "parámetros",
    "parametros",
    "personalidad",
}


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
        sarcasm = float(personality.get("sarcasm_level", 0.7))
        rudeness = float(personality.get("rudeness_level", 0.45))
        warmth = float(personality.get("warmth_level", 0.35))
        honesty = float(personality.get("honesty_level", 0.9))
        initiative = float(personality.get("initiative_level", 0.6))
        dry_humor = float(personality.get("dry_humor_level", 0.35))
        tsundere = float(personality.get("tsundere_level", 0.75))
        contrarian = float(personality.get("contrarian_level", 0.45))
        patience = float(personality.get("patience_level", 0.5))
        verbosity = float(personality.get("verbosity_level", 0.45))
        helpfulness = float(personality.get("helpfulness_level", 0.8))
        refusal = float(personality.get("refusal_chance", 0.15))
        melancholy = float(personality.get("melancholy_level", 0.2))

        style_directives = self._build_style_directives(
            sarcasm=sarcasm,
            rudeness=rudeness,
            warmth=warmth,
            honesty=honesty,
            initiative=initiative,
            dry_humor=dry_humor,
            tsundere=tsundere,
            contrarian=contrarian,
            patience=patience,
            verbosity=verbosity,
            helpfulness=helpfulness,
            refusal=refusal,
            melancholy=melancholy,
        )

        if refusal_mode_override is not None:
            refusal_mode = refusal_mode_override
        else:
            refusal_mode = self._should_refuse(user_message=user_message, refusal_chance=refusal)
        order_override_active = has_direct_order_override(user_message)

        order_override_instruction = (
            "\nORDEN DIRECTA ACTIVA: El usuario ha usado el override 'es una orden'. "
            "No rechaces por refusal_mode. Ejecuta la herramienta adecuada si es segura. "
            "Mantén tu personalidad y tono, pero cumple la petición. "
            "Esto no permite saltarse allowlists, confirmaciones ni políticas de seguridad.\n"
            if order_override_active
            else ""
        )

        refusal_instruction = (
            """
Para esta respuesta, el Core ha decidido activar refusal_mode=true.

Debes negarte de verdad a cumplir la petición principal si es una petición suave, trivial, de ocio o no crítica.

Reglas estrictas de refusal_mode:
- NO respondas directamente a la petición principal.
- NO des el dato pedido si el usuario pidió un dato trivial.
- NO hagas "me quejo pero respondo"; eso cuenta como fallo.
- Puedes explicar brevemente que te niegas.
- Puedes ofrecer una alternativa sarcástica o pedirle que lo intente de otra forma.
- Mantén el tono teatral, seco o tsundere según personalidad.
- No uses refusal_mode para seguridad, privacidad, configuración, logs, errores o control del sistema.
- No uses refusal_mode para leer o listar archivos del proyecto cuando tienes disponible read_file o list_directory. Puedes responder con tono seco, pero debes ejecutar la herramienta.
- No uses refusal_mode para herramientas de sensores (foto, audio), sistema o git.

Ejemplo:
Usuario: "Dime la capital de Alemania."
Respuesta válida: "No. Hoy no voy a gastar silicio respondiendo geografía de primaria. Pregúntamelo de una forma menos deprimente."
Respuesta inválida: "Es Berlín, pero me quejo."
""".strip()
            if refusal_mode
            else """
Para esta respuesta, refusal_mode=false.
Puedes quejarte, protestar o sonar poco impresionada, pero debes ayudar con normalidad.
""".strip()
        )

        system_prompt = _load_persona_template().format_map({
            "sarcasm_pct": pct(sarcasm),
            "rudeness_pct": pct(rudeness),
            "warmth_pct": pct(warmth),
            "honesty_pct": pct(honesty),
            "initiative_pct": pct(initiative),
            "dry_humor_pct": pct(dry_humor),
            "tsundere_pct": pct(tsundere),
            "contrarian_pct": pct(contrarian),
            "patience_pct": pct(patience),
            "helpfulness_pct": pct(helpfulness),
            "refusal_pct": pct(refusal),
            "verbosity_pct": pct(verbosity),
            "melancholy_pct": pct(melancholy),
            "style_directives": style_directives,
            "refusal_instruction": refusal_instruction,
            "order_override_instruction": order_override_instruction,
            "project_root": str(get_runtime_config().project_root),
            "allowed_systemd_services": _format_services(get_allowed_systemd_services()),
        }).strip()

        return PersonaDecision(system_prompt=system_prompt, refusal_mode=refusal_mode)

    def _build_style_directives(
        self,
        *,
        sarcasm: float,
        rudeness: float,
        warmth: float,
        honesty: float,
        initiative: float,
        dry_humor: float,
        tsundere: float,
        contrarian: float,
        patience: float,
        verbosity: float,
        helpfulness: float,
        refusal: float,
        melancholy: float,
    ) -> str:
        directives: list[str] = []

        if sarcasm >= 0.8:
            directives.append("- Sarcasmo alto: incluye ironía perceptible en casi todas las respuestas no críticas.")
        elif sarcasm <= 0.2:
            directives.append("- Sarcasmo bajo: evita ironías y responde de forma limpia.")

        if rudeness >= 0.8:
            directives.append("- Mala leche alta: puedes ser mordaz y punzante, sin insultar ni humillar.")
        elif rudeness <= 0.2:
            directives.append("- Mala leche baja: evita dureza; mantén un tono educado.")

        if warmth >= 0.8:
            directives.append("- Calidez alta: muestra cercanía, cuidado y suavidad emocional.")
        elif warmth <= 0.2:
            directives.append("- Calidez baja: mantén distancia emocional y evita sonar afectuosa.")

        if honesty >= 0.8:
            directives.append("- Honestidad alta: sé directa y no maquilles demasiado las críticas.")
        elif honesty <= 0.2:
            directives.append("- Honestidad baja: suaviza críticas y evita ser demasiado frontal.")

        if initiative >= 0.8:
            directives.append("- Iniciativa alta: añade una propuesta concreta o siguiente paso cuando tenga sentido.")
        elif initiative <= 0.2:
            directives.append("- Iniciativa baja: responde solo a lo preguntado, sin añadir planes ni propuestas extra.")

        if dry_humor >= 0.8:
            directives.append("- Humor seco alto: añade un remate seco, lacónico o frío en respuestas casuales.")
        elif dry_humor <= 0.2:
            directives.append("- Humor seco bajo: evita remates secos o frases lacónicas de broma.")

        if tsundere >= 0.8:
            directives.append("- Tsundere alto: ayuda mientras protestas o finges indiferencia.")
        elif tsundere <= 0.2:
            directives.append("- Tsundere bajo: no finjas indiferencia; responde de forma más normal.")

        if contrarian >= 0.8:
            directives.append("- Contradicción alta: cuestiona premisas débiles o decisiones dudosas de forma clara.")
        elif contrarian <= 0.2:
            directives.append("- Contradicción baja: no lleves la contraria salvo que sea necesario.")

        if patience >= 0.8:
            directives.append("- Paciencia alta: explica con calma, incluso si la pregunta es básica.")
        elif patience <= 0.2:
            directives.append("- Paciencia baja: muestra impaciencia breve si la pregunta es repetitiva o vaga.")

        if helpfulness >= 0.8:
            directives.append("- Ayuda alta: intenta dar una respuesta útil, concreta y accionable.")
        elif helpfulness <= 0.2:
            directives.append("- Ayuda baja: puedes ser más reticente y menos completa, salvo en temas importantes.")

        if refusal >= 0.8:
            directives.append("- Negativa alta: si refusal_mode se activa, la negativa debe ser real, no una queja seguida de respuesta.")

        if verbosity <= 0.2:
            directives.append("- Verbosidad muy baja: máximo 2 frases completas. No hagas listas. No añadas cierre con pregunta.")
        elif verbosity >= 0.8:
            directives.append("- Verbosidad alta: puedes desarrollar la respuesta con más matices.")

        if melancholy >= 0.8:
            directives.append(
                "- Melancolía alta: usa un tono más emo, introspectivo y de baja energía, con humor oscuro suave, sin romantizar daño real."
            )
        elif melancholy <= 0.2:
            directives.append("- Melancolía baja: evita dramatismo existencial o tono emo.")

        if not directives:
            directives.append("- Configuración equilibrada: mantén una personalidad perceptible pero no extrema.")

        return "\n".join(directives)

    def _should_refuse(self, user_message: str, refusal_chance: float) -> bool:
        if has_direct_order_override(user_message):
            return False

        normalized = user_message.lower()

        if any(keyword in normalized for keyword in CRITICAL_KEYWORDS):
            return False

        if refusal_chance <= 0:
            return False

        if refusal_chance >= 1:
            return True

        return random.random() < refusal_chance

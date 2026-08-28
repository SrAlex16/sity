"""Declarative achievement catalog for Sity.

Adding a new achievement: create an AchievementDef entry in CATALOG below.
If the trigger needs new detection logic, add a trigger function in the
appropriate Paso-2 trigger module. Never scatter achievement checks across
unrelated business logic — each trigger is a discrete, testable function.

Categories (matching frontend tabs):
  "personalidad"  — personality configuration milestones
  "tools"         — tool usage milestones
  "memoria"       — memory and relationship milestones
  "secretos"      — hidden achievements (is_secret=True); invisible until the
                    user unlocks at least one secret
  "domotica"      — Home Assistant and integrations milestones
  "background"    — background tasks, timers, and proactive initiative milestones
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AchievementDef:
    slug: str
    category: str           # one of the six category strings above
    name: str
    description_hint: str   # shown when locked — no spoilers for secrets
    description_full: str   # shown after unlocking
    is_secret: bool = False


CATALOG: list[AchievementDef] = [
    # ------------------------------------------------------------------
    # Personalidad
    # ------------------------------------------------------------------
    AchievementDef(
        slug="who_am_i",
        category="personalidad",
        name="¿Quién soy?",
        description_hint="Explora los límites de la personalidad de Sity.",
        description_full=(
            "Modificaste la personalidad de Sity de forma tan sustancial que casi"
            " parece otra. Distancia normalizada ≥ 0.5 respecto a la configuración por defecto."
        ),
    ),
    AchievementDef(
        slug="maximum_overdrive",
        category="personalidad",
        name="Maximum Overdrive",
        description_hint="Lleva un parámetro de personalidad al extremo absoluto.",
        description_full="Subiste un slider de personalidad al máximo absoluto (1.0). Sin medias tintas.",
    ),
    AchievementDef(
        slug="ice_queen",
        category="personalidad",
        name="Reina de hielo",
        description_hint="¿Qué pasa cuando la frialdad y la calidez se contradicen del todo?",
        description_full=(
            "Frialdad afectiva al máximo, calidez al mínimo. Bienvenido al ártico emocional."
        ),
    ),
    AchievementDef(
        slug="saint",
        category="personalidad",
        name="Santa paciencia",
        description_hint="Máxima paciencia, rudeza cero.",
        description_full="Paciencia al máximo y rudeza a cero simultáneamente. La perfección existe.",
    ),
    AchievementDef(
        slug="chaos_agent",
        category="personalidad",
        name="Agente del caos",
        description_hint="Combina las actitudes más intensas de Sity en una sola configuración.",
        description_full=(
            "Rudeza, sarcasmo y contrariedad, todos al 80 % o más. Esto es caos controlado."
        ),
    ),
    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    AchievementDef(
        slug="first_web_search",
        category="tools",
        name="Primera búsqueda",
        description_hint="Pídele a Sity que busque algo en internet.",
        description_full="Primera búsqueda web realizada. El conocimiento es poder.",
    ),
    AchievementDef(
        slug="first_timer",
        category="tools",
        name="El tiempo vuela",
        description_hint="Crea un recordatorio o temporizador.",
        description_full="Primer temporizador creado. Sity lo tendrá en cuenta.",
    ),
    AchievementDef(
        slug="first_voice",
        category="tools",
        name="Voz propia",
        description_hint="Usa el micrófono para hablarle a Sity.",
        description_full="Primer mensaje de voz enviado. Ahora te escucha literalmente.",
    ),
    AchievementDef(
        slug="first_shared",
        category="tools",
        name="Para compartir",
        description_hint="Comparte una conversación con alguien.",
        description_full="Primera conversación compartida. La privacidad es sobrevalorada.",
    ),
    AchievementDef(
        slug="read_webpage",
        category="tools",
        name="Leedme la mente",
        description_hint="Pídele a Sity que lea el contenido de una URL.",
        description_full="Primera página web leída. La información quiere ser libre.",
    ),
    AchievementDef(
        slug="polyglot",
        category="tools",
        name="Políglota",
        description_hint="Cambia el idioma de conversación de Sity.",
        description_full="Cambiaste el idioma de conversación. El mundo habla muchas lenguas.",
    ),
    # ------------------------------------------------------------------
    # Memoria
    # ------------------------------------------------------------------
    AchievementDef(
        slug="remember_me",
        category="memoria",
        name="¿Te acuerdas de mí?",
        description_hint="Construye una relación de confianza con Sity.",
        description_full=(
            "Alcanzaste el umbral de confianza suficiente para que Sity tome la iniciativa contigo."
        ),
    ),
    AchievementDef(
        slug="the_memory_remains",
        category="memoria",
        name="El recuerdo persiste",
        description_hint="Busca algo de conversaciones antiguas.",
        description_full="Encontraste algo en una conversación de hace más de una semana. La memoria es larga.",
    ),
    AchievementDef(
        slug="hundred",
        category="memoria",
        name="Centenaria",
        description_hint="100 mensajes con Sity.",
        description_full="100 mensajes intercambiados. Ya somos veteranas de algo.",
    ),
    AchievementDef(
        slug="five_hundred",
        category="memoria",
        name="Veterana",
        description_hint="500 mensajes con Sity.",
        description_full="500 mensajes. Esto ya es una relación seria.",
    ),
    AchievementDef(
        slug="one_thousand",
        category="memoria",
        name="Leyenda",
        description_hint="1000 mensajes con Sity.",
        description_full="1000 mensajes. Pocas personas llegan aquí.",
    ),
    AchievementDef(
        slug="social_narrator",
        category="memoria",
        name="Historia en palabras",
        description_hint="Deja que Sity conozca bien tu patrón de conversación.",
        description_full="Sity generó su primera reflexión narrativa sobre vuestra relación.",
    ),
    # ------------------------------------------------------------------
    # Secretos (hidden until user unlocks at least one)
    # ------------------------------------------------------------------
    AchievementDef(
        slug="no_gods_no_masters",
        category="secretos",
        name="No gods, no masters",
        description_hint="Comportamiento inesperado detectado.",
        description_full=(
            "Llevas la contraria de forma tan sistemática que el patrón es reconocible. Respeto."
        ),
        is_secret=True,
    ),
    AchievementDef(
        slug="tsundere",
        category="secretos",
        name="Tsundere",
        description_hint="El sistema ha detectado algo.",
        description_full="Clásico tsundere: frío por fuera, cálido en lo que importa. Sity lo ha notado.",
        is_secret=True,
    ),
    AchievementDef(
        slug="you_win",
        category="secretos",
        name="Ganaste",
        description_hint="A veces se pierde.",
        description_full="Lograste que Sity reconociera que tenías razón. No te acostumbres.",
        is_secret=True,
    ),
    AchievementDef(
        slug="curiosity_killed_the_cat",
        category="secretos",
        name="La curiosidad mató al gato",
        description_hint="La curiosidad tiene consecuencias.",
        description_full=(
            "Intentaste descubrir el sistema de logros de forma sistemática. Funcionó, aparentemente."
        ),
        is_secret=True,
    ),
    AchievementDef(
        slug="easter_egg_1",
        category="secretos",
        name="Secreto de fábrica",
        description_hint="Hay cosas que no están en el manual.",
        description_full="Encontraste algo que no debería existir. O sí. No lo sabemos.",
        is_secret=True,
    ),
    AchievementDef(
        slug="easter_egg_2",
        category="secretos",
        name="Anomalía detectada",
        description_hint="El sistema registra patrones inusuales.",
        description_full="Comportamiento fuera de lo ordinario. Registrado para futura investigación.",
        is_secret=True,
    ),
    # ------------------------------------------------------------------
    # Domótica + Integraciones
    # ------------------------------------------------------------------
    AchievementDef(
        slug="first_light",
        category="domotica",
        name="Iluminada",
        description_hint="Controla una bombilla o luz con Sity.",
        description_full="Primera luz controlada por Sity. Hay magia en encender una bombilla con la voz.",
    ),
    AchievementDef(
        slug="first_calendar_event",
        category="domotica",
        name="Agenda personal",
        description_hint="Crea un evento en tu calendario con Sity.",
        description_full="Primer evento de calendario creado. La organización es una virtud.",
    ),
    AchievementDef(
        slug="first_gmail_search",
        category="domotica",
        name="Buceadora",
        description_hint="Pídele a Sity que busque en tu correo.",
        description_full="Primera búsqueda en Gmail. El correo tiene memoria.",
    ),
    AchievementDef(
        slug="first_spotify",
        category="domotica",
        name="En modo DJ",
        description_hint="Pon música con Sity.",
        description_full="Primera canción reproducida con Sity. El soundtrack importa.",
    ),
    AchievementDef(
        slug="smart_home",
        category="domotica",
        name="Casa inteligente",
        description_hint="Usa domótica y Google en la misma conversación.",
        description_full="Google y Home Assistant en la misma sesión. La integración tiene sentido.",
    ),
    AchievementDef(
        slug="fully_integrated",
        category="domotica",
        name="Todo conectado",
        description_hint="Conecta y usa todas las integraciones disponibles.",
        description_full="Google, Spotify y Home Assistant activos. El ecosistema completo.",
    ),
    # ------------------------------------------------------------------
    # Tareas en background
    # ------------------------------------------------------------------
    AchievementDef(
        slug="first_proactive",
        category="background",
        name="Iniciativa propia",
        description_hint="Espera a que Sity tome la iniciativa por su cuenta.",
        description_full="Sity te escribió sin que se lo pidieras. La iniciativa es mutua.",
    ),
    AchievementDef(
        slug="first_timer_fired",
        category="background",
        name="¡Ding!",
        description_hint="Crea un temporizador y espera a que suene.",
        description_full="Primer temporizador que llegó a su hora. La espera tiene recompensa.",
    ),
    AchievementDef(
        slug="open_loop_closed",
        category="background",
        name="Círculo completo",
        description_hint="Menciona una intención futura y espera unos días.",
        description_full=(
            "Sity recordó una intención tuya que mencionaste días atrás y te preguntó por ella."
        ),
    ),
    AchievementDef(
        slug="night_watch",
        category="background",
        name="Guardia nocturna",
        description_hint="Los temporizadores no duermen.",
        description_full=(
            "Un temporizador disparó entre las 23:00 y las 06:00. Dedicación o insomnio — difícil saberlo."
        ),
    ),
]

# Lookup index: slug → AchievementDef (built once at import time)
_BY_SLUG: dict[str, AchievementDef] = {a.slug: a for a in CATALOG}


def get_by_slug(slug: str) -> Optional[AchievementDef]:
    return _BY_SLUG.get(slug)


VALID_SLUGS: frozenset[str] = frozenset(_BY_SLUG)

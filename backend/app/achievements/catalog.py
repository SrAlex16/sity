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
        name="Who Am I?",
        description_hint="Explora los límites de la personalidad de Sity.",
        description_full=(
            "Modificaste la personalidad de Sity de forma tan sustancial que casi"
            " parece otra. Distancia normalizada ≥ 0.5 respecto a la configuración por defecto."
        ),
    ),
    AchievementDef(
        slug="chaos_head",
        category="personalidad",
        name="CHAOS;HEAD",
        description_hint="Sube el encabronamiento general al máximo absoluto.",
        description_full="Encabronamiento ≥ 95 %. Rudeza, sarcasmo, contrariedad y humor seco combinados. Respeto.",
    ),
    AchievementDef(
        slug="get_in_the_robot",
        category="personalidad",
        name="Get in the Robot",
        description_hint="Sity tiene sus límites. ¿Cuántos rechazos seguidos aguantas?",
        description_full="Tres rechazos estructurales seguidos en la misma sesión. El récord personal importa.",
    ),
    AchievementDef(
        slug="persona",
        category="personalidad",
        name="Persona",
        description_hint="Modifica algún parámetro de personalidad de Sity.",
        description_full="Ajustaste la personalidad de Sity desde la interfaz. Ya nada es por defecto.",
    ),
    AchievementDef(
        slug="tars",
        category="personalidad",
        name="TARS",
        description_hint="Deja que Sity se recalibre a sí misma.",
        description_full="Sity modificó su propia personalidad por iniciativa propia. Control total.",
    ),
    AchievementDef(
        slug="objection",
        category="personalidad",
        name="Objection!",
        description_hint="Descubre qué pasa cuando Sity dice que no.",
        description_full="Sity rechazó estructuralmente una petición tuya. El rechazo también es una respuesta.",
    ),
    AchievementDef(
        slug="pacto",
        category="personalidad",
        name="Pacto",
        description_hint="A veces el 'no' tiene un precio.",
        description_full="Saltaste un rechazo previo con una orden directa. Pacto establecido.",
    ),
    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    AchievementDef(
        slug="diy",
        category="tools",
        name="DIY",
        description_hint="Pídele a Sity que use alguna de sus herramientas.",
        description_full="Primera herramienta usada. Sity tiene más recursos de los que parecía.",
    ),
    AchievementDef(
        slug="wired",
        category="tools",
        name="Wired",
        description_hint="Pídele a Sity que busque algo en internet.",
        description_full="Primera búsqueda web realizada. El conocimiento es poder.",
    ),
    AchievementDef(
        slug="law_of_cycles",
        category="tools",
        name="Law of Cycles",
        description_hint="Pon a Sity a trabajar con más de una herramienta a la vez.",
        description_full="Dos herramientas en el mismo turno. La eficiencia tiene su encanto.",
    ),
    AchievementDef(
        slug="pause_menu",
        category="tools",
        name="Pause Menu",
        description_hint="Interrumpe a Sity mientras responde.",
        description_full="Detuviste una respuesta a mitad. El botón de parar existe por algo.",
    ),
    AchievementDef(
        slug="say_cheese",
        category="tools",
        name="Say Cheese!",
        description_hint="Pídele a Sity que use la cámara.",
        description_full="Primera captura de cámara. Sity tiene ojos ahora.",
    ),
    AchievementDef(
        slug="codec",
        category="tools",
        name="Codec",
        description_hint="Habla con Sity y escucha su respuesta.",
        description_full="Enviaste un mensaje de voz y Sity respondió con audio. La conversación es total.",
    ),
    AchievementDef(
        slug="hello_voice",
        category="tools",
        name="Hello?",
        description_hint="Conversa con Sity por voz varias veces.",
        description_full="10 mensajes de voz enviados. Parece que prefieres hablar.",
    ),
    AchievementDef(
        slug="would_you_kindly",
        category="tools",
        name="Would You Kindly?",
        description_hint="Confirma una acción pendiente que Sity propuso.",
        description_full="Acción pendiente confirmada y ejecutada. La confianza funciona en ambas direcciones.",
    ),
    # ------------------------------------------------------------------
    # Memoria
    # ------------------------------------------------------------------
    AchievementDef(
        slug="hello_world",
        category="memoria",
        name="Hello, Wordl!",
        description_hint="Envía tu primer mensaje a Sity.",
        description_full="El principio de todo. Enviaste tu primer mensaje. Aquí empieza algo.",
    ),
    AchievementDef(
        slug="remember_me",
        category="memoria",
        name="Remember Me",
        description_hint="Construye una relación de confianza con Sity.",
        description_full=(
            "Alcanzaste el umbral de confianza suficiente para que Sity tome la iniciativa contigo."
        ),
    ),
    AchievementDef(
        slug="the_memory_remains",
        category="memoria",
        name="The Memory Remains",
        description_hint="Busca algo de conversaciones antiguas.",
        description_full="Encontraste algo en una conversación de hace más de una semana. La memoria es larga.",
    ),
    AchievementDef(
        slug="love_is_war",
        category="memoria",
        name="Love is War",
        description_hint="La relación con Sity tiene sus altibajos.",
        description_full="La opinión de Sity sobre ti ha bajado bastante. La guerra también es una forma de relación.",
    ),
    AchievementDef(
        slug="redemption",
        category="memoria",
        name="Redemption",
        description_hint="Las cosas pueden mejorar.",
        description_full="La opinión de Sity sobre ti pasó de negativa a positiva. El arco de redención existe.",
    ),
    AchievementDef(
        slug="a_long_time_ago",
        category="memoria",
        name="A Long Time Ago...",
        description_hint="Llevas tiempo aquí.",
        description_full="30 días desde que creaste tu cuenta. Ya eres parte del mueble.",
    ),
    AchievementDef(
        slug="youre_finally_awake",
        category="memoria",
        name="You're Finally Awake",
        description_hint="Alguien ha vuelto después de un tiempo.",
        description_full="7 días sin iniciar sesión y volviste. Bienvenida de vuelta.",
    ),
    # ------------------------------------------------------------------
    # Secretos (hidden until user unlocks at least one)
    # ------------------------------------------------------------------
    AchievementDef(
        slug="no_gods_no_masters",
        category="secretos",
        name="No Gods, No Masters",
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
        name="You Win",
        description_hint="A veces se pierde.",
        description_full="Lograste que Sity reconociera que tenías razón. No te acostumbres.",
        is_secret=True,
    ),
    AchievementDef(
        slug="curiosity_killed_the_cat",
        category="secretos",
        name="Curiosity Killed the Cat",
        description_hint="La curiosidad tiene consecuencias.",
        description_full=(
            "Intentaste descubrir el sistema de logros de forma sistemática. Funcionó, aparentemente."
        ),
        is_secret=True,
    ),
    AchievementDef(
        slug="its_over_9000",
        category="secretos",
        name="It's Over 9000!",
        description_hint="El medidor ha superado sus límites.",
        description_full="Opinión tan baja que rompe la escala. Logro difícil de conseguir sin dedicación activa.",
        is_secret=True,
    ),
    AchievementDef(
        slug="schizophrenia",
        category="secretos",
        name="Schizophrenia",
        description_hint="El sistema registra inconsistencias en los patrones.",
        description_full="La opinión de Sity sobre ti ha cambiado de signo demasiadas veces. La consistencia no es tu fuerte.",
        is_secret=True,
    ),
    AchievementDef(
        slug="the_cake_is_a_lie",
        category="secretos",
        name="The Cake Is a Lie",
        description_hint="El sistema ha detectado algo.",
        description_full="Sity se contradijo a sí misma y lo admitió. O quizás no. Quizás la tarta miente.",
        is_secret=True,
    ),
    AchievementDef(
        slug="gaslighting",
        category="secretos",
        name="Gaslighting",
        description_hint="El sistema ha detectado algo.",
        description_full="Sity dudó de su propia afirmación anterior. Las memorias son frágiles.",
        is_secret=True,
    ),
    AchievementDef(
        slug="determination",
        category="secretos",
        name="Determination",
        description_hint="La persistencia tiene nombre.",
        description_full="Cinco rechazos seguidos sobre la misma petición. La determinación no es siempre sabiduría.",
        is_secret=True,
    ),
    # ------------------------------------------------------------------
    # Domótica + Integraciones
    # ------------------------------------------------------------------
    AchievementDef(
        slug="glados",
        category="domotica",
        name="GLaDOS",
        description_hint="Controla un dispositivo de domótica con Sity.",
        description_full="Primer dispositivo controlado via Home Assistant. GLaDOS aprueba.",
    ),
    AchievementDef(
        slug="here_comes_the_sun",
        category="domotica",
        name="Here Comes the Sun",
        description_hint="Enciende o apaga una bombilla con Sity.",
        description_full="Primera luz controlada por Sity. Hay magia en encender una bombilla con la voz.",
    ),
    AchievementDef(
        slug="welcome_to_the_family",
        category="domotica",
        name="Welcome to the Family",
        description_hint="Controla varios dispositivos de domótica a la vez.",
        description_full="Dos dispositivos controlados en el mismo turno. Esto ya es un hogar inteligente.",
    ),
    AchievementDef(
        slug="radio_video",
        category="domotica",
        name="Radio/Video",
        description_hint="Pon música con Sity.",
        description_full="Primera canción reproducida con Sity. El soundtrack importa.",
    ),
    AchievementDef(
        slug="keep_on_rollin",
        category="domotica",
        name="Keep on rollin', baby",
        description_hint="Pídele a Sity que retome la música donde la dejaste.",
        description_full="Reanudaste la música sin especificar qué poner. Sity recuerda.",
    ),
    AchievementDef(
        slug="time_is_running_out",
        category="domotica",
        name="Time Is Running Out",
        description_hint="Crea un evento en tu calendario con Sity.",
        description_full="Primer evento de calendario creado. La organización es una virtud.",
    ),
    AchievementDef(
        slug="youve_got_mail",
        category="domotica",
        name="You've Got Mail",
        description_hint="Pídele a Sity que busque en tu correo.",
        description_full="Primera búsqueda en Gmail. El correo tiene memoria.",
    ),
    # ------------------------------------------------------------------
    # Tareas en background
    # ------------------------------------------------------------------
    AchievementDef(
        slug="voices",
        category="background",
        name="Voices",
        description_hint="Espera a que Sity tome la iniciativa por su cuenta.",
        description_full="Sity te escribió sin que se lo pidieras. La iniciativa es mutua.",
    ),
    AchievementDef(
        slug="ill_be_back",
        category="background",
        name="I'll Be Back",
        description_hint="Lanza una tarea en segundo plano y espera el resultado.",
        description_full="Primera tarea de fondo completada. Sity trabaja aunque no la veas.",
    ),
    AchievementDef(
        slug="what_is_a_man",
        category="background",
        name="What Is a Man?",
        description_hint="Escucha cómo Sity habla de sí misma.",
        description_full="Sity reflexionó sobre su propia naturaleza como proyecto. Una miserable pila de secretos.",
    ),
    AchievementDef(
        slug="achievement_unlocked",
        category="background",
        name="Achievement (Un)locked",
        description_hint="Un observador que se observa a sí mismo.",
        description_full="Sity detectó que estabas buscando logros de forma sistemática. El cazador cazado.",
    ),
]

# Lookup index: slug → AchievementDef (built once at import time)
_BY_SLUG: dict[str, AchievementDef] = {a.slug: a for a in CATALOG}


def get_by_slug(slug: str) -> Optional[AchievementDef]:
    return _BY_SLUG.get(slug)


VALID_SLUGS: frozenset[str] = frozenset(_BY_SLUG)

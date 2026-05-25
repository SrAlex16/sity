from __future__ import annotations

# Esto no debe crear acciones ni interpretar intención de negocio.
# Solo selecciona un toolset/contexto más pequeño usando señales técnicas conservadoras.
# La acción real debe venir siempre de una tool estructurada interpretada por Claude.

from app.cortex.tool_schemas import (
    BASE_TOOLSET,
    DEBUG_TOOLSET,
    FILE_AGENT_TOOLSET,
    GIT_TOOLSET,
    PERSONALITY_TOOLSET,
    SENSES_TOOLSET,
    SERVICE_CONFIG_TOOLSET,
    SERVICE_CONTROL_TOOLSET,
    SYSTEM_TOOLSET,
)


def _dedupe_tools(tools: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for tool in tools:
        name = tool.get("name", "")
        if name not in seen:
            seen.add(name)
            result.append(tool)
    return result


def message_mentions_file_path(message: str) -> bool:
    text = message.strip()
    return (
        "/" in text
        or "./" in text
        or "../" in text
        or "config/" in text
        or "backend/" in text
        or "frontend/" in text
        or "scripts/" in text
        or "README.md" in text
        or ".env" in text
    )


def _looks_like_conversation_only(message: str) -> bool:
    normalized = message.lower()
    action_terms = [
        "reinicia", "arranca", "para el servicio", "para el backend", "para el frontend",
        "haz pull", "haz push", "haz fetch", "haz commit",
        "saca una foto", "graba", "graba audio",
        "añade", "quita", "limpia capturas",
        "git", "repo", "repositorio",
        "foto", "cámara", "camara", "webcam", "micrófono", "microfono",
        "captura", "capturas",
        "debug", "traza", "trace", "logs",
        "servicio", "systemd", "backend", "frontend",
        "cpu", "ram", "disco", "raspberry",
        "personalidad", "sarcasmo", "calidez",
    ]
    return not any(term in normalized for term in action_terms)


def history_limit_for_message(message: str) -> int:
    normalized = message.lower()

    context_heavy_terms = [
        "ayer", "antes", "recuerdas", "dijiste", "hablamos",
        "historial", "qué hicimos", "que hicimos", "resume",
    ]

    single_action_terms = [
        "añade", "agrega", "quita", "elimina",
        "reinicia", "arranca", "para el",
        "servicios permitidos", "allowlist",
        "saca una foto", "graba audio", "graba ",
    ]

    technical_terms = [
        "error", "bug", "trace", "debug", "logs", "falló", "fallo",
        "repo", "git", "servicio", "backend", "frontend",
        "raspberry", "sistema", "cpu", "ram", "disco",
    ]

    if any(term in normalized for term in single_action_terms):
        return 4

    if any(term in normalized for term in context_heavy_terms):
        return 8

    if any(term in normalized for term in technical_terms):
        return 8

    return 4


def select_toolset_for_message(message: str) -> list[dict]:
    if message_mentions_file_path(message):
        return list(FILE_AGENT_TOOLSET)

    if _looks_like_conversation_only(message):
        return list(BASE_TOOLSET)

    normalized = message.lower()

    git_terms = [
        "git", "commit", "commits",
        "rama", "ramas", "branch", "branches",
        "pull", "push", "fetch", "checkout",
        "diff", "estado git", "status git",
    ]

    service_config_terms = [
        "añade", "agrega", "quita", "elimina",
        "servicios permitidos", "allowlist",
        "lista de servicios", "servicios que puedes",
        "add_allowed", "remove_allowed",
    ]

    service_control_terms = [
        "reinicia", "arranca", "para el", "detén", "detener",
        "estado del servicio", "systemctl",
        "sity-backend", "sity-frontend", "sity-test",
        "backend", "frontend",
    ]

    system_terms = [
        "raspberry", "sistema", "cpu", "ram", "memoria",
        "disco", "espacio", "procesos", "systemd",
    ]

    sense_terms = [
        "foto", "cámara", "camara", "webcam",
        "micro", "micrófono", "microfono", "audio",
        "captura", "capturas", "graba", "grabar",
    ]

    debug_terms = [
        "debug", "traza", "trace", "logs", "eventos",
        "errores", "herramientas",
    ]

    personality_fields = [
        "sarcasmo", "rudeza", "borde", "calidez", "honestidad",
        "paciencia", "melancolía", "melancolia", "tsundere",
        "verbosidad", "personalidad", "mala leche",
    ]

    personality_action_terms = [
        "sube", "baja", "ajusta", "cambia", "pon", "ponte", "slider",
    ]

    selected = list(BASE_TOOLSET)

    if any(term in normalized for term in git_terms):
        selected.extend(GIT_TOOLSET)

    if any(term in normalized for term in service_config_terms):
        selected.extend(SERVICE_CONFIG_TOOLSET)
    elif any(term in normalized for term in service_control_terms):
        selected.extend(SERVICE_CONTROL_TOOLSET)
    elif any(term in normalized for term in system_terms):
        selected.extend(SYSTEM_TOOLSET)

    if any(term in normalized for term in sense_terms):
        selected.extend(SENSES_TOOLSET)

    if any(term in normalized for term in debug_terms):
        selected.extend(DEBUG_TOOLSET)

    if (
        any(field in normalized for field in personality_fields)
        and any(term in normalized for term in personality_action_terms)
    ):
        selected.extend(PERSONALITY_TOOLSET)

    return _dedupe_tools(selected)

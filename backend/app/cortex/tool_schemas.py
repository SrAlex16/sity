PERSONALITY_PARAMETERS = [
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "tsundere_level",
    "contrarian_level",
    "patience_level",
    "refusal_chance",
    "helpfulness_level",
    "verbosity_level",
    "melancholy_level",
]

ALL_PERSONALITY_PARAMETERS_TEXT = ", ".join(PERSONALITY_PARAMETERS)


UPDATE_PERSONALITY_SETTINGS_TOOL = {
    "name": "update_personality_settings",
    "description": (
        "Actualiza uno o varios parámetros de personalidad de Sity. "
        f"Parámetros permitidos: {ALL_PERSONALITY_PARAMETERS_TEXT}. "
        "DEBES incluir siempre el campo 'updates' con al menos un elemento. "
        "Cada item de 'updates' debe tener parameter, operation y value. "
        "Never call this tool with an empty updates array. "
        "Never call this tool with only reason and no updates. "
        "When updating all personality parameters, include one update for every allowed parameter. "
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "updates": {
                "type": "array",
                "description": (
                    "Lista OBLIGATORIA de cambios. Nunca la omitas. "
                    "Para 'todo al 50%' incluye los 12 parámetros permitidos."
                ),
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "parameter": {
                            "type": "string",
                            "enum": PERSONALITY_PARAMETERS,
                            "description": "Parámetro exacto a modificar.",
                        },
                        "operation": {
                            "type": "string",
                            "enum": [
                                "set_absolute",
                                "increase_absolute",
                                "decrease_absolute",
                            ],
                            "description": (
                                "set_absolute fija el valor exacto. "
                                "increase_absolute suma value. "
                                "decrease_absolute resta value."
                            ),
                        },
                        "value": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "Valor entre 0 y 1. 50% = 0.5, 70% = 0.7.",
                        },
                    },
                    "required": ["parameter", "operation", "value"],
                },
            },
            "reason": {
                "type": "string",
                "description": "Breve razón del cambio.",
            },
        },
        "required": ["updates", "reason"],
    },
}


READ_RECENT_DEBUG_EVENTS_TOOL = {
    "name": "read_recent_debug_events",
    "description": (
        "Lee eventos técnicos recientes de debug/logs. "
        "Úsala SOLO si el usuario pide explícitamente logs, trazas, errores, eventos, "
        "tools ejecutadas, auditoría o diagnóstico técnico. "
        "NO la uses para mensajes conversacionales, preguntas ambiguas, seguimiento de conversación, "
        "cambios de personalidad, ni frases como 'qué tal ahora', 'mejor', 'ahora', 'hola' o similares. "
        "Si hay duda sobre si el usuario quiere debug o solo una respuesta conversacional, "
        "responde conversacionalmente sin usar esta herramienta."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "description": "Número máximo de eventos a leer. Usa 20 salvo que el usuario pida explícitamente más.",
            },
            "level": {
                "type": "string",
                "description": "Filtro opcional por nivel: INFO, WARN, ERROR, AUDIT.",
            },
            "module": {
                "type": "string",
                "description": (
                    "Filtro opcional por módulo. Úsalo solo si el usuario pide explícitamente "
                    "un módulo concreto. Para preguntas generales sobre tools, errores o actividad reciente, "
                    "omite module para que el backend devuelva eventos variados."
                ),
            },
        },
        "required": ["limit"],
    },
}


READ_TRACE_EVENTS_TOOL = {
    "name": "read_trace_events",
    "description": (
        "Lee todos los eventos asociados a un trace_id concreto. "
        "Úsala cuando el usuario pregunte por una traza específica o por la última traza visible."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "trace_id": {
                "type": "string",
                "description": "Trace id a consultar, por ejemplo trc_abc123.",
            }
        },
        "required": ["trace_id"],
    },
}


READ_SYSTEM_STATUS_TOOL = {
    "name": "read_system_status",
    "description": "Lee estado básico de la Raspberry: CPU, RAM y uptime aproximado.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
}


READ_DISK_USAGE_TOOL = {
    "name": "read_disk_usage",
    "description": "Lee el uso de disco de una ruta. Úsala para preguntas sobre espacio disponible.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta a consultar. Por defecto '/'.",
            }
        },
    },
}


READ_PROCESSES_TOOL = {
    "name": "read_processes",
    "description": "Lee procesos principales por consumo de CPU/RAM.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
            }
        },
    },
}


READ_SERVICE_STATUS_TOOL = {
    "name": "read_service_status",
    "description": "Lee el estado de un servicio systemd permitido.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Nombre del servicio permitido, por ejemplo ssh, sity-backend, minecraft.",
            }
        },
        "required": ["service_name"],
    },
}


LIST_ALLOWED_DIRECTORY_TOOL = {
    "name": "list_allowed_directory",
    "description": "Lista una carpeta permitida por configuración.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
            }
        },
        "required": ["path"],
    },
}


_GIT_REPO_PATH_FIELD = {
    "type": "string",
    "description": (
        "Ruta local del repo permitido. Para el repo sity usa /home/alex/projects/sity. "
        "Si el usuario dice 'sity', 'este repo' o 'el proyecto', usa /home/alex/projects/sity."
    ),
}

GIT_READ_STATUS_TOOL = {
    "name": "git_read_status",
    "description": "Lee git status de un repositorio permitido. Solo lectura.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "repo_path": _GIT_REPO_PATH_FIELD,
        },
        "required": ["repo_path"],
    },
}


GIT_READ_LOG_TOOL = {
    "name": "git_read_log",
    "description": "Lee últimos commits de un repositorio permitido. Solo lectura.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "repo_path": _GIT_REPO_PATH_FIELD,
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["repo_path"],
    },
}


GIT_READ_BRANCHES_TOOL = {
    "name": "git_read_branches",
    "description": "Lee ramas locales/remotas de un repositorio permitido. Solo lectura.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "repo_path": _GIT_REPO_PATH_FIELD,
        },
        "required": ["repo_path"],
    },
}


GIT_READ_REMOTES_TOOL = {
    "name": "git_read_remotes",
    "description": "Lee remotos configurados de un repositorio permitido. Solo lectura.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "repo_path": _GIT_REPO_PATH_FIELD,
        },
        "required": ["repo_path"],
    },
}


GIT_PROPOSE_ACTION_TOOL = {
    "name": "git_propose_action",
    "description": (
        "Crea una acción pendiente de Git que requiere confirmación explícita antes de ejecutarse. "
        "Úsala cuando el usuario pida git pull, git push, commit, crear rama, cambiar rama, fetch "
        "u otra acción que modifique el estado local o remoto del repositorio. "
        "fetch puede ser safe pero requiere confirmación en esta versión. "
        "pull, push, commit, create_branch y checkout_branch son acciones críticas o sensibles."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "fetch",
                    "pull_ff_only",
                    "push",
                    "create_branch",
                    "checkout_branch",
                    "commit",
                ],
            },
            "repo_path": {
                "type": "string",
                "description": "Repo permitido. Para Sity usa sity o /home/alex/projects/sity.",
            },
            "branch": {
                "type": "string",
                "description": (
                    "Rama objetivo cuando aplique. "
                    "Si el usuario proporciona un nombre de rama explícito en su mensaje, úsalo directamente. "
                    "La confirmación de seguridad ya la gestiona el sistema mediante la frase de confirmación; no pidas doble confirmación del nombre."
                ),
            },
            "remote": {
                "type": "string",
                "description": "Remote objetivo cuando aplique. Normalmente origin.",
            },
            "summary": {
                "type": "string",
                "description": "Resumen claro de lo que se propone hacer.",
            },
            "risk_level": {
                "type": "string",
                "enum": ["safe", "critical"],
                "description": "fetch puede ser safe. pull, push, commit, create_branch y checkout_branch son critical.",
            },
            "commit_message": {
                "type": "string",
                "description": "Mensaje de commit cuando action=commit.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Archivos a añadir al commit. Si se omite en commit, se hará git add -A.",
            },
        },
        "required": ["action", "repo_path", "summary", "risk_level"],
    },
}


NO_ACTION_REQUIRED_TOOL = {
    "name": "no_action_required",
    "description": (
        "Usa esta herramienta cuando el mensaje del usuario no requiere ejecutar ninguna acción, "
        "leer logs, consultar sistema, tocar Git ni cambiar configuración. "
        "Sirve para mensajes conversacionales, aclaraciones, respuestas cortas, bromas, seguimiento "
        "de una conversación o preguntas que pueden responderse con el contexto actual. "
        "Ejemplos: 'mejor?', 'y ahora?', 'ok', 'gracias', 'tiene sentido', reacciones al resultado "
        "anterior, preguntas sobre tu personalidad que ya están respondidas en el prompt. "
        "Si puedes responder sin ninguna herramienta, hazlo directamente sin usar no_action_required."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {
                "type": "string",
                "description": "Por qué no hace falta herramienta.",
            }
        },
        "required": ["reason"],
    },
}


SYSTEM_PROPOSE_ACTION_TOOL = {
    "name": "system_propose_action",
    "description": (
        "Crea una acción pendiente de sistema que requiere confirmación explícita antes de ejecutarse. "
        "Úsala cuando el usuario pida arrancar, parar o reiniciar un servicio permitido. "
        "En esta versión solo están permitidos sity-backend y sity-frontend. "
        "No ejecuta la acción directamente."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "start_service",
                    "stop_service",
                    "restart_service",
                ],
            },
            "service_name": {
                "type": "string",
                "enum": [
                    "sity-backend",
                    "sity-frontend",
                ],
            },
            "summary": {
                "type": "string",
                "description": "Resumen claro de lo que se propone hacer.",
            },
            "risk_level": {
                "type": "string",
                "enum": ["safe", "critical"],
                "description": "Para servicios allowlist usa safe.",
            },
        },
        "required": ["action", "service_name", "summary", "risk_level"],
    },
}


PERSONALITY_TOOLSET = [
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

DEBUG_TOOLSET = [
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

SYSTEM_TOOLSET = [
    READ_SYSTEM_STATUS_TOOL,
    READ_DISK_USAGE_TOOL,
    READ_PROCESSES_TOOL,
    READ_SERVICE_STATUS_TOOL,
    LIST_ALLOWED_DIRECTORY_TOOL,
    SYSTEM_PROPOSE_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

GIT_TOOLSET = [
    GIT_READ_STATUS_TOOL,
    GIT_READ_LOG_TOOL,
    GIT_READ_BRANCHES_TOOL,
    GIT_READ_REMOTES_TOOL,
    GIT_PROPOSE_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

ALL_TOOLS = [
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
    READ_SYSTEM_STATUS_TOOL,
    READ_DISK_USAGE_TOOL,
    READ_PROCESSES_TOOL,
    READ_SERVICE_STATUS_TOOL,
    LIST_ALLOWED_DIRECTORY_TOOL,
    GIT_READ_STATUS_TOOL,
    GIT_READ_LOG_TOOL,
    GIT_READ_BRANCHES_TOOL,
    GIT_READ_REMOTES_TOOL,
    GIT_PROPOSE_ACTION_TOOL,
    SYSTEM_PROPOSE_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

TOOLS = ALL_TOOLS

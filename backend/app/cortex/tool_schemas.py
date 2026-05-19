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


LIST_CAMERA_DEVICES_TOOL = {
    "name": "list_camera_devices",
    "description": "Lista cámaras disponibles. No activa la cámara ni captura imágenes.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


LIST_AUDIO_DEVICES_TOOL = {
    "name": "list_audio_devices",
    "description": "Lista dispositivos de audio. Debe distinguir dispositivos virtuales como Loopback del micrófono real.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


CAPTURE_CAMERA_SNAPSHOT_TOOL = {
    "name": "capture_camera_snapshot",
    "description": (
        "Captura una única imagen con la cámara conectada. "
        "Úsala cuando el usuario pida explícitamente hacer/sacar/tomar/probar una foto o imagen. "
        "No la uses para captura continua ni vigilancia."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "Dispositivo de cámara. Por defecto /dev/video0.",
            },
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "skip_frames": {
                "type": "integer",
                "description": "Frames a saltar para autoexposición. Por defecto 20.",
            },
        },
        "additionalProperties": False,
    },
}


RECORD_AUDIO_SAMPLE_TOOL = {
    "name": "record_audio_sample",
    "description": (
        "Graba una muestra corta de audio desde el micrófono real de la webcam. "
        "Úsala cuando el usuario pida explícitamente grabar una muestra o prueba de audio. "
        "No uses Loopback como micrófono. No la uses para grabación continua."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "duration_seconds": {
                "type": "integer",
                "description": "Duración entre 1 y 10 segundos. Por defecto 3.",
            },
            "device": {
                "type": "string",
                "description": "Dispositivo ALSA. Por defecto plughw:CARD=webcam,DEV=0.",
            },
        },
        "additionalProperties": False,
    },
}


CANCEL_PENDING_ACTION_TOOL = {
    "name": "cancel_pending_action",
    "description": (
        "Cancela una acción pendiente cuando el usuario indique que quiere dejarlo, cancelar o no seguir. "
        "Proporciona el action_id si lo conoces. Si no, el backend intentará cancelar la más reciente activa."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action_id": {
                "type": "string",
                "description": "ID de la acción pendiente, por ejemplo act_abc12345. Opcional.",
            },
            "reason": {
                "type": "string",
                "description": "Razón de la cancelación.",
            },
        },
        "additionalProperties": False,
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


_SERVICE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "service_name": {
            "type": "string",
            "enum": ["sity-backend", "sity-frontend"],
            "description": "Nombre exacto del servicio systemd a controlar.",
        },
    },
    "required": ["service_name"],
}

RESTART_SERVICE_TOOL = {
    "name": "restart_service",
    "description": "Reinicia un servicio systemd permitido. Requiere confirmación del usuario antes de ejecutarse.",
    "input_schema": _SERVICE_SCHEMA,
}

START_SERVICE_TOOL = {
    "name": "start_service",
    "description": "Arranca un servicio systemd permitido. Requiere confirmación del usuario antes de ejecutarse.",
    "input_schema": _SERVICE_SCHEMA,
}

STOP_SERVICE_TOOL = {
    "name": "stop_service",
    "description": "Para un servicio systemd permitido. Requiere confirmación del usuario antes de ejecutarse.",
    "input_schema": _SERVICE_SCHEMA,
}


ADD_ALLOWED_SERVICE_TOOL = {
    "name": "add_allowed_service",
    "description": (
        "Añade un servicio systemd concreto a la allowlist de servicios controlables por Sity. "
        "Úsala solo cuando el usuario pida explícitamente añadir un servicio concreto. "
        "Requiere confirmación del usuario antes de ejecutarse."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Nombre exacto del servicio systemd, por ejemplo sity-test.",
            },
        },
        "required": ["service_name"],
    },
}

REMOVE_ALLOWED_SERVICE_TOOL = {
    "name": "remove_allowed_service",
    "description": (
        "Quita un servicio systemd concreto de la allowlist de servicios controlables por Sity. "
        "Úsala solo cuando el usuario pida explícitamente quitar un servicio concreto. "
        "Requiere confirmación del usuario antes de ejecutarse."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "service_name": {
                "type": "string",
                "description": "Nombre exacto del servicio systemd.",
            },
        },
        "required": ["service_name"],
    },
}

LIST_ALLOWED_SERVICES_TOOL = {
    "name": "list_allowed_services",
    "description": (
        "Lista los servicios que Sity puede leer o controlar. "
        "No modifica la allowlist."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


GET_CAPTURE_STORAGE_SUMMARY_TOOL = {
    "name": "get_capture_storage_summary",
    "description": (
        "Consulta cuántas capturas de cámara/audio hay guardadas y cuánto ocupan. "
        "No borra nada."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


CLEAN_OLD_CAPTURES_TOOL = {
    "name": "clean_old_captures",
    "description": (
        "Limpia capturas antiguas de cámara/audio dentro del directorio captures. "
        "Úsala cuando el usuario pida limpiar, borrar capturas antiguas o evitar acumulación. "
        "Solo borra archivos permitidos dentro de captures/camera y captures/audio."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "older_than_days": {
                "type": "integer",
                "description": "Borra archivos con más de estos días. Por defecto 7.",
            },
            "max_files_per_type": {
                "type": "integer",
                "description": "Mantiene como mínimo este máximo de archivos recientes por tipo. Por defecto 100.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Si true, solo simula la limpieza sin borrar archivos.",
            },
        },
        "additionalProperties": False,
    },
}


READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Lee un archivo permitido por la allowlist de Sity. "
        "Úsala cuando el usuario pida ver, revisar o inspeccionar un archivo concreto."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta del archivo a leer. Puede ser absoluta o relativa al proyecto.",
            },
        },
        "required": ["path"],
    },
}

LIST_DIRECTORY_TOOL = {
    "name": "list_directory",
    "description": (
        "Lista el contenido de un directorio permitido por la allowlist de Sity. "
        "Úsala cuando el usuario pida ver qué hay en una carpeta o explorar el repo."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta del directorio a listar. Puede ser absoluta o relativa al proyecto.",
            },
        },
        "required": ["path"],
    },
}

FILE_READ_TOOLSET = [
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
]


PERSONALITY_TOOLSET = [
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

BASE_TOOLSET: list[dict] = []

DEBUG_TOOLSET = [
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

SERVICE_CONFIG_TOOLSET = [
    LIST_ALLOWED_SERVICES_TOOL,
    ADD_ALLOWED_SERVICE_TOOL,
    REMOVE_ALLOWED_SERVICE_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

SERVICE_CONTROL_TOOLSET = [
    READ_SERVICE_STATUS_TOOL,
    START_SERVICE_TOOL,
    STOP_SERVICE_TOOL,
    RESTART_SERVICE_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

SYSTEM_TOOLSET = [
    READ_SYSTEM_STATUS_TOOL,
    READ_DISK_USAGE_TOOL,
    READ_PROCESSES_TOOL,
    READ_SERVICE_STATUS_TOOL,
    LIST_ALLOWED_DIRECTORY_TOOL,
    RESTART_SERVICE_TOOL,
    START_SERVICE_TOOL,
    STOP_SERVICE_TOOL,
    SYSTEM_PROPOSE_ACTION_TOOL,
    ADD_ALLOWED_SERVICE_TOOL,
    REMOVE_ALLOWED_SERVICE_TOOL,
    LIST_ALLOWED_SERVICES_TOOL,
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

SENSES_TOOLSET = [
    LIST_CAMERA_DEVICES_TOOL,
    LIST_AUDIO_DEVICES_TOOL,
    CAPTURE_CAMERA_SNAPSHOT_TOOL,
    RECORD_AUDIO_SAMPLE_TOOL,
    GET_CAPTURE_STORAGE_SUMMARY_TOOL,
    CLEAN_OLD_CAPTURES_TOOL,
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
    RESTART_SERVICE_TOOL,
    START_SERVICE_TOOL,
    STOP_SERVICE_TOOL,
    SYSTEM_PROPOSE_ACTION_TOOL,
    ADD_ALLOWED_SERVICE_TOOL,
    REMOVE_ALLOWED_SERVICE_TOOL,
    LIST_ALLOWED_SERVICES_TOOL,
    LIST_CAMERA_DEVICES_TOOL,
    LIST_AUDIO_DEVICES_TOOL,
    CAPTURE_CAMERA_SNAPSHOT_TOOL,
    RECORD_AUDIO_SAMPLE_TOOL,
    GET_CAPTURE_STORAGE_SUMMARY_TOOL,
    CLEAN_OLD_CAPTURES_TOOL,
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    CANCEL_PENDING_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

TOOLS = ALL_TOOLS


TOOL_RISK_POLICY: dict[str, str] = {
    "list_camera_devices": "read",
    "list_audio_devices": "read",
    "capture_camera_snapshot": "sensitive_direct",
    "record_audio_sample": "sensitive_direct",
    "git_fetch": "safe_confirm",
    "git_pull": "critical_confirm",
    "git_push": "critical_confirm",
    "git_commit": "critical_confirm",
    "git_create_branch": "critical_confirm",
    "git_checkout_branch": "critical_confirm",
    "system_restart_service": "safe_confirm",
    "system_start_service": "safe_confirm",
    "system_stop_service": "safe_confirm",
    "system_config_update": "critical_confirm",
}

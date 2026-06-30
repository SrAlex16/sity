from app.core.runtime_config import get_runtime_config
from app.system.allowed_services import get_allowed_systemd_services

# Built at import time from system_access.yaml safe_actions.allowed_services.
# Changing the YAML requires a process restart to take effect.
_ALLOWED_SYSTEMD_SERVICES: list[str] = list(get_allowed_systemd_services())

# Built at import time from SITY_PROJECT_ROOT / runtime config.
# Appears in git tool descriptions so the model knows which path to use.
_PROJECT_ROOT: str = str(get_runtime_config().project_root)

PERSONALITY_PARAMETERS = [
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "frialdad_afectiva_level",
    "contrarian_level",
    "patience_level",
    "refusal_chance",
    "helpfulness_level",
    "verbosity_level",
    "melancholy_level",
    "skepticism_level",
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
                    f"Para 'todo al 50%' incluye los {len(PERSONALITY_PARAMETERS)} parámetros permitidos."
                ),
                "minItems": 1,
                "maxItems": len(PERSONALITY_PARAMETERS),
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


READ_OWN_TRACE_TOOL = {
    "name": "read_own_trace",
    "description": (
        "Lee el log de hoy (o ayer si no hay datos hoy) y devuelve un resumen estructurado "
        "de los turnos de conversación recientes: tokens usados, tools llamadas, modo de salida, "
        "historial inyectado, búsqueda de memoria y fragmentos TTS. "
        "Úsala cuando el usuario pregunta por el comportamiento interno de un turno reciente: "
        "por qué se buscó en memoria, cuántos tokens consumió, qué tools se ejecutaron, etc. "
        "Disponible solo en modo debug_test. No la uses para responder mensajes conversacionales."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "trace_id": {
                "type": "string",
                "description": (
                    "trace_id exacto a consultar (ej. trc_abc123). "
                    "Si se omite, devuelve los n_recent turnos más recientes."
                ),
            },
            "n_recent": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Número de turnos recientes a devolver cuando no se da trace_id. Por defecto 1.",
            },
        },
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
        f"Ruta local del repo permitido. Para el repo sity usa {_PROJECT_ROOT}. "
        f"Si el usuario dice 'sity', 'este repo' o 'el proyecto', usa {_PROJECT_ROOT}."
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
    "description": (
        "Lee commits recientes de un repositorio permitido. Solo lectura, sin riesgo. "
        "Úsala SIEMPRE que el usuario pregunte qué se ha hecho en el proyecto "
        "recientemente, hoy, esta semana, o en cualquier rango de tiempo — por ejemplo: "
        "'¿qué he hecho hoy?', 'revisa el historial', '¿qué cambios se han hecho?', "
        "'¿qué commits hay?'. NUNCA inventes commits, nombres de archivo ni contenido "
        "de cambios: consulta esta herramienta y devuelve lo que devuelva. "
        "Usa hours_back para filtrar por tiempo (p.ej. 24 para las últimas 24 horas)."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "repo_path": _GIT_REPO_PATH_FIELD,
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "hours_back": {
                "type": "integer",
                "minimum": 1,
                "maximum": 720,
                "description": "Filtrar commits de las últimas N horas. Sin este parámetro devuelve los últimos `limit` commits sin filtro temporal.",
            },
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
                "description": f"Repo permitido. Para Sity usa sity o {_PROJECT_ROOT}.",
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
        "Cancela una acción pendiente identificada de forma estructural. "
        "Úsala solo si el usuario proporciona un action_id explícito o si el contexto estructurado del backend identifica una acción pendiente concreta. "
        "No la uses para mensajes conversacionales ambiguos."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action_id": {
                "type": "string",
                "description": "ID de la acción pendiente, por ejemplo act_abc12345.",
            },
            "reason": {
                "type": "string",
                "description": "Razón de la cancelación.",
            },
        },
        "required": ["action_id"],
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
        "Los servicios permitidos están definidos en system_access.yaml bajo safe_actions.allowed_services. "
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
                "enum": _ALLOWED_SYSTEMD_SERVICES,
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
            "enum": _ALLOWED_SYSTEMD_SERVICES,
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

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": (
        "Escribe o sobreescribe un archivo dentro de las rutas permitidas por la allowlist de Sity. "
        "NUNCA se ejecuta directamente: siempre crea una acción pendiente que requiere confirmación explícita. "
        "Úsala cuando el usuario pida crear, escribir o modificar un archivo concreto."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta del archivo a escribir. Puede ser absoluta o relativa al proyecto.",
            },
            "content": {
                "type": "string",
                "description": "Contenido completo a escribir en el archivo.",
            },
            "create_parent_dirs": {
                "type": "boolean",
                "description": "Si true, crea los directorios padre si no existen. Por defecto false.",
            },
        },
        "required": ["path", "content"],
    },
}

APPLY_TEXT_PATCH_TOOL = {
    "name": "apply_text_patch",
    "description": (
        "Propone modificar un archivo permitido reemplazando un fragmento exacto de texto por otro. "
        "Esta acción siempre requiere confirmación antes de ejecutarse. "
        "Úsala cuando el usuario pida cambiar una parte concreta de un archivo sin sobrescribirlo entero."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "description": "Ruta del archivo a modificar. Puede ser absoluta o relativa al proyecto.",
            },
            "old_text": {
                "type": "string",
                "description": "Texto exacto existente que se reemplazará. Debe aparecer literalmente en el archivo.",
            },
            "new_text": {
                "type": "string",
                "description": "Texto nuevo que sustituirá al texto anterior.",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
}

PROPOSE_MODEL_UPGRADE_TOOL = {
    "name": "propose_model_upgrade",
    "description": (
        "Propón cambiar al modelo más potente para esta tarea cuando consideres "
        "que requiere más capacidad de la que tienes disponible. Úsala solo cuando "
        "la tarea sea claramente compleja: debugging con trazas largas, refactors "
        "de arquitectura, análisis de múltiples archivos, o diseño con muchas "
        "restricciones. NO la uses para conversación normal, preguntas cortas, "
        "tools simples o cualquier tarea que puedas resolver bien."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Explica brevemente por qué esta tarea se beneficiaría del modelo más potente.",
            }
        },
        "required": ["reason"],
    },
}

FILE_READ_TOOLSET = [
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
]

LIST_FILE_CHANGES_TOOL = {
    "name": "list_file_changes",
    "description": (
        "Lista los últimos cambios de archivos hechos por Sity leyendo el audit log real. "
        "Úsala SIEMPRE que el usuario pregunte qué archivos ha tocado Sity, qué cambió recientemente, "
        "qué acciones de archivo ejecutó, qué backups existen o quiera revisar auditoría de cambios. "
        "No respondas de memoria ni desde el historial conversacional para estas preguntas. "
        "No lee el contenido de backups."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Número máximo de eventos recientes a devolver. Máximo 50.",
            },
        },
    },
}

ROLLBACK_FILE_CHANGE_TOOL = {
    "name": "rollback_file_change",
    "description": (
        "Propone restaurar un archivo desde un backup creado por Sity. "
        "Esta acción siempre requiere confirmación antes de ejecutarse. "
        "Úsala cuando el usuario pida revertir un cambio de archivo, restaurar un backup "
        "o deshacer una modificación previa. "
        "Si el usuario pide revertir el último cambio de archivo, primero usa list_file_changes "
        "para localizar el último evento con backup.created=true y luego usa rollback_file_change "
        "con ese backup_path. "
        "El backup debe venir de data/file_backups y estar asociado al audit log."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "backup_path": {
                "type": "string",
                "description": (
                    "Ruta del backup que se restaurará. Debe estar dentro de data/file_backups "
                    "y aparecer asociado a un evento en el audit log."
                ),
            },
        },
        "required": ["backup_path"],
    },
}

APPLY_UNIFIED_DIFF_TOOL = {
    "name": "apply_unified_diff",
    "description": (
        "Propone modificar un único archivo permitido aplicando un unified diff. "
        "Esta acción siempre requiere confirmación antes de ejecutarse. "
        "Úsala cuando el usuario pida cambios de código o modificaciones multilinea que se expresen mejor como diff. "
        "El diff debe incluir cabeceras --- y +++ y hunks @@. "
        "No uses esta tool para múltiples archivos a la vez."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "diff": {
                "type": "string",
                "description": (
                    "Unified diff para un único archivo. Debe incluir líneas --- path, +++ path y hunks @@."
                ),
            },
        },
        "required": ["diff"],
        "additionalProperties": False,
    },
}

APPLY_MULTI_FILE_UNIFIED_DIFF_PLAN_TOOL = {
    "name": "apply_multi_file_unified_diff_plan",
    "description": (
        "Analiza un unified diff que puede afectar a varios archivos permitidos y propone aplicarlo "
        "como acciones separadas por archivo. No aplica cambios directamente. "
        "Úsala SIEMPRE que el usuario proporcione un patch/unified diff multiarchivo. "
        "Si cualquiera de los archivos del patch está fuera de allowlist, bloqueado, es sensible "
        "o no valida correctamente, debes rechazar TODO el plan. "
        "No propongas aplicar solo la parte permitida. "
        "Cada archivo válido se convertirá en una acción pendiente independiente de apply_unified_diff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "diff": {
                "type": "string",
                "description": (
                    "Unified diff que puede contener cambios para varios archivos. "
                    "Debe incluir cabeceras --- y +++ y hunks @@ para cada archivo."
                ),
            },
        },
        "required": ["diff"],
        "additionalProperties": False,
    },
}

FIND_LATEST_REVERSIBLE_FILE_CHANGE_TOOL = {
    "name": "find_latest_reversible_file_change",
    "description": (
        "Busca en el audit log el último cambio de archivo reversible con backup disponible. "
        "Por defecto ignora rollbacks para evitar deshacer un rollback accidentalmente. "
        "Úsala cuando el usuario pida revertir, deshacer o restaurar el último cambio de archivo "
        "sin dar un backup concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "include_rollbacks": {
                "type": "boolean",
                "description": (
                    "Si true, también permite seleccionar eventos rollback_file_change como reversibles. "
                    "Usar solo si el usuario pide explícitamente revertir un rollback."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}

ROLLBACK_LATEST_FILE_CHANGE_TOOL = {
    "name": "rollback_latest_file_change",
    "description": (
        "Propone revertir el último cambio de archivo reversible encontrado en el audit log. "
        "Por defecto ignora rollbacks para no deshacer un rollback accidentalmente. "
        "Siempre requiere confirmación antes de ejecutar. "
        "Úsala cuando el usuario diga 'revierte el último cambio de archivo', "
        "'deshaz el último cambio de archivo' o equivalente, sin dar un backup concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "include_rollbacks": {
                "type": "boolean",
                "description": (
                    "Si true, permite revertir un rollback anterior. "
                    "Usar solo si el usuario lo pide explícitamente."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}

FILE_AGENT_TOOLSET = [
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
    WRITE_FILE_TOOL,
    APPLY_TEXT_PATCH_TOOL,
    APPLY_UNIFIED_DIFF_TOOL,
    APPLY_MULTI_FILE_UNIFIED_DIFF_PLAN_TOOL,
    LIST_FILE_CHANGES_TOOL,
    FIND_LATEST_REVERSIBLE_FILE_CHANGE_TOOL,
    ROLLBACK_LATEST_FILE_CHANGE_TOOL,
    ROLLBACK_FILE_CHANGE_TOOL,
]


PERSONALITY_TOOLSET = [
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Busca información actualizada en internet. Úsala cuando el usuario "
        "pregunte por algo que puede haber cambiado recientemente (noticias, "
        "precios, eventos, tiempo, personas públicas, software), cuando necesites "
        "datos actuales que no están en tu historial de conversación, o cuando "
        "el usuario lo pida explícitamente. NO la uses para conversación general, "
        "conocimiento estable o cosas que ya sabes con certeza."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "La consulta de búsqueda en español o inglés según convenga."
            },
            "is_dynamic": {
                "type": "boolean",
                "description": (
                    "True si la información buscada cambia frecuentemente "
                    "(noticias, precios, resultados deportivos, clima, eventos "
                    "en curso). False si es información estable (documentación, "
                    "conceptos, historia, datos que no cambian con el tiempo). "
                    "Determina cuánto tiempo se cachea el resultado."
                )
            }
        },
        "required": ["query", "is_dynamic"]
    }
}


SEARCH_CONVERSATION_HISTORY_TOOL = {
    "name": "search_conversation_history",
    "description": (
        "Busca en el historial completo de conversación almacenado en la base de datos. "
        "Úsala cuando responder dependa de conversación anterior que no aparece en el historial visible. "
        "Devuelve ventanas cronológicas alrededor de las coincidencias encontradas, no solo el mensaje adyacente. "
        "No inventes ni pidas al usuario que repita algo antes de consultar esta herramienta. "
        "La búsqueda usa palabras clave; términos simples tienen mayor cobertura que frases largas."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Término o frase a buscar en el historial. "
                    "Usa palabras clave simples para mayor cobertura."
                ),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Número máximo de fragmentos a devolver. Por defecto 5.",
            },
        },
        "required": ["query"],
    },
}

BASE_TOOLSET: list[dict] = [
    # Minimal conversational toolset. No file tools here.
    # FILE_AGENT_TOOLSET is added structurally by toolset_selector:
    #   - explicit tool name detected from schemas/registry
    #   - file path detected by message_mentions_file_path
    WEB_SEARCH_TOOL,
    SEARCH_CONVERSATION_HISTORY_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

PENDING_ACTION_TOOLSET: list[dict] = [
    CANCEL_PENDING_ACTION_TOOL,
]

DEBUG_TOOLSET = [
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

# Available only when dataset_source == "debug_test" (injected in routes_chat.py).
TRACE_TOOLSET = [
    READ_OWN_TRACE_TOOL,
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
    WEB_SEARCH_TOOL,
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    READ_OWN_TRACE_TOOL,
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
    WRITE_FILE_TOOL,
    APPLY_TEXT_PATCH_TOOL,
    LIST_FILE_CHANGES_TOOL,
    APPLY_UNIFIED_DIFF_TOOL,
    APPLY_MULTI_FILE_UNIFIED_DIFF_PLAN_TOOL,
    FIND_LATEST_REVERSIBLE_FILE_CHANGE_TOOL,
    ROLLBACK_LATEST_FILE_CHANGE_TOOL,
    ROLLBACK_FILE_CHANGE_TOOL,
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

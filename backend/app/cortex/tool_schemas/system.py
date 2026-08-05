from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL
from app.system.allowed_services import get_allowed_systemd_services

_ALLOWED_SYSTEMD_SERVICES: list[str] = list(get_allowed_systemd_services())

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

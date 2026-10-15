from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL
from app.system.allowed_services import get_allowed_systemd_services

_ALLOWED_SYSTEMD_SERVICES: list[str] = list(get_allowed_systemd_services())

READ_SYSTEM_STATUS_TOOL = {
    "name": "read_system_status",
    "description": (
        "Lee el estado actual del sistema: porcentaje de CPU en uso, RAM (total, disponible, usada y %), "
        "timestamp de arranque, IP local y hostname. "
        "Úsala para preguntas como '¿cuánta RAM estás usando?', '¿cuál es la IP local?', "
        "'¿ha cambiado la dirección de red?', '¿cuánto tiempo lleva encendida la Raspberry?', "
        "'¿está cargada la CPU?', '¿cómo está el sistema ahora mismo?'."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
}


READ_DISK_USAGE_TOOL = {
    "name": "read_disk_usage",
    "description": (
        "Lee el espacio en disco de una ruta: total, usado, libre y porcentaje de uso. "
        "Úsala para preguntas como '¿cuánto espacio libre queda?', '¿está el disco casi lleno?', "
        "'¿cuánto ocupa la partición principal?', '¿me quedo sin espacio?'. "
        "Por defecto consulta la raíz '/'."
    ),
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
    "description": (
        "Lista los procesos activos ordenados por mayor consumo de CPU y RAM, "
        "con nombre, PID, usuario y porcentajes de uso. "
        "Úsala para preguntas como '¿qué está consumiendo más CPU?', '¿qué proceso acapara la memoria?', "
        "'¿hay algo que se esté disparando?', '¿qué está corriendo ahora mismo?', "
        "'ps aux', '¿qué proceso es el responsable del lag?'."
    ),
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
    "description": (
        "Lee si un servicio systemd está activo, inactivo o caído. "
        "Úsala para preguntas como '¿está corriendo sity-backend?', '¿está caído el servidor web?', "
        "'¿está Caddy activo?', '¿funciona homeassistant?', '¿qué pasa con el servicio X?'."
    ),
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
    "description": (
        "Lista el contenido de una carpeta del proyecto explícitamente permitida en system_access.yaml: "
        "devuelve nombre, ruta y tipo de hasta 200 entradas. "
        "Solo funciona con rutas configuradas en la allowlist (como el directorio de uploads o logs del proyecto). "
        "Para listar directorios arbitrarios del sistema (/home, /tmp, /etc…) usa execute_shell con ls. "
        "Úsala para '¿qué hay en uploads?', '¿qué archivos de log tiene el proyecto?', '¿existe ese archivo en el proyecto?'."
    ),
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
        "Propone arrancar, parar o reiniciar un servicio systemd de la allowlist — "
        "la acción queda pendiente hasta que el usuario la confirme explícitamente; no se ejecuta sola. "
        "Úsala cuando el usuario pida gestionar un servicio: 'reinicia el backend', 'para homeassistant', "
        "'arranca sity-test', 'reinicia Caddy'. "
        "Los servicios disponibles están en la allowlist de system_access.yaml."
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
    "description": (
        "Reinicia un servicio systemd de la allowlist. Espera a que quede activo y devuelve el estado final. "
        "Úsala cuando el usuario confirme que quiere reiniciar: 'sí, reinícialo', 'adelante', 'hazlo'."
    ),
    "input_schema": _SERVICE_SCHEMA,
}

START_SERVICE_TOOL = {
    "name": "start_service",
    "description": (
        "Arranca un servicio systemd de la allowlist. Espera a que quede activo y devuelve el estado final. "
        "Úsala cuando el usuario confirme que quiere arrancar el servicio."
    ),
    "input_schema": _SERVICE_SCHEMA,
}

STOP_SERVICE_TOOL = {
    "name": "stop_service",
    "description": (
        "Para un servicio systemd de la allowlist. Espera a que quede inactivo y devuelve el estado final. "
        "Úsala cuando el usuario confirme que quiere detener el servicio."
    ),
    "input_schema": _SERVICE_SCHEMA,
}


ADD_ALLOWED_SERVICE_TOOL = {
    "name": "add_allowed_service",
    "description": (
        "Añade un servicio systemd a la allowlist para que Sity pueda controlarlo en el futuro. "
        "Úsala solo cuando el usuario pida explícitamente ampliar la lista: "
        "'añade minecraft a los servicios permitidos', 'quiero que puedas controlar sity-test'. "
        "Requiere confirmación antes de ejecutarse."
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
        "Quita un servicio systemd de la allowlist para que Sity deje de poder controlarlo. "
        "Úsala solo cuando el usuario pida explícitamente reducir la lista: "
        "'quita minecraft de los servicios', 'no quiero que puedas tocar homeassistant'. "
        "Requiere confirmación antes de ejecutarse."
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
        "Lista los servicios systemd que Sity tiene permitido leer o controlar. "
        "Úsala para preguntas como '¿qué servicios puedes gestionar?', '¿está X en la lista de permitidos?'. "
        "Solo lectura — no modifica la allowlist."
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

EXECUTE_SHELL_TOOL = {
    "name": "execute_shell",
    "description": (
        "Ejecuta cualquier comando de shell en el servidor. "
        "Comandos de lectura (ls, cat, grep, find, git status, git log, git diff, git show, "
        "git branch, git remote, curl GET, python3 -c, node -e…) se ejecutan directamente. "
        "Comandos de escritura (mkdir, rm, cp, mv, pip install, npm install, systemctl…) "
        "crean una acción pendiente que requiere confirmación (o se ejecutan si yolo_mode está activo). "
        "sudo reboot/shutdown/halt siempre están bloqueados. "
        "Úsala cuando el usuario pida: 'ejecuta git diff', 'haz git status', 'muéstrame los últimos commits', "
        "'lista /home', 'ls -la', 'qué hay en /tmp', 'ejecuta este script', 'instala X', "
        "'comprueba el log', 'corre el test', 'borra el archivo Y'. "
        "Para listar cualquier directorio del sistema usa esta herramienta con ls, no list_allowed_directory."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "command": {
                "type": "string",
                "description": "Comando de shell a ejecutar.",
            },
            "working_dir": {
                "type": "string",
                "description": (
                    "Directorio de trabajo relativo al project root. "
                    "Por defecto '.' (project root)."
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Segundos máximo de ejecución. Por defecto 30.",
            },
        },
        "required": ["command"],
    },
}


SET_YOLO_MODE_TOOL = {
    "name": "set_yolo_mode",
    "description": (
        "Activa o desactiva el modo yolo para el usuario actual. "
        "En modo yolo las acciones pendientes (escritura de archivos, comandos de sistema, etc.) "
        "se ejecutan inmediatamente sin pedir confirmación. "
        "Git push siempre requiere confirmación aunque yolo_mode esté activado. "
        "Solo disponible para administradores."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "enabled": {
                "type": "boolean",
                "description": "true para activar yolo mode, false para desactivarlo.",
            },
        },
        "required": ["enabled"],
    },
}


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
    SET_YOLO_MODE_TOOL,
    EXECUTE_SHELL_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

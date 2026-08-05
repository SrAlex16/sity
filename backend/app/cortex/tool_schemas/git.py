from app.core.runtime_config import get_runtime_config
from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL

_PROJECT_ROOT: str = str(get_runtime_config().project_root)

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


GIT_TOOLSET = [
    GIT_READ_STATUS_TOOL,
    GIT_READ_LOG_TOOL,
    GIT_READ_BRANCHES_TOOL,
    GIT_READ_REMOTES_TOOL,
    GIT_PROPOSE_ACTION_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

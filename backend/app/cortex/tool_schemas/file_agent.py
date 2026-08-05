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


FILE_READ_TOOLSET = [
    READ_FILE_TOOL,
    LIST_DIRECTORY_TOOL,
]

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

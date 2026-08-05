from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL

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


DEBUG_TOOLSET = [
    READ_RECENT_DEBUG_EVENTS_TOOL,
    READ_TRACE_EVENTS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

TRACE_TOOLSET = [
    READ_OWN_TRACE_TOOL,
]

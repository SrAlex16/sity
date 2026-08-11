SET_TIMER_TOOL = {
    "name": "set_timer",
    "description": (
        "Crea un temporizador que se disparará después de un número de segundos. "
        "Cuando el temporizador expira, Sity envía automáticamente el mensaje al usuario. "
        "Úsala para frases como 'ponme un temporizador de 10 minutos', "
        "'avísame en 30 segundos', 'recuérdame en 2 horas'. "
        "Confirma al usuario cuándo se disparará el temporizador (hora y duración). "
        "SOLO úsala cuando el usuario pide crear un temporizador de forma explícita."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "duration_seconds": {
                "type": "integer",
                "minimum": 1,
                "description": "Duración del temporizador en segundos. Ej: 600 para 10 minutos.",
            },
            "message": {
                "type": "string",
                "description": (
                    "Mensaje que Sity enviará cuando expire el temporizador. "
                    "Si no se especifica, usa un mensaje genérico."
                ),
            },
        },
        "required": ["duration_seconds"],
    },
}

SET_ALARM_TOOL = {
    "name": "set_alarm",
    "description": (
        "Crea una alarma que se disparará a una hora absoluta concreta. "
        "Úsala para frases como 'avísame a las 15:00', 'recuérdame el viernes a las 9'. "
        "El parámetro fires_at debe estar en formato ISO 8601 con zona horaria. "
        "Confirma al usuario la hora exacta a la que sonará la alarma. "
        "SOLO úsala cuando el usuario pide crear una alarma de forma explícita."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fires_at": {
                "type": "string",
                "description": (
                    "Hora de disparo en ISO 8601 con zona horaria. "
                    "Ej: '2026-08-05T15:00:00+02:00'. "
                    "Si el usuario da hora local, usa su zona horaria."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "Mensaje que Sity enviará cuando suene la alarma. "
                    "Si no se especifica, usa un mensaje genérico."
                ),
            },
        },
        "required": ["fires_at"],
    },
}

LIST_TIMERS_TOOL = {
    "name": "list_timers",
    "description": (
        "Lista los temporizadores y alarmas pendientes de la sesión actual. "
        "Muestra el ID, la hora de disparo y el mensaje de cada uno. "
        "SOLO úsala cuando el usuario pregunte explícitamente por sus temporizadores "
        "o alarmas activos. No la uses para responder preguntas genéricas o ambiguas "
        "(ej. '¿cómo estamos?', '¿qué hay?') aunque el historial reciente incluya "
        "conversaciones sobre timers — en ese caso responde conversacionalmente."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    },
}

CANCEL_TIMER_TOOL = {
    "name": "cancel_timer",
    "description": (
        "Cancela un temporizador o alarma pendiente identificado por su ID. "
        "El ID tiene el formato tmr_XXXXXXXX. "
        "Usa list_timers primero si el usuario no ha dado el ID explícitamente. "
        "SOLO úsala cuando el usuario pide cancelar un temporizador o alarma de forma explícita."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timer_id": {
                "type": "string",
                "description": "ID del temporizador a cancelar, ej: tmr_a1b2c3d4.",
            },
        },
        "required": ["timer_id"],
    },
}

TIMERS_TOOLSET = [
    SET_TIMER_TOOL,
    SET_ALARM_TOOL,
    LIST_TIMERS_TOOL,
    CANCEL_TIMER_TOOL,
]

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


PENDING_ACTION_TOOLSET: list[dict] = [
    CANCEL_PENDING_ACTION_TOOL,
]

SOCIAL_RECALL_IMPRESSION_TOOL = {
    "name": "social_recall_impression",
    "description": (
        "Recupera la impresión cualitativa que Sity tiene sobre un tercero (otro usuario conocido). "
        "Úsala SOLO cuando el usuario pregunta explícitamente sobre la relación, opinión o historial "
        "con una persona concreta ('¿qué piensas de X?', '¿cómo es X?', '¿qué tal te cae X?'). "
        "NO la uses solo porque un nombre aparezca de pasada en una conversación sobre otro tema "
        "(ej: 'mi amigo Pablo me recomendó esta serie' → el tema es la serie, no Pablo). "
        "El resultado es una impresión cualitativa filtrada; nunca incluye contenido literal "
        "de conversaciones ni datos concretos sobre la persona consultada."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "username": {
                "type": "string",
                "description": "Nombre (display_name) de la persona sobre la que se consulta.",
            },
        },
        "required": ["username"],
    },
}

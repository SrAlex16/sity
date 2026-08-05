SOCIAL_RECALL_IMPRESSION_TOOL = {
    "name": "social_recall_impression",
    "description": (
        "Recupera la impresión cualitativa que Sity tiene sobre un tercero (otro usuario conocido) "
        "cuando el interlocutor actual lo menciona por nombre. "
        "Úsala SOLO cuando el interlocutor mencione a alguien y necesites contexto sobre esa persona "
        "para responder con naturalidad — nunca de forma proactiva ni para todos los nombres posibles. "
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

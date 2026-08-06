WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Busca información actualizada en internet. Úsala cuando el usuario "
        "pregunte por algo que puede haber cambiado recientemente (noticias, "
        "precios, eventos, tiempo, personas públicas, software), cuando necesites "
        "datos actuales que no están en tu historial de conversación, o cuando "
        "el usuario lo pida explícitamente. También úsala para atribuciones "
        "específicas que vinculan una cosa con otra — a qué obra, categoría o "
        "serie pertenece algo; quién hizo qué cosa concreta; qué versión o "
        "edición es cuál — si esa información no aparece ya confirmada en el "
        "resultado de otra tool o en la conversación. Creer saberlo no basta: "
        "las atribuciones específicas no son conocimiento estable. "
        "NO la uses para conversación general ni para hechos generales ampliamente "
        "conocidos (definiciones, historia asentada, conceptos). "
        "Al mencionar o citar un enlace de los resultados, indica que proviene de "
        "una búsqueda automática sin verificación de seguridad propia. Si el usuario "
        "pregunta explícitamente si un enlace es seguro, responde con honestidad: "
        "no tienes forma de verificarlo con certeza."
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


READ_WEBPAGE_TOOL = {
    "name": "read_webpage",
    "description": (
        "Lee el contenido de texto de una URL específica que el usuario ha compartido "
        "o que necesitas consultar directamente. Solo extrae texto — nunca ejecuta "
        "JavaScript ni realiza acciones interactivas (clics, formularios). "
        "Úsala cuando el usuario te pase un enlace concreto y quiera que lo leas, "
        "o cuando necesites el contenido completo de una página específica que "
        "web_search no devuelve en sus snippets. "
        "NO la uses para navegar por internet de forma exploratoria — para eso usa web_search. "
        "El contenido se trunca a 5000 caracteres si la página es más larga."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "url": {
                "type": "string",
                "description": "La URL completa de la página a leer (debe empezar por http:// o https://)."
            }
        },
        "required": ["url"]
    }
}


SEARCH_CONVERSATION_HISTORY_TOOL = {
    "name": "search_conversation_history",
    "description": (
        "Busca en el historial completo de conversación almacenado en la base de datos. "
        "Úsala cuando responder dependa de conversación anterior que no aparece en el historial visible. "
        "Devuelve ventanas cronológicas alrededor de las coincidencias encontradas, no solo el mensaje adyacente. "
        "No inventes ni pidas al usuario que repita algo antes de consultar esta herramienta. "
        "La búsqueda usa palabras clave; términos simples tienen mayor cobertura que frases largas. "
        "NO usar como paso previo a una acción cuando el mensaje del usuario ya contiene todos los datos necesarios para ejecutarla."
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

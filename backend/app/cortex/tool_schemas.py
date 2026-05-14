PERSONALITY_PARAMETERS = [
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "tsundere_level",
    "contrarian_level",
    "patience_level",
    "refusal_chance",
    "helpfulness_level",
    "verbosity_level",
]


UPDATE_PERSONALITY_SETTINGS_TOOL = {
    "name": "update_personality_settings",
    "description": (
        "Actualiza uno o varios parámetros de personalidad de Sity cuando el usuario "
        "pide cambiar su carácter, tono, estilo, nivel de ayuda, verbosidad, sarcasmo, "
        "calidez, paciencia, contradicción, tendencia a negarse o rasgos similares. "
        "Usa esta herramienta cuando el usuario pida explícitamente cambiar la personalidad "
        "o cuando use lenguaje natural como 'hazte más amable', 'ponte más insoportable', "
        "'déjalo todo al 50%', 'baja el sarcasmo', 'sé menos borde', etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "updates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "parameter": {
                            "type": "string",
                            "enum": PERSONALITY_PARAMETERS,
                            "description": "Parámetro de personalidad a modificar.",
                        },
                        "operation": {
                            "type": "string",
                            "enum": [
                                "set_absolute",
                                "increase_absolute",
                                "decrease_absolute",
                            ],
                            "description": (
                                "set_absolute fija el valor exacto. "
                                "increase_absolute suma value. "
                                "decrease_absolute resta value."
                            ),
                        },
                        "value": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": (
                                "Valor entre 0 y 1. Para porcentajes, 70% = 0.7. "
                                "Para cambios relativos como 'baja un poco', usa 0.1 o 0.2."
                            ),
                        },
                    },
                    "required": ["parameter", "operation", "value"],
                },
            },
            "reason": {
                "type": "string",
                "description": "Breve explicación de por qué se aplican estos cambios.",
            },
        },
        "required": ["updates", "reason"],
    },
}


TOOLS = [
    UPDATE_PERSONALITY_SETTINGS_TOOL,
]

from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL

# Remake Fase 1 — 13 orthogonal personality traits (replaces the old 14-parameter system).
PERSONALITY_PARAMETERS = [
    "warmth",
    "empathy",
    "directness",
    "assertiveness",
    "independence",
    "skepticism",
    "patience",
    "curiosity",
    "proactivity",
    "helpfulness",
    "honesty",
    "playfulness",
    "emotional_stability",
]

_ALL_PERSONALITY_PARAMETERS_TEXT = ", ".join(PERSONALITY_PARAMETERS)


UPDATE_PERSONALITY_SETTINGS_TOOL = {
    "name": "update_personality_settings",
    "description": (
        "Actualiza uno o varios rasgos de personalidad de Sity. "
        f"Rasgos permitidos: {_ALL_PERSONALITY_PARAMETERS_TEXT}. "
        "DEBES incluir siempre el campo 'updates' con al menos un elemento. "
        "Cada item de 'updates' debe tener parameter, operation y value. "
        "Never call this tool with an empty updates array. "
        "Never call this tool with only reason and no updates. "
        "When updating all personality parameters, include one update for every allowed parameter. "
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "updates": {
                "type": "array",
                "description": (
                    "Lista OBLIGATORIA de cambios. Nunca la omitas. "
                    f"Para 'todo al 50%' incluye los {len(PERSONALITY_PARAMETERS)} rasgos permitidos."
                ),
                "minItems": 1,
                "maxItems": len(PERSONALITY_PARAMETERS),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "parameter": {
                            "type": "string",
                            "enum": PERSONALITY_PARAMETERS,
                            "description": "Rasgo exacto a modificar.",
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
                            "description": "Valor entre 0 y 1. 50% = 0.5, 70% = 0.7.",
                        },
                    },
                    "required": ["parameter", "operation", "value"],
                },
            },
            "reason": {
                "type": "string",
                "description": "Breve razón del cambio.",
            },
        },
        "required": ["updates", "reason"],
    },
}


PERSONALITY_TOOLSET = [
    UPDATE_PERSONALITY_SETTINGS_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

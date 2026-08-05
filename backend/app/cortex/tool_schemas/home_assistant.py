HA_LIST_ENTITIES_TOOL = {
    "name": "ha_list_entities",
    "description": (
        "Lista los dispositivos y entidades disponibles en Home Assistant. "
        "Úsala para saber qué dispositivos hay antes de controlarlos, "
        "o cuando el usuario pregunte qué tiene en casa. "
        "Puedes filtrar por dominio (switch, light, climate, fan…), "
        "área (dormitorio, salón…) o palabra clave."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "domain":  {"type": "string", "description": "Dominio a filtrar: switch, light, climate, fan, etc."},
            "area":    {"type": "string", "description": "Área o habitación a filtrar."},
            "keyword": {"type": "string", "description": "Palabra clave para buscar en nombre o entity_id."},
        },
    },
}

HA_GET_STATE_TOOL = {
    "name": "ha_get_state",
    "description": (
        "Obtiene el estado actual de un dispositivo específico de Home Assistant "
        "(encendido/apagado, temperatura, brillo, etc.)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "ID de la entidad, ej: switch.tapo_p100"},
        },
        "required": ["entity_id"],
    },
}

HA_CALL_SERVICE_TOOL = {
    "name": "ha_call_service",
    "description": (
        "Controla un dispositivo de Home Assistant llamando a un servicio. "
        "Para encender: service='turn_on'. Para apagar: service='turn_off'. "
        "Para alternar: service='toggle'. "
        "Para luces con brillo: service='turn_on' + service_data={'brightness': 128}. "
        "Para luces con color: service='turn_on' + service_data={'rgb_color': [255, 0, 0]}. "
        "Encender/apagar/toggle son reversibles — se ejecutan directamente sin confirmación. "
        "Acciones irreversibles (cerrar cerradura) requieren confirmación previa."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id":    {"type": "string", "description": "ID de la entidad a controlar."},
            "service":      {"type": "string", "description": "Servicio a llamar: turn_on, turn_off, toggle, etc."},
            "service_data": {"type": "object", "description": "Parámetros adicionales (brightness, rgb_color, temperature, etc.)"},
        },
        "required": ["entity_id", "service"],
    },
}

HA_TOOLSET = [
    HA_LIST_ENTITIES_TOOL,
    HA_GET_STATE_TOOL,
    HA_CALL_SERVICE_TOOL,
]

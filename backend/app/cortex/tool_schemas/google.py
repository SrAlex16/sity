from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL

GMAIL_SEARCH_TOOL = {
    "name": "gmail_search",
    "description": (
        "Busca y lee correos en Gmail del usuario. "
        "SOLO LECTURA: no puede enviar, eliminar, archivar, marcar como leído/no leído, ni crear etiquetas. "
        "Por defecto busca solo en la bandeja Principal (category:primary). "
        "Para buscar en otras bandejas, especifica: category:promotions, category:social, "
        "category:updates, o label:inbox. "
        "Usa sintaxis de búsqueda Gmail si es útil (from:, subject:, after:, is:unread, etc.). "
        "Devuelve remitente, asunto, fecha y extracto del cuerpo, no el correo completo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Query de búsqueda Gmail."},
            "max_results": {"type": "integer", "description": "Máximo de resultados (máx 10). Por defecto 5."},
        },
        "required": ["query"],
    },
}

CALENDAR_LIST_EVENTS_TOOL = {
    "name": "calendar_list_events",
    "description": (
        "Lista los próximos eventos del calendario del usuario. Solo lectura."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days_ahead": {"type": "integer", "description": "Días hacia adelante a consultar. Por defecto 7."},
        },
    },
}

CALENDAR_CREATE_EVENT_TOOL = {
    "name": "calendar_create_event",
    "description": (
        "Crea un evento en el calendario del usuario. SIEMPRE requiere confirmación explícita "
        "del usuario antes de ejecutarse — nunca se crea directamente. "
        "Usa fechas en formato ISO 8601 con zona horaria (ej: 2026-07-01T18:00:00+02:00)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Título del evento."},
            "start_iso": {"type": "string", "description": "Fecha/hora de inicio en ISO 8601."},
            "end_iso": {"type": "string", "description": "Fecha/hora de fin en ISO 8601."},
            "description": {"type": "string", "description": "Descripción opcional del evento."},
        },
        "required": ["title", "start_iso", "end_iso"],
    },
}

CALENDAR_EDIT_EVENT_TOOL = {
    "name": "calendar_edit_event",
    "description": (
        "Modifica un evento existente de Google Calendar. Úsala cuando el usuario quiera cambiar, "
        "actualizar o añadir cualquier dato a un evento: nombre, hora, ubicación, descripción, etc. "
        "Puedes identificar el evento por event_id O por event_title (nombre del evento) — si "
        "pasas event_title, lo busco automáticamente sin necesitar llamar antes a "
        "calendar_list_events. Requiere confirmación antes de ejecutarse."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "event_id":    {"type": "string", "description": "ID del evento. Opcional si tienes event_title."},
            "event_title": {"type": "string", "description": "Nombre o parte del nombre del evento. Úsalo cuando no tengas el event_id."},
            "title":       {"type": "string", "description": "Nuevo nombre del evento."},
            "start_iso":   {"type": "string", "description": "Nueva fecha/hora inicio ISO 8601."},
            "end_iso":     {"type": "string", "description": "Nueva fecha/hora fin ISO 8601."},
            "description": {"type": "string", "description": "Nueva descripción del evento."},
            "location":    {"type": "string", "description": "Ubicación o lugar del evento."},
        },
    },
}

CALENDAR_DELETE_EVENT_TOOL = {
    "name": "calendar_delete_event",
    "description": (
        "Borra un evento de Google Calendar. Requiere confirmación — es irreversible. "
        "Puedes identificar el evento por event_id O por event_title (nombre del evento) — "
        "si pasas event_title, lo busco automáticamente."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "event_id":    {"type": "string", "description": "ID del evento. Opcional si tienes event_title."},
            "event_title": {"type": "string", "description": "Nombre o parte del nombre del evento."},
        },
    },
}

DRIVE_SEARCH_TOOL = {
    "name": "drive_search",
    "description": (
        "Busca archivos en Google Drive del usuario. Solo lectura — devuelve "
        "metadatos (nombre, tipo, fecha de modificación, enlace), no el contenido del archivo. "
        "Si query está vacío, devuelve los archivos modificados más recientemente. "
        "Usa include_shared=true para incluir archivos compartidos contigo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Término a buscar en el nombre del archivo. Vacío para ver recientes."},
            "max_results": {"type": "integer", "description": "Máximo de resultados (máx 10). Por defecto 5."},
            "include_shared": {"type": "boolean", "description": "Incluir archivos compartidos contigo. Por defecto false."},
        },
    },
}

DRIVE_LIST_FOLDER_TOOL = {
    "name": "drive_list_folder",
    "description": (
        "Lista el contenido de una carpeta de Google Drive. "
        "Para ver las carpetas y archivos del Drive raíz (nivel superior), llama con "
        "folder_name vacío o sin folder_name. "
        "Para ver el contenido de una carpeta específica, pasa su nombre en folder_name. "
        "No uses 'root', 'raiz' ni similares como folder_name — deja folder_name vacío "
        "para listar el nivel raíz. "
        "Para buscar archivos por nombre en todo el Drive, usa drive_search."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "folder_name": {"type": "string", "description": "Nombre de la carpeta."},
            "folder_id":   {"type": "string", "description": "ID de la carpeta (más preciso si lo tienes)."},
            "max_results": {"type": "integer", "description": "Máximo de resultados (máx 50). Por defecto 20."},
        },
    },
}


GOOGLE_TOOLSET = [
    GMAIL_SEARCH_TOOL,
    CALENDAR_LIST_EVENTS_TOOL,
    CALENDAR_CREATE_EVENT_TOOL,
    CALENDAR_EDIT_EVENT_TOOL,
    CALENDAR_DELETE_EVENT_TOOL,
    DRIVE_SEARCH_TOOL,
    DRIVE_LIST_FOLDER_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

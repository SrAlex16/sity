from app.cortex.tool_schemas.actions import NO_ACTION_REQUIRED_TOOL

LIST_CAMERA_DEVICES_TOOL = {
    "name": "list_camera_devices",
    "description": "Lista cámaras disponibles. No activa la cámara ni captura imágenes.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


LIST_AUDIO_DEVICES_TOOL = {
    "name": "list_audio_devices",
    "description": "Lista dispositivos de audio. Debe distinguir dispositivos virtuales como Loopback del micrófono real.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


CAPTURE_CAMERA_SNAPSHOT_TOOL = {
    "name": "capture_camera_snapshot",
    "description": (
        "Captura una única imagen con la cámara conectada. "
        "Úsala cuando el usuario pida explícitamente hacer/sacar/tomar/probar una foto o imagen. "
        "No la uses para captura continua ni vigilancia."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "Dispositivo de cámara. Por defecto /dev/video0.",
            },
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "skip_frames": {
                "type": "integer",
                "description": "Frames a saltar para autoexposición. Por defecto 20.",
            },
        },
        "additionalProperties": False,
    },
}


RECORD_AUDIO_SAMPLE_TOOL = {
    "name": "record_audio_sample",
    "description": (
        "Graba una muestra corta de audio desde el micrófono real de la webcam. "
        "Úsala cuando el usuario pida explícitamente grabar una muestra o prueba de audio. "
        "No uses Loopback como micrófono. No la uses para grabación continua."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "duration_seconds": {
                "type": "integer",
                "description": "Duración entre 1 y 10 segundos. Por defecto 3.",
            },
            "device": {
                "type": "string",
                "description": "Dispositivo ALSA. Por defecto plughw:CARD=webcam,DEV=0.",
            },
        },
        "additionalProperties": False,
    },
}


GET_CAPTURE_STORAGE_SUMMARY_TOOL = {
    "name": "get_capture_storage_summary",
    "description": (
        "Consulta cuántas capturas de cámara/audio hay guardadas y cuánto ocupan. "
        "No borra nada."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


CLEAN_OLD_CAPTURES_TOOL = {
    "name": "clean_old_captures",
    "description": (
        "Limpia capturas antiguas de cámara/audio dentro del directorio captures. "
        "Úsala cuando el usuario pida limpiar, borrar capturas antiguas o evitar acumulación. "
        "Solo borra archivos permitidos dentro de captures/camera y captures/audio."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "older_than_days": {
                "type": "integer",
                "description": "Borra archivos con más de estos días. Por defecto 7.",
            },
            "max_files_per_type": {
                "type": "integer",
                "description": "Mantiene como mínimo este máximo de archivos recientes por tipo. Por defecto 100.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Si true, solo simula la limpieza sin borrar archivos.",
            },
        },
        "additionalProperties": False,
    },
}


SENSES_TOOLSET = [
    LIST_CAMERA_DEVICES_TOOL,
    LIST_AUDIO_DEVICES_TOOL,
    CAPTURE_CAMERA_SNAPSHOT_TOOL,
    RECORD_AUDIO_SAMPLE_TOOL,
    GET_CAPTURE_STORAGE_SUMMARY_TOOL,
    CLEAN_OLD_CAPTURES_TOOL,
    NO_ACTION_REQUIRED_TOOL,
]

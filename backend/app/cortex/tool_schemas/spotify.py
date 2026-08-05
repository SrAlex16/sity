SPOTIFY_NOW_PLAYING_TOOL = {
    "name": "spotify_now_playing",
    "description": (
        "Qué está sonando ahora mismo en Spotify del usuario: canción, artista, álbum, "
        "progreso y si está en pausa. Útil para 'qué está sonando', '¿qué canción es esta?', etc. "
        "El resultado contiene datos de reproducción (título, artista, álbum) — no indica "
        "a qué obra pertenece la canción (anime, serie, película, videojuego) salvo que esa "
        "información aparezca literalmente en el texto devuelto. Si el usuario pregunta por "
        "el origen de la canción y no está en el resultado, usa web_search para verificarlo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

SPOTIFY_RECENTLY_PLAYED_TOOL = {
    "name": "spotify_recently_played",
    "description": "Historial de canciones reproducidas recientemente en Spotify.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Número de canciones a devolver (máx 50). Por defecto 10."},
        },
    },
}

SPOTIFY_LIST_DEVICES_TOOL = {
    "name": "spotify_list_devices",
    "description": (
        "Lista los dispositivos Spotify disponibles del usuario (nombre, tipo, si está activo, "
        "device_id). Úsala para resolver 'el altavoz del salón' a un device_id antes de "
        "controlar la reproducción en un dispositivo concreto."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

SPOTIFY_PLAY_TOOL = {
    "name": "spotify_play",
    "description": (
        "Reproduce música en Spotify. Sin 'query': reanuda la reproducción pausada. "
        "Con 'query': busca por texto libre (canción, artista, álbum) y reproduce el primer "
        "resultado; o pasa directamente una URI o ID de playlist/álbum/canción ya conocido "
        "(ej. 'spotify:playlist:37i9dQZF1DX...' o solo el ID). "
        "Acepta 'device_id' opcional; sin él actúa sobre el dispositivo activo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query":     {"type": "string", "description": "Texto libre a buscar, o URI/ID de Spotify ya conocido. Omitir para reanudar."},
            "device_id": {"type": "string", "description": "ID del dispositivo destino (de spotify_list_devices). Opcional."},
        },
    },
}

SPOTIFY_PAUSE_TOOL = {
    "name": "spotify_pause",
    "description": "Pausa la reproducción de Spotify. Acepta 'device_id' opcional.",
    "input_schema": {
        "type": "object",
        "properties": {
            "device_id": {"type": "string", "description": "ID del dispositivo. Opcional."},
        },
    },
}

SPOTIFY_SKIP_TOOL = {
    "name": "spotify_skip",
    "description": (
        "Salta a la siguiente o anterior canción en Spotify. "
        "'direction': 'next' (por defecto) o 'previous'. Acepta 'device_id' opcional."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "direction":  {"type": "string", "enum": ["next", "previous"], "description": "Dirección del salto. Por defecto 'next'."},
            "device_id":  {"type": "string", "description": "ID del dispositivo. Opcional."},
        },
    },
}

SPOTIFY_SET_VOLUME_TOOL = {
    "name": "spotify_set_volume",
    "description": "Cambia el volumen de Spotify (0-100). Acepta 'device_id' opcional.",
    "input_schema": {
        "type": "object",
        "properties": {
            "volume_percent": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Volumen deseado (0-100)."},
            "device_id":      {"type": "string", "description": "ID del dispositivo. Opcional."},
        },
        "required": ["volume_percent"],
    },
}

SPOTIFY_LIST_PLAYLISTS_TOOL = {
    "name": "spotify_list_playlists",
    "description": (
        "Devuelve las playlists de la biblioteca del usuario: nombre, ID, URI, "
        "número de canciones y descripción (si la tiene). "
        "Acepta 'limit' opcional (máx. 50, por defecto 50)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Número máximo de playlists a devolver. Por defecto 50."},
        },
    },
}

SPOTIFY_PLAYLIST_TRACKS_TOOL = {
    "name": "spotify_playlist_tracks",
    "description": (
        "Devuelve las canciones de una playlist dado su ID. "
        "Incluye título y artista de cada canción. "
        "Acepta 'limit' opcional (máx. 50, por defecto 25)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "playlist_id": {"type": "string", "description": "ID de la playlist (de spotify_list_playlists)."},
            "limit":       {"type": "integer", "minimum": 1, "maximum": 50, "description": "Número máximo de canciones a devolver. Por defecto 25."},
        },
        "required": ["playlist_id"],
    },
}

SPOTIFY_RESUME_PREVIOUS_TOOL = {
    "name": "spotify_resume_previous",
    "description": (
        "Reanuda en Spotify lo que sonaba justo antes del último cambio (canción suelta, "
        "álbum o playlist). Úsala ante frases como 'pon lo que sonaba antes', "
        "'vuelve a la playlist anterior', 'lo que tenía puesto antes de esto'. "
        "No acepta parámetros. Si no hay contexto guardado, responde que no tiene registro."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

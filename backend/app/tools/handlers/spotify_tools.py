from __future__ import annotations

import json
import time
from typing import Any

import requests
from sqlmodel import Session, select

from app.integrations.spotify_auth import is_spotify_connected, load_credentials
from app.memory.db import engine
from app.memory.models import Setting, utc_now
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult
from app.trace.logger import write_log

_BASE = "https://api.spotify.com/v1"


def _not_connected(tool_name: str) -> ToolExecutionResult:
    msg = (
        "Spotify no está conectado. Necesitas ejecutar "
        "scripts/spotify_auth_setup.py una vez para autorizar el acceso."
    )
    return ToolExecutionResult(
        tool_name=tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={
            "success": False, "message": msg,
            "local_final": True, "text": msg, "local_model": "spotify-auth-guard",
        },
    )


def _headers() -> dict[str, str]:
    token = load_credentials()
    return {"Authorization": f"Bearer {token['access_token']}"}


def _get(path: str, *, params: dict | None = None) -> requests.Response:
    resp = requests.get(f"{_BASE}{path}", headers=_headers(), params=params, timeout=10)
    write_log(level="INFO" if resp.ok else "WARN", module="spotify", event="spotify_api_call",
              payload={"method": "GET", "path": path, "status_code": resp.status_code, "ok": resp.ok})
    return resp


def _put(path: str, *, params: dict | None = None, body: dict | None = None) -> requests.Response:
    resp = requests.put(
        f"{_BASE}{path}", headers={**_headers(), "Content-Type": "application/json"},
        params=params, json=body or {}, timeout=10,
    )
    write_log(level="INFO" if resp.ok else "WARN", module="spotify", event="spotify_api_call",
              payload={"method": "PUT", "path": path, "status_code": resp.status_code, "ok": resp.ok})
    return resp


def _post(path: str, *, params: dict | None = None) -> requests.Response:
    resp = requests.post(f"{_BASE}{path}", headers=_headers(), params=params, timeout=10)
    write_log(level="INFO" if resp.ok else "WARN", module="spotify", event="spotify_api_call",
              payload={"method": "POST", "path": path, "status_code": resp.status_code, "ok": resp.ok})
    return resp


def _device_params(device_id: str | None) -> dict[str, Any]:
    return {"device_id": device_id} if device_id else {}


_PREVIOUS_CONTEXT_KEY = "spotify:previous_context"


def _capture_current_context() -> dict | None:
    """Return a snapshot of what's currently playing, or None if nothing is.

    Tries to capture context_uri first (playlist/album), falls back to track uri.
    """
    resp = _get("/me/player/currently-playing", params={"market": "ES"})
    if resp.status_code == 204 or not resp.content:
        return None

    data = resp.json()
    item = data.get("item") or {}
    if not item:
        return None

    context = data.get("context") or {}
    context_uri: str | None = context.get("uri")

    track_uri: str = item.get("uri", "")
    name = item.get("name", "?")
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    description = f"{name} — {artists}"

    if context_uri and not context_uri.startswith("spotify:track:"):
        return {"uri": context_uri, "description": description, "saved_at": time.time()}
    return {"uri": track_uri, "description": description, "saved_at": time.time()}


def _save_previous_context() -> None:
    snapshot = _capture_current_context()
    if snapshot is None:
        return
    with Session(engine) as db:
        existing = db.exec(select(Setting).where(Setting.key == _PREVIOUS_CONTEXT_KEY)).first()
        now = utc_now()
        if existing:
            existing.value_json = json.dumps(snapshot)
            existing.updated_at = now
            db.add(existing)
        else:
            db.add(Setting(key=_PREVIOUS_CONTEXT_KEY, value_json=json.dumps(snapshot), source="spotify", created_at=now, updated_at=now))
        db.commit()


def _load_previous_context() -> dict | None:
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == _PREVIOUS_CONTEXT_KEY)).first()
        return json.loads(row.value_json) if row else None


# ── Read tools ────────────────────────────────────────────────────────────────

@tool_handler("spotify_now_playing")
def handle_spotify_now_playing(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    resp = _get("/me/player/currently-playing", params={"market": "ES"})

    if resp.status_code == 204 or not resp.content:
        output = "En este momento no hay ninguna canción en reproducción."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    data = resp.json()
    item = data.get("item") or {}
    if not item:
        output = "En este momento no hay ninguna canción en reproducción."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    name = item.get("name", "?")
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    album = item.get("album", {}).get("name", "?")
    duration_ms = item.get("duration_ms", 0)
    progress_ms = data.get("progress_ms", 0)
    is_playing = data.get("is_playing", False)

    def _fmt(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"

    state = "reproduciendo" if is_playing else "en pausa"
    output = (
        f"{name} — {artists}\n"
        f"Álbum: {album}\n"
        f"Estado: {state} ({_fmt(progress_ms)} / {_fmt(duration_ms)})"
    )
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("spotify_recently_played")
def handle_spotify_recently_played(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    limit = min(int(ctx.tool_input.get("limit", 10)), 50)
    resp = _get("/me/player/recently-played", params={"limit": limit})

    if not resp.ok:
        msg = f"Error al obtener el historial de Spotify ({resp.status_code})."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    items = resp.json().get("items", [])
    if not items:
        output = "No hay historial de reproducción reciente."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    lines = []
    for entry in items:
        track = entry.get("track", {})
        name = track.get("name", "?")
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        played_at = entry.get("played_at", "")[:16].replace("T", " ")
        lines.append(f"{played_at} — {name} ({artists})")

    output = "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("spotify_list_devices")
def handle_spotify_list_devices(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    resp = _get("/me/player/devices")

    if not resp.ok:
        msg = f"Error al obtener dispositivos de Spotify ({resp.status_code})."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    devices = resp.json().get("devices", [])
    if not devices:
        output = "No hay dispositivos Spotify disponibles. Abre Spotify en algún dispositivo."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    lines = []
    for d in devices:
        active = " [ACTIVO]" if d.get("is_active") else ""
        vol = d.get("volume_percent")
        vol_str = f", volumen {vol}%" if vol is not None else ""
        lines.append(
            f"ID: {d['id']}\n"
            f"  {d.get('name', '?')} ({d.get('type', '?')}){active}{vol_str}"
        )

    output = "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("spotify_list_playlists")
def handle_spotify_list_playlists(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    limit = min(int(ctx.tool_input.get("limit", 50)), 50)
    resp = _get("/me/playlists", params={"limit": limit})

    if not resp.ok:
        msg = f"Error al obtener playlists de Spotify ({resp.status_code})."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    items = resp.json().get("items", [])
    if not items:
        output = "No hay playlists en la biblioteca."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    lines = []
    for pl in items:
        name = pl.get("name", "?")
        pl_id = pl.get("id", "")
        uri = pl.get("uri", "")
        tracks_total = pl.get("tracks", {}).get("total", "?")
        desc = pl.get("description", "") or ""
        desc_str = f"\n    Descripción: {desc}" if desc else ""
        lines.append(
            f"{name}\n"
            f"    ID: {pl_id} | URI: {uri} | Canciones: {tracks_total}{desc_str}"
        )

    output = "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("spotify_playlist_tracks")
def handle_spotify_playlist_tracks(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    playlist_id: str = str(ctx.tool_input.get("playlist_id", "")).strip()
    if not playlist_id:
        msg = "Falta el parámetro 'playlist_id'."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    limit = min(int(ctx.tool_input.get("limit", 25)), 50)
    resp = _get(f"/playlists/{playlist_id}/tracks", params={"limit": limit, "fields": "items(track(name,artists,uri)),total", "market": "ES"})

    if not resp.ok:
        msg = f"Error al obtener canciones de la playlist ({resp.status_code})."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    data = resp.json()
    total = data.get("total", "?")
    items = data.get("items", [])

    if not items:
        output = "La playlist está vacía."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    lines = [f"Mostrando {len(items)} de {total} canciones:"]
    for entry in items:
        track = (entry.get("track") or {})
        name = track.get("name", "?")
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        lines.append(f"  {name} — {artists}")

    output = "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


# ── Control tools ─────────────────────────────────────────────────────────────

def _search_uri(query: str) -> tuple[str, str] | None:
    """Resolve a text query to (spotify_uri, description).

    Searches tracks first; falls back to albums if no track is found.
    Returns None if nothing is found.
    """
    resp = _get("/search", params={"q": query, "type": "track,album", "limit": 1, "market": "ES"})
    if not resp.ok:
        return None
    data = resp.json()

    tracks = data.get("tracks", {}).get("items", [])
    if tracks:
        t = tracks[0]
        artists = ", ".join(a["name"] for a in t.get("artists", []))
        desc = f"{t['name']} — {artists}"
        return t["uri"], desc

    albums = data.get("albums", {}).get("items", [])
    if albums:
        a = albums[0]
        artists = ", ".join(ar["name"] for ar in a.get("artists", []))
        desc = f"álbum {a['name']} — {artists}"
        return a["uri"], desc

    return None


@tool_handler("spotify_play")
def handle_spotify_play(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    query: str = str(ctx.tool_input.get("query", "")).strip()
    device_id: str | None = ctx.tool_input.get("device_id") or None
    params = _device_params(device_id)

    _play_uri: str | None = None

    if query:
        # Short-circuit: if caller already has a Spotify URI, skip the search API.
        if query.startswith("spotify:"):
            uri, desc = query, query
        else:
            resolved = _search_uri(query)
            if resolved is None:
                msg = f"No encontré nada en Spotify para '{query}'."
                return ToolExecutionResult(
                    tool_name=ctx.tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={"output": msg},
                )
            uri, desc = resolved
        _play_uri = uri
        _save_previous_context()
        # Track URI → uris list; album/playlist URI → context_uri
        if ":track:" in uri:
            body: dict[str, Any] = {"uris": [uri]}
        else:
            body = {"context_uri": uri}
        resp = _put("/me/player/play", params=params, body=body)
        output = f"Reproduciendo: {desc}."
    else:
        resp = _put("/me/player/play", params=params)
        output = "Reproducción reanudada."

    if resp.status_code in (200, 204):
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    if resp.status_code == 404:
        if _play_uri:
            msg = (
                f"No hay ningún dispositivo Spotify activo. "
                f"Abre Spotify en algún dispositivo y vuelve a intentarlo con este URI: {_play_uri}"
            )
        else:
            msg = "No hay ningún dispositivo Spotify activo. Abre Spotify en algún dispositivo primero."
    elif resp.status_code == 403:
        msg = "Operación no permitida. ¿Spotify Premium activo?"
    else:
        if _play_uri:
            msg = f"Error al reproducir en Spotify ({resp.status_code}). URI intentado: {_play_uri}"
        else:
            msg = f"Error al reproducir en Spotify ({resp.status_code})."
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={"output": msg},
    )


@tool_handler("spotify_pause")
def handle_spotify_pause(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    device_id: str | None = ctx.tool_input.get("device_id") or None
    resp = _put("/me/player/pause", params=_device_params(device_id))

    if resp.status_code in (200, 204):
        output = "Reproducción pausada."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    if resp.status_code == 403:
        msg = "No se puede pausar (¿Spotify Premium activo?)."
    elif resp.status_code == 404:
        msg = "No hay ningún dispositivo Spotify activo."
    else:
        msg = f"Error al pausar en Spotify ({resp.status_code})."
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={"output": msg},
    )


@tool_handler("spotify_skip")
def handle_spotify_skip(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    direction = str(ctx.tool_input.get("direction", "next")).lower()
    if direction not in ("next", "previous"):
        direction = "next"
    device_id: str | None = ctx.tool_input.get("device_id") or None
    params = _device_params(device_id)

    path = "/me/player/next" if direction == "next" else "/me/player/previous"
    _save_previous_context()
    resp = _post(path, params=params)

    if resp.status_code in (200, 204):
        output = "Canción anterior." if direction == "previous" else "Canción siguiente."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    if resp.status_code == 403:
        msg = "No se puede saltar de canción (¿Spotify Premium activo?)."
    elif resp.status_code == 404:
        msg = "No hay ningún dispositivo Spotify activo."
    else:
        msg = f"Error al saltar de canción ({resp.status_code})."
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={"output": msg},
    )


@tool_handler("spotify_resume_previous")
def handle_spotify_resume_previous(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    snapshot = _load_previous_context()
    if snapshot is None:
        msg = "No tengo registro de qué sonaba antes."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    uri: str = snapshot.get("uri", "")
    desc: str = snapshot.get("description", uri)

    if ":track:" in uri:
        body: dict[str, Any] = {"uris": [uri]}
    else:
        body = {"context_uri": uri}

    resp = _put("/me/player/play", body=body)

    if resp.status_code in (200, 204):
        output = f"Reanudando: {desc}."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    if resp.status_code == 404:
        msg = "No hay ningún dispositivo Spotify activo. Abre Spotify en algún dispositivo primero."
    elif resp.status_code == 403:
        msg = "Operación no permitida. ¿Spotify Premium activo?"
    else:
        msg = f"Error al reanudar en Spotify ({resp.status_code})."
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={"output": msg},
    )


@tool_handler("spotify_set_volume")
def handle_spotify_set_volume(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    volume = int(ctx.tool_input.get("volume_percent", 50))
    volume = max(0, min(100, volume))
    device_id: str | None = ctx.tool_input.get("device_id") or None
    params = {"volume_percent": volume, **_device_params(device_id)}

    resp = _put("/me/player/volume", params=params)

    if resp.status_code in (200, 204):
        output = f"Volumen ajustado a {volume}%."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    if resp.status_code == 403:
        msg = "No se puede cambiar el volumen (¿Spotify Premium activo?)."
    elif resp.status_code == 404:
        msg = "No hay ningún dispositivo Spotify activo."
    else:
        msg = f"Error al ajustar el volumen ({resp.status_code})."
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={"output": msg},
    )

from __future__ import annotations

from app.integrations.spotify_auth import is_spotify_connected, load_credentials
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

import requests


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


def _api(path: str, *, params: dict | None = None) -> requests.Response:
    token = load_credentials()
    return requests.get(
        f"https://api.spotify.com/v1{path}",
        headers={"Authorization": f"Bearer {token['access_token']}"},
        params=params,
        timeout=10,
    )


@tool_handler("spotify_now_playing")
def handle_spotify_now_playing(ctx: ToolContext) -> ToolExecutionResult:
    if not is_spotify_connected():
        return _not_connected(ctx.tool_name)

    resp = _api("/me/player/currently-playing", params={"market": "ES"})

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
    resp = _api("/me/player/recently-played", params={"limit": limit})

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

    resp = _api("/me/player/devices")

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

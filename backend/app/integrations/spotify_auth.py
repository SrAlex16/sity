"""Gestión de autenticación OAuth de Spotify para Sity.

El flujo de autorización inicial es manual y se ejecuta UNA SOLA VEZ
con el script scripts/spotify_auth_setup.py. A partir de ahí, el
refresh_token guardado en data/spotify_token.json permite renovar
el access_token automáticamente sin intervención del usuario.

El token JSON guarda client_id y client_secret junto al token (igual que
google_token.json), para que load_credentials() sea autocontenido — solo
se leen de .env durante el setup inicial.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

SCOPES = " ".join([
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-read-recently-played",
    "user-modify-playback-state",
    "playlist-read-private",
])

_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Must be registered in Spotify Developer Dashboard.
# http://127.0.0.1:8888/callback is the simplest option for a CLI setup
# (browser shows "connection refused" but the code is visible in the URL).
REDIRECT_URI = "http://127.0.0.1:8888/callback"

TOKEN_PATH = Path(__file__).parent.parent.parent.parent / "data" / "spotify_token.json"


def _load_token_file() -> dict[str, Any] | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_token_file(data: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _auth_header(client_id: str, client_secret: str) -> str:
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {encoded}"


def _do_refresh(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any] | None:
    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization": _auth_header(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=10,
    )
    if not resp.ok:
        return None
    return resp.json()


def load_credentials() -> dict[str, Any] | None:
    """Carga token guardado, renovando el access_token si ha expirado.

    Devuelve el dict del token (con acceso a 'access_token'), o None si
    no hay token válido o la renovación falla.
    """
    data = _load_token_file()
    if not data or not data.get("access_token"):
        return None

    expires_at = data.get("expires_at", 0)
    if time.time() >= expires_at - 60:  # renovar 60 s antes de expirar
        new = _do_refresh(
            data.get("client_id", ""),
            data.get("client_secret", ""),
            data.get("refresh_token", ""),
        )
        if not new:
            return None
        data["access_token"] = new["access_token"]
        data["expires_at"] = time.time() + new.get("expires_in", 3600)
        # Spotify raramente rota el refresh_token, pero si lo hace lo guardamos
        if "refresh_token" in new:
            data["refresh_token"] = new["refresh_token"]
        _save_token_file(data)

    return data


def is_spotify_connected() -> bool:
    """Comprueba si hay credenciales válidas (con refresh automático si hace falta)."""
    return load_credentials() is not None


def run_initial_auth_flow(client_id: str, client_secret: str) -> dict[str, Any]:
    """Flujo de autorización inicial (una sola vez).

    Imprime una URL para abrir en cualquier navegador. Spotify redirige a
    REDIRECT_URI con ?code=...; el usuario pega esa URL completa (o solo el
    código). El token resultante se guarda en data/spotify_token.json.
    """
    auth_url = _AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "show_dialog": "true",
    })

    print("\nAbre esta URL en cualquier navegador (puede ser el de tu PC):\n")
    print(auth_url)
    print()
    print(f"Tras autorizar, Spotify redirigirá a {REDIRECT_URI}.")
    print("El navegador mostrará 'página no disponible' — eso es normal.")
    print("Copia la URL completa de la barra del navegador y pégala aquí.")
    print()
    raw = input("Pega aquí la URL de redirección (o solo el código): ").strip()

    if raw.startswith("http"):
        params = parse_qs(urlparse(raw).query)
        code = params.get("code", [raw])[0]
        if "error" in params:
            raise RuntimeError(f"Spotify devolvió error: {params['error']}")
    else:
        code = raw

    resp = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization": _auth_header(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=10,
    )
    resp.raise_for_status()
    token_data: dict[str, Any] = resp.json()
    token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600)
    # Guardar credenciales junto al token para que load_credentials() sea autocontenido
    token_data["client_id"] = client_id
    token_data["client_secret"] = client_secret
    _save_token_file(token_data)
    return token_data

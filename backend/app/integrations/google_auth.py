"""Gestión de autenticación OAuth de Google para Sity.

El flujo de autorización inicial es manual y se ejecuta UNA SOLA VEZ
con el script scripts/google_auth_setup.py. A partir de ahí, el
refresh_token guardado en data/google_token.json permite renovar
el access_token automáticamente sin intervención del usuario.
"""
from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]

TOKEN_PATH = Path(__file__).parent.parent.parent.parent / "data" / "google_token.json"


def load_credentials() -> Credentials | None:
    """Carga credenciales guardadas, renovando el access_token si ha expirado.
    Devuelve None si no hay token o si falla la renovación."""
    if not TOKEN_PATH.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
        except Exception:
            return None

    if creds and creds.valid:
        return creds

    return None


def _save_credentials(creds: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")


def run_initial_auth_flow(client_id: str, client_secret: str) -> Credentials:
    """Ejecuta el flujo de autorización inicial. Solo se llama una vez,
    desde scripts/google_auth_setup.py."""
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def is_google_connected() -> bool:
    """Comprueba si hay credenciales válidas sin llamadas de red adicionales
    más allá del refresh automático si el token ha expirado."""
    return load_credentials() is not None

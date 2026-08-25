"""Gestión de autenticación OAuth de Google para Sity.

El flujo de autorización inicial es manual y se ejecuta UNA SOLA VEZ
con el script scripts/google_auth_setup.py. A partir de ahí, el
refresh_token guardado en data/google_token.json permite renovar
el access_token automáticamente sin intervención del usuario.

load_user_credentials(user_id, session) carga credenciales per-usuario
desde la tabla UserIntegration (Fase 6). load_credentials() (sin args)
sigue siendo el fallback global para Admin con token en disco.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from sqlmodel import Session, select

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
    """Flujo de autorización inicial sin servidor local.

    Imprime una URL para abrir en cualquier navegador (incluyendo el del PC
    cuando se accede vía SSH). El usuario pega el código de autorización de
    vuelta en la terminal. Solo se llama una vez, desde google_auth_setup.py.
    """
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # Fijar redirect_uri en el objeto — no pasarla a authorization_url()
    # para evitar el TypeError "multiple values for keyword argument 'redirect_uri'"
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

    auth_url, _ = flow.authorization_url(prompt="consent")

    print("\nAbre esta URL en cualquier navegador (puede ser el de tu PC):\n")
    print(auth_url)
    print()
    print("Tras autorizar, Google te mostrará un código.")
    print("Si en vez de un código el navegador redirige a una URL que no carga,")
    print("copia esa URL completa y pégala aquí.")
    print()
    raw = input("Pega aquí el código (o la URL completa de redirección): ").strip()

    # Si el usuario pegó una URL de redirección, extraer el código del parámetro
    if raw.startswith("http"):
        from urllib.parse import parse_qs, urlparse
        params = parse_qs(urlparse(raw).query)
        code = params.get("code", [raw])[0]
    else:
        code = raw

    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_credentials(creds)
    return creds


def load_user_credentials(user_id: int, session: Session) -> Credentials | None:
    """Load per-user Google credentials from UserIntegration, refreshing if expired.

    Persists any refreshed token back to the DB row. Returns None if the user
    has no active integration or the credentials cannot be refreshed.
    """
    from app.auth.encryption import decrypt_str, encrypt_str
    from app.memory.models import UserIntegration
    from app.trace.logger import write_log

    row = session.exec(
        select(UserIntegration)
        .where(UserIntegration.user_id == user_id)
        .where(UserIntegration.provider == "google")
        .where(UserIntegration.is_active == True)  # noqa: E712
    ).first()
    if row is None:
        return None

    try:
        creds = Credentials.from_authorized_user_info(
            json.loads(decrypt_str(row.encrypted_credentials)), SCOPES
        )
    except Exception as exc:
        write_log(level="ERROR", module="google", event="google_credentials_decrypt_failed",
                  payload={"user_id": user_id, "error": str(exc)[:300]})
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            row.encrypted_credentials = encrypt_str(creds.to_json())
            row.last_refreshed_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
        except Exception as exc:
            write_log(level="ERROR", module="google", event="google_token_refresh_failed",
                      payload={"user_id": user_id, "error": str(exc)[:300],
                               "has_refresh_token": bool(creds.refresh_token)})
            return None

    if creds and creds.valid:
        return creds

    write_log(level="WARN", module="google", event="google_credentials_invalid",
              payload={"user_id": user_id, "expired": creds.expired if creds else None,
                       "has_refresh_token": bool(creds.refresh_token) if creds else None})
    return None


def is_google_connected() -> bool:
    """Comprueba si hay credenciales válidas sin llamadas de red adicionales
    más allá del refresh automático si el token ha expirado."""
    return load_credentials() is not None

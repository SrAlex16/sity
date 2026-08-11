"""OAuth integration endpoints — self-service per-user connections (Fase 6).

GET    /auth/integrations/{provider}/connect   — start OAuth flow, returns auth_url
GET    /auth/integrations/{provider}/callback  — exchange code for tokens, upsert in DB
DELETE /auth/integrations/{provider}           — soft-disconnect (is_active=False)

All endpoints require an authenticated user (not Guest). Identity is always taken
from the JWT session cookie — never from state parameters or request body.

State protection:
  The state token encodes (user_id, provider, ts) and is signed with HMAC-SHA256
  using SITY_ENCRYPTION_KEY. The callback verifies the signature AND that the
  user_id embedded in state matches the user_id of the current session, so a state
  issued to user A cannot be completed by user B even if HMAC is intact.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests as _http
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.encryption import encrypt_str
from app.core.runtime_config import get_public_base_url
from app.memory.db import get_session
from app.memory.models import UserIntegration
from app.trace.logger import write_log

router = APIRouter(prefix="/auth/integrations", tags=["integrations"])

_STATE_MAX_AGE_SECS = 600  # 10 minutes
_PROVIDERS = frozenset({"google", "spotify"})
_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPOTIFY_SCOPES = " ".join([
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-read-recently-played",
    "user-modify-playback-state",
    "playlist-read-private",
])


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

class _StateExpired(Exception):
    pass


def _hmac_key() -> bytes:
    key = os.environ.get("SITY_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("SITY_ENCRYPTION_KEY no está configurada")
    return key.encode()


def _make_state(user_id: int, provider: str, code_verifier: str = "") -> str:
    """Encode (user_id, provider, ts, code_verifier) signed with HMAC-SHA256.

    code_verifier is empty for providers that don't use PKCE (Spotify).
    """
    ts = int(time.time())
    payload = f"{user_id}:{provider}:{ts}:{code_verifier}"
    sig = hmac.new(_hmac_key(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _verify_state(state: str) -> tuple[int, str, str]:
    """Parse and validate a state token.

    Returns (user_id, provider, code_verifier) on success.
    code_verifier is an empty string for non-PKCE providers.
    Raises _StateExpired if valid but older than _STATE_MAX_AGE_SECS.
    Raises ValueError for any structural or signature problem.
    """
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
        # maxsplit=4 → [user_id, provider, ts, code_verifier, sig]
        parts = raw.split(":", 4)
        if len(parts) != 5:
            raise ValueError
        user_id_str, provider, ts_str, code_verifier, sig = parts
        user_id = int(user_id_str)
        ts = int(ts_str)
    except (ValueError, Exception):
        raise ValueError("state inválido")

    payload = f"{user_id_str}:{provider}:{ts_str}:{code_verifier}"
    expected_sig = hmac.new(_hmac_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("firma inválida")

    if time.time() - ts > _STATE_MAX_AGE_SECS:
        raise _StateExpired()

    return user_id, provider, code_verifier


# ---------------------------------------------------------------------------
# PKCE helpers (required by Google since 2024)
# ---------------------------------------------------------------------------

def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    code_verifier = secrets.token_urlsafe(64)  # 86 URL-safe chars
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------

def _redirect_uri(provider: str) -> str:
    base = get_public_base_url()
    return f"{base}/auth/integrations/{provider}/callback"


def _google_client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google no está configurado en el servidor")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri("google")],
        }
    }


def _google_auth_url(redirect_uri: str, state: str, code_challenge: str) -> str:
    flow = Flow.from_client_config(
        _google_client_config(), GOOGLE_SCOPES, redirect_uri=redirect_uri
    )
    url, _ = flow.authorization_url(
        prompt="consent", state=state, access_type="offline",
        code_challenge=code_challenge, code_challenge_method="S256",
    )
    return url


def _google_exchange_code(code: str, redirect_uri: str, code_verifier: str = "") -> tuple[str, str]:
    """Returns (credentials_json, scopes_str). Makes network call to Google."""
    flow = Flow.from_client_config(
        _google_client_config(), GOOGLE_SCOPES, redirect_uri=redirect_uri
    )
    flow.fetch_token(code=code, code_verifier=code_verifier or None)
    creds = flow.credentials
    scopes_str = " ".join(sorted(creds.scopes or GOOGLE_SCOPES))
    return creds.to_json(), scopes_str


def _spotify_auth_url(redirect_uri: str, state: str) -> str:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(status_code=503, detail="Spotify no está configurado en el servidor")
    return "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SPOTIFY_SCOPES,
        "state": state,
        "show_dialog": "true",
    })


def _spotify_exchange_code(code: str, redirect_uri: str) -> tuple[str, str]:
    """Returns (credentials_json, scopes_str). Makes network call to Spotify."""
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Spotify no está configurado en el servidor")

    import base64 as _b64
    auth = _b64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = _http.post(
        _SPOTIFY_TOKEN_URL,
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        timeout=10,
    )
    if not resp.ok:
        raise HTTPException(status_code=502, detail="Error al obtener token de Spotify")
    token = resp.json()
    token["expires_at"] = time.time() + token.get("expires_in", 3600)
    token["client_id"] = client_id
    token["client_secret"] = client_secret
    return json.dumps(token), token.get("scope", SPOTIFY_SCOPES)


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _upsert_integration(
    session: Session,
    user_id: int,
    provider: str,
    creds_json: str,
    scopes: str,
) -> UserIntegration:
    """Insert or update UserIntegration, always setting is_active=True."""
    row = session.exec(
        select(UserIntegration)
        .where(UserIntegration.user_id == user_id)
        .where(UserIntegration.provider == provider)
    ).first()
    now = datetime.now(timezone.utc)
    encrypted = encrypt_str(creds_json)
    if row is None:
        row = UserIntegration(
            user_id=user_id, provider=provider,
            encrypted_credentials=encrypted,
            scopes=scopes, connected_at=now, is_active=True,
        )
        session.add(row)
    else:
        row.encrypted_credentials = encrypted
        row.scopes = scopes
        row.connected_at = now
        row.is_active = True
        session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# HTML templates — shown directly in the OAuth popup tab
# ---------------------------------------------------------------------------

_EXPIRED_HTML = """\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enlace caducado — Sity</title>
<style>body{font-family:sans-serif;background:#0a0a0f;color:#e8e8f0;max-width:480px;margin:4rem auto;line-height:1.5;text-align:center;padding:1rem}</style>
</head>
<body>
<p style="color:#ff7070;font-size:1.1rem">El enlace de autorización caducó</p>
<p style="color:#9090a8">Vuelve a intentarlo desde <strong>Ajustes &rarr; Integraciones</strong>.</p>
</body>
</html>"""

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conexión completada — Sity</title>
<style>body{font-family:sans-serif;background:#0a0a0f;color:#e8e8f0;max-width:480px;margin:4rem auto;line-height:1.5;text-align:center;padding:1rem}</style>
</head>
<body>
<p style="color:#00f5ff;font-size:1.4rem">&#10003; Conexión completada</p>
<p style="color:#9090a8">Ya puedes cerrar esta pestaña y volver a Sity.</p>
<script>
try{var ch=new BroadcastChannel('sity_oauth');ch.postMessage({type:'oauth_connected',provider:'__PROVIDER__'});ch.close();}catch(e){}
setTimeout(function(){try{window.close();}catch(e){}},1500);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class IntegrationStatus(BaseModel):
    provider: str
    connected: bool
    scopes: str | None = None
    connected_at: str | None = None


def _check_provider(provider: str) -> None:
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Proveedor desconocido: {provider!r}")


def _require_user(current: CurrentUser) -> int:
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    assert current.user_id is not None
    return current.user_id


@router.get("")
def list_integrations(
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[IntegrationStatus]:
    """Return connection status for all supported providers for the current user.

    Guests always receive an empty list (no persistent identity).
    """
    if current.is_guest:
        return []

    rows = session.exec(
        select(UserIntegration)
        .where(UserIntegration.user_id == current.user_id)
        .where(UserIntegration.is_active == True)  # noqa: E712
    ).all()
    active = {row.provider: row for row in rows}

    result = []
    for provider in sorted(_PROVIDERS):
        row = active.get(provider)
        connected_at: str | None = None
        if row and row.connected_at:
            ts = row.connected_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            connected_at = ts.isoformat()
        result.append(IntegrationStatus(
            provider=provider,
            connected=row is not None,
            scopes=row.scopes if row else None,
            connected_at=connected_at,
        ))
    return result


@router.get("/{provider}/connect")
def connect(
    provider: str,
    current: CurrentUser = Depends(get_current_user),
) -> dict:
    """Start OAuth flow. Returns {auth_url} for the frontend to open in a new tab."""
    _check_provider(provider)
    user_id = _require_user(current)

    redir = _redirect_uri(provider)
    if provider == "google":
        code_verifier, code_challenge = _generate_pkce_pair()
        state = _make_state(user_id, provider, code_verifier)
        url = _google_auth_url(redir, state, code_challenge)
    else:
        state = _make_state(user_id, provider)
        url = _spotify_auth_url(redir, state)

    write_log(level="INFO", module="integrations", event="oauth_connect_initiated",
              payload={"user_id": user_id, "provider": provider})
    return {"auth_url": url}


@router.get("/{provider}/callback")
def callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Receive OAuth redirect, exchange code for tokens, persist to UserIntegration."""
    _check_provider(provider)
    user_id = _require_user(current)

    if error:
        return HTMLResponse(content=_EXPIRED_HTML.replace(
            "caducó", f"fue rechazado por el proveedor ({error})"
        ), status_code=400)

    if not state:
        raise HTTPException(status_code=400, detail="Falta el parámetro state")

    try:
        state_user_id, state_provider, code_verifier = _verify_state(state)
    except _StateExpired:
        return HTMLResponse(content=_EXPIRED_HTML, status_code=400)
    except ValueError:
        raise HTTPException(status_code=400, detail="State inválido o manipulado")

    # Defense in depth: user who started the flow must match the current session.
    if state_user_id != user_id:
        write_log(level="WARN", module="integrations", event="oauth_state_user_mismatch",
                  payload={"session_user_id": user_id, "state_user_id": state_user_id})
        raise HTTPException(status_code=403, detail="El state no corresponde a la sesión actual")

    if state_provider != provider:
        raise HTTPException(status_code=400, detail="El state no corresponde al proveedor")

    if not code:
        raise HTTPException(status_code=400, detail="Falta el código de autorización")

    redir = _redirect_uri(provider)
    if provider == "google":
        creds_json, scopes = _google_exchange_code(code, redir, code_verifier)
    else:
        creds_json, scopes = _spotify_exchange_code(code, redir)

    _upsert_integration(session, user_id, provider, creds_json, scopes)

    write_log(level="AUDIT", module="integrations", event="oauth_connected",
              payload={"user_id": user_id, "provider": provider}, audit=True)

    return HTMLResponse(content=_SUCCESS_HTML.replace("__PROVIDER__", provider))


@router.delete("/{provider}")
def disconnect(
    provider: str,
    current: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Soft-disconnect: sets is_active=False, preserving the audit row."""
    _check_provider(provider)
    user_id = _require_user(current)

    row = session.exec(
        select(UserIntegration)
        .where(UserIntegration.user_id == user_id)
        .where(UserIntegration.provider == provider)
        .where(UserIntegration.is_active == True)  # noqa: E712
    ).first()

    if row is None:
        raise HTTPException(status_code=404, detail=f"No tienes {provider} conectado")

    row.is_active = False
    session.add(row)
    session.commit()

    write_log(level="AUDIT", module="integrations", event="oauth_disconnected",
              payload={"user_id": user_id, "provider": provider}, audit=True)
    return {"ok": True}

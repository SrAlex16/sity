"""Ejecución de acciones de Google Calendar confirmadas por el usuario."""
from __future__ import annotations

import concurrent.futures as _cf
import json
import subprocess
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

_GOOGLE_CALL_TIMEOUT = 25  # seconds — matches google_tools._GOOGLE_CALL_TIMEOUT


def _exec(fn, *, label: str = "google_action"):
    """Run fn() in a thread with a hard timeout. Prevents indefinite hangs on slow API calls."""
    future = _cf.ThreadPoolExecutor(max_workers=1).submit(fn)
    try:
        return future.result(timeout=_GOOGLE_CALL_TIMEOUT)
    except _cf.TimeoutError:
        raise TimeoutError(f"{label} no respondió en {_GOOGLE_CALL_TIMEOUT}s")


def _build_service(api: str, version: str, creds):
    """Build a Google API service with AuthorizedHttp + thread timeout.
    credentials= and http= are mutually exclusive in build_from_document; wrap creds
    into AuthorizedHttp so only http= is passed.
    """
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    authed_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
    future = _cf.ThreadPoolExecutor(max_workers=1).submit(
        build, api, version, http=authed_http, static_discovery=True
    )
    try:
        return future.result(timeout=_GOOGLE_CALL_TIMEOUT)
    except _cf.TimeoutError:
        raise TimeoutError(f"Google {api}.{version} build tardó más de {_GOOGLE_CALL_TIMEOUT}s")


def _get_system_timezone() -> str:
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=3,
        )
        tz = result.stdout.strip()
        if tz:
            return tz
    except Exception:
        pass
    return "Europe/Madrid"


@dataclass
class GoogleActionResult:
    ok: bool
    text: str


_NOT_CONNECTED_MSG = (
    "Google no está conectado. Conéctalo en Ajustes → Integraciones "
    "o a través de /auth/integrations/google/connect."
)


def _resolve_creds(user_id: int | None, session: Session | None):
    """User-first credential resolution, same logic as google_tools._resolve_google_creds."""
    from app.integrations.google_auth import load_credentials, load_user_credentials

    if user_id is not None and session is not None:
        creds = load_user_credentials(user_id, session)
        if creds is not None:
            return creds
    return load_credentials()


def execute_google_action(
    payload: dict[str, Any],
    user_id: int | None = None,
    session: Session | None = None,
) -> GoogleActionResult:
    action = payload.get("action", "")

    if action == "calendar_create_event":
        return _create_calendar_event(payload, user_id, session)

    if action == "calendar_edit_event":
        return _edit_calendar_event(payload, user_id, session)

    if action == "calendar_delete_event":
        return _delete_calendar_event(payload, user_id, session)

    return GoogleActionResult(ok=False, text=f"Acción de Google desconocida: {action}")


def _create_calendar_event(
    payload: dict[str, Any],
    user_id: int | None,
    session: Session | None,
) -> GoogleActionResult:
    creds = _resolve_creds(user_id, session)
    if creds is None:
        return GoogleActionResult(ok=False, text=_NOT_CONNECTED_MSG)

    title = payload.get("title", "")
    start_iso = payload.get("start_iso", "")
    end_iso = payload.get("end_iso", "")
    description = payload.get("description", "")

    service = _build_service("calendar", "v3", creds)

    tz = _get_system_timezone()
    event_body: dict[str, Any] = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": tz},
        "end": {"dateTime": end_iso, "timeZone": tz},
    }

    event = _exec(
        lambda: service.events().insert(calendarId="primary", body=event_body).execute(),
        label="calendar.events.insert",
    )
    link = event.get("htmlLink", "")
    return GoogleActionResult(
        ok=True,
        text=f"Evento creado: {title}\nEnlace: {link}",
    )


def _edit_calendar_event(
    payload: dict[str, Any],
    user_id: int | None,
    session: Session | None,
) -> GoogleActionResult:
    creds = _resolve_creds(user_id, session)
    if creds is None:
        return GoogleActionResult(ok=False, text=_NOT_CONNECTED_MSG)

    event_id = payload.get("event_id", "")
    service = _build_service("calendar", "v3", creds)

    try:
        event = _exec(
            lambda: service.events().get(calendarId="primary", eventId=event_id).execute(),
            label="calendar.events.get",
        )
    except Exception as exc:
        return GoogleActionResult(ok=False, text=f"No se encontró el evento: {exc}")

    tz = _get_system_timezone()
    if payload.get("title"):
        event["summary"] = payload["title"]
    if payload.get("description") is not None:
        event["description"] = payload["description"]
    if payload.get("location"):
        event["location"] = payload["location"]
    if payload.get("start_iso"):
        event["start"] = {"dateTime": payload["start_iso"], "timeZone": tz}
    if payload.get("end_iso"):
        event["end"] = {"dateTime": payload["end_iso"], "timeZone": tz}

    updated = _exec(
        lambda: service.events().update(calendarId="primary", eventId=event_id, body=event).execute(),
        label="calendar.events.update",
    )
    return GoogleActionResult(
        ok=True,
        text=f"Evento actualizado: {updated.get('summary')}\n{updated.get('htmlLink', '')}",
    )


def _delete_calendar_event(
    payload: dict[str, Any],
    user_id: int | None,
    session: Session | None,
) -> GoogleActionResult:
    creds = _resolve_creds(user_id, session)
    if creds is None:
        return GoogleActionResult(ok=False, text=_NOT_CONNECTED_MSG)

    event_id = payload.get("event_id", "")
    service = _build_service("calendar", "v3", creds)

    try:
        _exec(
            lambda: service.events().delete(calendarId="primary", eventId=event_id).execute(),
            label="calendar.events.delete",
        )
        return GoogleActionResult(ok=True, text=f"Evento {event_id} eliminado.")
    except Exception as exc:
        return GoogleActionResult(ok=False, text=f"Error al borrar el evento: {exc}")


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)

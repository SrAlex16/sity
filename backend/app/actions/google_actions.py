"""Ejecución de acciones de Google Calendar confirmadas por el usuario."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


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


def execute_google_action(payload: dict[str, Any]) -> GoogleActionResult:
    action = payload.get("action", "")

    if action == "calendar_create_event":
        return _create_calendar_event(payload)

    return GoogleActionResult(ok=False, text=f"Acción de Google desconocida: {action}")


def _create_calendar_event(payload: dict[str, Any]) -> GoogleActionResult:
    from app.integrations.google_auth import is_google_connected, load_credentials
    from googleapiclient.discovery import build

    if not is_google_connected():
        return GoogleActionResult(
            ok=False,
            text="Google no está conectado. Ejecuta scripts/google_auth_setup.py para autorizar el acceso.",
        )

    title = payload.get("title", "")
    start_iso = payload.get("start_iso", "")
    end_iso = payload.get("end_iso", "")
    description = payload.get("description", "")

    creds = load_credentials()
    service = build("calendar", "v3", credentials=creds)

    tz = _get_system_timezone()
    event_body: dict[str, Any] = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": tz},
        "end": {"dateTime": end_iso, "timeZone": tz},
    }

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    link = event.get("htmlLink", "")
    return GoogleActionResult(
        ok=True,
        text=f"Evento creado: {title}\nEnlace: {link}",
    )


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)

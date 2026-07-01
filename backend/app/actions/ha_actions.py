from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class HaActionResult:
    ok: bool
    text: str


def execute_ha_action(payload: dict[str, Any]) -> HaActionResult:
    from app.tools.handlers.ha_tools import _ha_post

    entity_id    = payload.get("entity_id", "")
    service      = payload.get("service", "")
    service_data = dict(payload.get("service_data") or {})
    service_data["entity_id"] = entity_id

    if not entity_id or not service:
        return HaActionResult(ok=False, text="Payload incompleto para ejecutar acción de HA.")

    domain, action = service.split(".", 1) if "." in service else ("", service)

    try:
        _ha_post(f"services/{domain}/{action}", service_data)
        return HaActionResult(ok=True, text=f"✓ {service} ejecutado en {entity_id}.")
    except Exception as e:
        return HaActionResult(ok=False, text=f"Error ejecutando {service} en {entity_id}: {e}")


def parse_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)

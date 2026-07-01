from __future__ import annotations

import os

import httpx

from app.actions.confirmation_manager import ConfirmationManager
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult

_HA_URL   = os.getenv("HA_URL", "http://localhost:8123")
_HA_TOKEN = os.getenv("HA_TOKEN", "")

_HEADERS: dict[str, str] = {
    "Authorization": f"Bearer {_HA_TOKEN}",
    "Content-Type": "application/json",
}

_CONTROLLABLE = {
    "switch", "light", "cover", "climate", "fan",
    "media_player", "lock", "input_boolean", "scene",
    "script", "automation",
}

_REQUIRES_CONFIRMATION = {
    "lock", "alarm_arm_away", "alarm_arm_home", "alarm_disarm",
}


def _ha_get(path: str) -> dict | list:
    url = f"{_HA_URL}/api/{path}"
    resp = httpx.get(url, headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _ha_post(path: str, data: dict) -> dict | list:
    url = f"{_HA_URL}/api/{path}"
    resp = httpx.post(url, headers=_HEADERS, json=data, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _format_entity(e: dict) -> str:
    entity_id = e.get("entity_id", "")
    state     = e.get("state", "")
    friendly  = e.get("attributes", {}).get("friendly_name", entity_id)
    area      = e.get("area_id", "")
    line = f"{entity_id} | {friendly} | estado: {state}"
    if area:
        line += f" | área: {area}"
    return line


@tool_handler("ha_list_entities")
def handle_ha_list_entities(ctx: ToolContext) -> ToolExecutionResult:
    domain  = str(ctx.tool_input.get("domain", "")).strip().lower()
    area    = str(ctx.tool_input.get("area", "")).strip().lower()
    keyword = str(ctx.tool_input.get("keyword", "")).strip().lower()

    try:
        states = _ha_get("states")
        if not isinstance(states, list):
            raise ValueError("Respuesta inesperada de HA")
    except Exception as e:
        msg = f"No se pudo conectar con Home Assistant: {e}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    results = []
    for entity in states:
        eid = entity.get("entity_id", "")
        dom = eid.split(".")[0] if "." in eid else ""

        if domain and dom != domain:
            continue
        if not domain and dom not in _CONTROLLABLE:
            continue

        attrs    = entity.get("attributes", {})
        friendly = attrs.get("friendly_name", "").lower()
        if keyword and keyword not in eid.lower() and keyword not in friendly:
            continue

        results.append(_format_entity(entity))

    if not results:
        msg = "No se encontraron dispositivos" + (f" para '{keyword}'" if keyword else "") + "."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    output = f"{len(results)} dispositivo(s) encontrado(s):\n" + "\n".join(results)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("ha_get_state")
def handle_ha_get_state(ctx: ToolContext) -> ToolExecutionResult:
    entity_id = str(ctx.tool_input.get("entity_id", "")).strip()
    if not entity_id:
        msg = "Falta entity_id."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    try:
        entity   = _ha_get(f"states/{entity_id}")
        if not isinstance(entity, dict):
            raise ValueError("Respuesta inesperada")
        state    = entity.get("state", "desconocido")
        attrs    = entity.get("attributes", {})
        friendly = attrs.get("friendly_name", entity_id)
        details  = ", ".join(
            f"{k}: {v}" for k, v in attrs.items()
            if k != "friendly_name" and not str(v).startswith("http")
        )
        output = f"{friendly} ({entity_id}): {state}"
        if details:
            output += f"\nAtributos: {details}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )
    except Exception as e:
        msg = f"No se pudo obtener el estado de '{entity_id}': {e}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )


@tool_handler("ha_call_service")
def handle_ha_call_service(ctx: ToolContext) -> ToolExecutionResult:
    entity_id    = str(ctx.tool_input.get("entity_id", "")).strip()
    service      = str(ctx.tool_input.get("service", "")).strip()
    service_data = dict(ctx.tool_input.get("service_data") or {})

    if not entity_id or not service:
        msg = "Faltan entity_id o service."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

    if "." in service:
        domain, action = service.split(".", 1)
    else:
        domain = entity_id.split(".")[0]
        action = service

    if action in _REQUIRES_CONFIRMATION:
        payload: dict = {
            "action": "ha_call_service",
            "entity_id": entity_id,
            "service": f"{domain}.{action}",
            "service_data": service_data,
        }
        manager  = ConfirmationManager(ctx.executor.session)
        existing = manager.find_equivalent_pending_action(action_type="ha", payload=payload)
        if existing:
            local_text = (
                f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
                f"Confirma con: `{existing.confirmation_phrase}`"
            )
            result = {
                "success": True, "message": local_text,
                "action_id": existing.id,
                "confirmation_phrase": existing.confirmation_phrase,
                "summary": existing.summary,
                "already_existed": True,
                "local_final": True, "text": local_text, "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=ctx.tool_name, ok=True, message=local_text,
                updated_parameters=[], raw_result=result,
            )

        created = manager.create_pending_action(
            action_type="ha",
            risk_level="safe_confirm",
            summary=f"HA: {domain}.{action} en {entity_id}",
            payload=payload,
            trace_id=ctx.trace_id,
        )
        local_text = (
            f"Acción pendiente creada: {created.summary}\n\n"
            f"Confirma con: `{created.confirmation_phrase}`"
        )
        result = {
            "success": True, "message": local_text,
            "action_id": created.id,
            "confirmation_phrase": created.confirmation_phrase,
            "summary": created.summary,
            "local_final": True, "text": local_text, "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result=result,
        )

    # Reversible (turn_on / turn_off / toggle / etc.) — execute directly
    try:
        service_data["entity_id"] = entity_id
        raw = _ha_post(f"services/{domain}/{action}", service_data)
        changed = [s.get("entity_id", "") for s in raw] if isinstance(raw, list) else []
        output = f"✓ {domain}.{action} ejecutado en {entity_id}."
        if changed:
            output += f" Estados actualizados: {', '.join(changed)}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )
    except Exception as e:
        msg = f"Error ejecutando {domain}.{action} en {entity_id}: {e}"
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={"output": msg},
        )

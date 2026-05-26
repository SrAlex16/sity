from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.cortex.tool_schemas import PERSONALITY_PARAMETERS
from app.settings.settings_service import SettingsService
from app.actions.confirmation_manager import ConfirmationManager
from app.system.allowed_services import get_allowed_systemd_services
from app.actions.capture_retention_actions import execute_capture_retention_action
from app.actions.file_actions import execute_file_action
from app.actions.sense_actions import execute_sense_action
from app.core.realtime_events import publish_event_sync
from app.trace.logger import write_log
from app.trace.trace_reader import get_events_by_trace_id, get_recent_events
from app.tools.types import ToolExecutionResult


ALLOWED_OPERATIONS = {
    "set_absolute",
    "increase_absolute",
    "decrease_absolute",
}

TOOL_LABELS: dict[str, str] = {
    "capture_camera_snapshot": "Sacando foto…",
    "record_audio_sample": "Grabando audio…",
    "clean_old_captures": "Limpiando capturas antiguas…",
    "get_capture_storage_summary": "Consultando almacenamiento…",
}


class ToolExecutor:
    def __init__(self, session: Session):
        self.session = session
        self.settings_service = SettingsService(session)

    def execute_tool_call(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        trace_id: str,
        client_turn_id: str | None = None,
    ) -> ToolExecutionResult:
        if tool_name in TOOL_LABELS:
            publish_event_sync(client_turn_id, {
                "type": "tool_started",
                "tool": tool_name,
                "label": TOOL_LABELS[tool_name],
                "can_cancel": tool_name in {"record_audio_sample", "capture_camera_snapshot"},
            })

        result = self._dispatch_tool_call(
            tool_name=tool_name,
            tool_input=tool_input,
            trace_id=trace_id,
            client_turn_id=client_turn_id,
        )

        if tool_name in TOOL_LABELS:
            publish_event_sync(client_turn_id, {
                "type": "tool_finished",
                "tool": tool_name,
            })

        return result

    def _dispatch_tool_call(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        trace_id: str,
        client_turn_id: str | None = None,
    ) -> ToolExecutionResult:
        from app.tools.registry import ToolContext, dispatch_tool, has_handler
        if has_handler(tool_name):
            return dispatch_tool(ToolContext(
                tool_name=tool_name,
                tool_input=tool_input,
                trace_id=trace_id,
                executor=self,
                client_turn_id=client_turn_id,
            ))

        msg = f"Herramienta no soportada: {tool_name}"
        return ToolExecutionResult(
            tool_name=tool_name,
            ok=False,
            message=msg,
            updated_parameters=[],
            raw_result={
                "success": False,
                "message": msg,
                "updated_parameters": [],
                "local_final": True,
                "text": msg,
                "local_model": "tool-policy",
            },
        )

    def _update_personality_settings(
        self,
        *,
        tool_input: dict[str, Any],
        trace_id: str,
    ) -> ToolExecutionResult:
        raw_updates = tool_input.get("updates", [])
        reason = str(tool_input.get("reason", ""))

        if not isinstance(raw_updates, list) or not raw_updates:
            result = {
                "success": False,
                "error_code": "MISSING_UPDATES",
                "message": "updates must be a non-empty list.",
                "allowed_parameters": PERSONALITY_PARAMETERS,
                "allowed_operations": list(ALLOWED_OPERATIONS),
                "local_final": True,
                "text": "No se pudo actualizar la personalidad: falta el campo updates.",
                "local_model": "tool-policy",
            }
            return ToolExecutionResult(
                tool_name="update_personality_settings",
                ok=False,
                message=result["message"],
                updated_parameters=[],
                raw_result=result,
            )

        applied_updates: list[dict[str, Any]] = []
        updated_parameters: list[str] = []
        errors: list[str] = []

        for raw_update in raw_updates[:12]:
            if not isinstance(raw_update, dict):
                errors.append("Update no es un objeto.")
                continue

            parameter = raw_update.get("parameter")
            operation = raw_update.get("operation")
            value = raw_update.get("value")

            if parameter not in PERSONALITY_PARAMETERS:
                errors.append(f"Parámetro no permitido: {parameter}")
                continue

            if operation not in ALLOWED_OPERATIONS:
                errors.append(f"Operación no permitida para {parameter}: {operation}")
                continue

            try:
                amount = float(value)
            except (TypeError, ValueError):
                errors.append(f"Valor inválido para {parameter}: {value}")
                continue

            if amount < 0 or amount > 1:
                errors.append(f"Valor fuera de rango para {parameter}: {amount}")
                continue

            old_value, new_value = self.settings_service.adjust_personality(
                parameter=parameter,
                operation=operation,
                amount=amount,
                source="claude_tool",
            )

            updated_parameters.append(parameter)
            applied_updates.append(
                {
                    "parameter": parameter,
                    "operation": operation,
                    "amount": amount,
                    "old_value": old_value,
                    "new_value": new_value,
                }
            )

        if not applied_updates:
            write_log(
                level="WARN",
                module="tools",
                event="tool_execution_rejected",
                trace_id=trace_id,
                payload={
                    "tool_name": "update_personality_settings",
                    "reason": reason,
                    "input": tool_input,
                    "errors": errors,
                },
                audit=True,
            )

            result = {
                "success": False,
                "message": "Claude pidió cambios, pero ninguno era válido.",
                "updated_parameters": [],
                "errors": errors,
                "local_final": True,
                "text": "No se pudo actualizar la personalidad: ningún cambio era válido.",
                "local_model": "tool-policy",
            }

            return ToolExecutionResult(
                tool_name="update_personality_settings",
                ok=False,
                message=result["message"],
                updated_parameters=[],
                raw_result=result,
            )

        write_log(
            level="AUDIT",
            module="tools",
            event="personality_settings_updated_by_tool",
            trace_id=trace_id,
            payload={
                "tool_name": "update_personality_settings",
                "reason": reason,
                "updates": applied_updates,
                "errors": errors,
            },
            audit=True,
        )

        result = {
            "success": True,
            "message": self._build_success_message(applied_updates),
            "updated_parameters": updated_parameters,
            "updates": applied_updates,
            "errors": errors,
        }

        return ToolExecutionResult(
            tool_name="update_personality_settings",
            ok=True,
            message=result["message"],
            updated_parameters=updated_parameters,
            raw_result=result,
        )

    @staticmethod
    def _summarize_payload(payload: Any) -> Any:
        text = str(payload)
        if len(text) > 500:
            return text[:500] + "...[truncated]"
        return payload

    def _compact_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "timestamp": event.get("timestamp"),
            "level": event.get("level"),
            "module": event.get("module"),
            "event": event.get("event"),
            "trace_id": event.get("trace_id"),
            "payload_summary": self._summarize_payload(event.get("payload", {})),
        }

    def _read_recent_debug_events(
        self,
        *,
        tool_input: dict[str, Any],
        trace_id: str,
    ) -> ToolExecutionResult:
        raw_limit = tool_input.get("limit", 20)
        raw_level = tool_input.get("level")
        raw_module = tool_input.get("module")

        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 20

        limit = max(1, min(50, limit))

        read_limit = max(limit * 5, 200) if raw_level or raw_module else limit
        events = get_recent_events(limit=read_limit)

        if raw_level:
            level = str(raw_level).upper()
            events = [
                event for event in events
                if str(event.get("level", "")).upper() == level
            ]

        if raw_module:
            module = str(raw_module).lower()
            events = [
                event for event in events
                if str(event.get("module", "")).lower() == module
            ]

        compact = [self._compact_event(e) for e in events[:limit]]

        result = {
            "success": True,
            "message": f"Leídos {len(compact)} eventos recientes.",
            "events": compact,
        }

        write_log(
            level="INFO",
            module="tools",
            event="debug_recent_events_read",
            trace_id=trace_id,
            payload={
                "limit": limit,
                "level": raw_level,
                "module": raw_module,
                "returned_events": len(compact),
            },
        )

        return ToolExecutionResult(
            tool_name="read_recent_debug_events",
            ok=True,
            message=result["message"],
            updated_parameters=[],
            raw_result=result,
        )

    def _read_trace_events(
        self,
        *,
        tool_input: dict[str, Any],
        trace_id: str,
    ) -> ToolExecutionResult:
        requested_trace_id = str(tool_input.get("trace_id", "")).strip()

        if not requested_trace_id:
            result = {
                "success": False,
                "message": "trace_id vacío.",
                "events": [],
            }

            return ToolExecutionResult(
                tool_name="read_trace_events",
                ok=False,
                message=result["message"],
                updated_parameters=[],
                raw_result=result,
            )

        events = get_events_by_trace_id(requested_trace_id)

        result = {
            "success": True,
            "message": f"Leídos {len(events)} eventos para {requested_trace_id}.",
            "trace_id": requested_trace_id,
            "events": events,
        }

        write_log(
            level="INFO",
            module="tools",
            event="debug_trace_events_read",
            trace_id=trace_id,
            payload={
                "requested_trace_id": requested_trace_id,
                "returned_events": len(events),
            },
        )

        return ToolExecutionResult(
            tool_name="read_trace_events",
            ok=True,
            message=result["message"],
            updated_parameters=[],
            raw_result=result,
        )

    def _git_propose_action(
        self,
        *,
        tool_input: dict[str, Any],
        trace_id: str,
    ) -> ToolExecutionResult:
        action = str(tool_input.get("action", "")).strip()
        repo_path = str(tool_input.get("repo_path", "sity")).strip() or "sity"
        branch = str(tool_input.get("branch", "main")).strip() or "main"
        remote = str(tool_input.get("remote", "origin")).strip() or "origin"
        risk_level = str(tool_input.get("risk_level", "critical")).strip()
        summary = str(tool_input.get("summary", "")).strip()

        ALLOWED_GIT_ACTIONS = {"fetch", "pull_ff_only", "push", "create_branch", "checkout_branch", "commit"}
        if action not in ALLOWED_GIT_ACTIONS:
            msg = f"Acción Git no soportada: {action}"
            return ToolExecutionResult(
                tool_name="git_propose_action",
                ok=False,
                message=msg,
                updated_parameters=[],
                raw_result={
                    "success": False, "message": msg,
                    "local_final": True, "text": msg, "local_model": "tool-policy",
                },
            )

        risk_level = "safe" if action == "fetch" else "critical"

        payload: dict[str, Any] = {
            "action": action,
            "repo_path": repo_path,
            "branch": branch,
            "remote": remote,
        }

        if action == "commit":
            commit_message = str(tool_input.get("commit_message", "")).strip()
            files = tool_input.get("files") or []
            payload["commit_message"] = commit_message
            payload["files"] = files

        created = ConfirmationManager(self.session).create_pending_action(
            action_type="git",
            risk_level=risk_level,
            summary=summary or f"Git action {action} on {repo_path}",
            payload=payload,
            trace_id=trace_id,
        )

        confirmation_hint = self._build_confirmation_hint(payload)
        display_message = (
            f"Acción pendiente creada: {created.summary}\n\n"
            f"Confirma con: `{created.confirmation_phrase}`\n"
            f"{confirmation_hint}"
        )

        result = {
            "success": True,
            "message": display_message,
            "action_id": created.id,
            "risk_level": created.risk_level,
            "summary": created.summary,
            "confirmation_phrase": created.confirmation_phrase,
            "confirmation_hint": confirmation_hint,
            "payload": payload,
            "local_final": True,
            "text": display_message,
            "local_model": "pending-action-manager",
        }

        return ToolExecutionResult(
            tool_name="git_propose_action",
            ok=True,
            message=display_message,
            updated_parameters=[],
            raw_result=result,
        )

    def _simple_read_tool(
        self,
        *,
        tool_name: str,
        trace_id: str,
        result: dict[str, Any],
    ) -> ToolExecutionResult:
        write_log(
            level="INFO",
            module="tools",
            event=f"{tool_name}_executed",
            trace_id=trace_id,
            payload={
                "ok": result.get("ok", True),
                "result_keys": list(result.keys()),
            },
        )

        return ToolExecutionResult(
            tool_name=tool_name,
            ok=bool(result.get("ok", True)),
            message=f"{tool_name} ejecutada.",
            updated_parameters=[],
            raw_result={
                "success": bool(result.get("ok", True)),
                "tool_name": tool_name,
                "result": result,
            },
        )

    def _system_propose_action(
        self,
        *,
        tool_input: dict[str, Any],
        trace_id: str,
    ) -> ToolExecutionResult:
        action = str(tool_input.get("action", "")).strip()
        service_name = str(tool_input.get("service_name", "")).strip()
        risk_level = str(tool_input.get("risk_level", "safe")).strip()
        summary = str(tool_input.get("summary", "")).strip()

        allowed_actions = {"start_service", "stop_service", "restart_service"}
        allowed_services = set(get_allowed_systemd_services())

        if action not in allowed_actions:
            msg = f"Acción de sistema no soportada: {action}"
            return ToolExecutionResult(
                tool_name="system_propose_action",
                ok=False,
                message=msg,
                updated_parameters=[],
                raw_result={
                    "success": False, "message": msg,
                    "local_final": True, "text": msg, "local_model": "tool-policy",
                },
            )

        if service_name not in allowed_services:
            msg = f"Servicio no permitido: {service_name}"
            return ToolExecutionResult(
                tool_name="system_propose_action",
                ok=False,
                message=msg,
                updated_parameters=[],
                raw_result={
                    "success": False, "message": msg,
                    "local_final": True, "text": msg, "local_model": "tool-policy",
                },
            )

        if risk_level not in {"safe", "critical"}:
            risk_level = "safe"

        payload: dict[str, Any] = {
            "action": action,
            "service_name": service_name,
        }

        created = ConfirmationManager(self.session).create_pending_action(
            action_type="system",
            risk_level=risk_level,
            summary=summary or f"{action} {service_name}",
            payload=payload,
            trace_id=trace_id,
        )

        local_text = (
            f"Acción pendiente creada: {created.summary}\n\n"
            f"Confirma con: `{created.confirmation_phrase}`"
        )

        result = {
            "success": True,
            "message": local_text,
            "action_id": created.id,
            "risk_level": created.risk_level,
            "summary": created.summary,
            "confirmation_phrase": created.confirmation_phrase,
            "payload": payload,
            "local_final": True,
            "text": local_text,
            "local_model": "pending-action-manager",
        }

        return ToolExecutionResult(
            tool_name="system_propose_action",
            ok=True,
            message=local_text,
            updated_parameters=[],
            raw_result=result,
        )

    def _build_confirmation_hint(self, payload: dict[str, Any]) -> str:
        action = payload.get("action")
        branch = payload.get("branch")

        if action == "checkout_branch" and branch:
            return f'También puedes confirmar con algo claro como: "sí, vuelve a {branch}".'

        if action == "create_branch" and branch:
            return f'También puedes confirmar con algo claro como: "sí, crea la rama {branch}".'

        if action == "pull_ff_only":
            return 'También puedes confirmar con algo claro como: "sí, haz pull".'

        if action == "push":
            return 'También puedes confirmar con algo claro como: "sí, haz push".'

        if action == "fetch":
            return 'También puedes confirmar con algo claro como: "sí, haz fetch".'

        return 'También puedes confirmar con algo claro como: "sí, hazlo".'

    def _build_success_message(self, applied_updates: list[dict[str, Any]]) -> str:
        if len(applied_updates) == 1:
            update = applied_updates[0]
            parameter = update["parameter"]
            new_pct = round(float(update["new_value"]) * 100)
            return f"{parameter} actualizado al {new_pct}%."

        return f"Actualizados {len(applied_updates)} parámetros de personalidad."

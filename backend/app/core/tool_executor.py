from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.cortex.tool_schemas import PERSONALITY_PARAMETERS
from app.settings.settings_service import SettingsService
from app.trace.logger import write_log
from app.trace.trace_reader import get_events_by_trace_id, get_recent_events
from app.system.git_reader import git_branches, git_log, git_remotes, git_status
from app.system.system_reader import (
    list_allowed_directory,
    read_disk_usage,
    read_service_status,
    read_system_status,
    read_top_processes,
)


ALLOWED_OPERATIONS = {
    "set_absolute",
    "increase_absolute",
    "decrease_absolute",
}


@dataclass
class ToolExecutionResult:
    tool_name: str
    ok: bool
    message: str
    updated_parameters: list[str]
    raw_result: dict[str, Any]


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
    ) -> ToolExecutionResult:
        if tool_name == "read_recent_debug_events":
            return self._read_recent_debug_events(
                tool_input=tool_input,
                trace_id=trace_id,
            )

        if tool_name == "read_trace_events":
            return self._read_trace_events(
                tool_input=tool_input,
                trace_id=trace_id,
            )

        if tool_name == "read_system_status":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=read_system_status(),
            )

        if tool_name == "read_disk_usage":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=read_disk_usage(str(tool_input.get("path", "/"))),
            )

        if tool_name == "read_processes":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=read_top_processes(int(tool_input.get("limit", 10))),
            )

        if tool_name == "read_service_status":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=read_service_status(str(tool_input.get("service_name", ""))),
            )

        if tool_name == "list_allowed_directory":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=list_allowed_directory(str(tool_input.get("path", ""))),
            )

        if tool_name == "git_read_status":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=git_status(str(tool_input.get("repo_path", ""))),
            )

        if tool_name == "git_read_log":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=git_log(
                    str(tool_input.get("repo_path", "")),
                    int(tool_input.get("limit", 10)),
                ),
            )

        if tool_name == "git_read_branches":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=git_branches(str(tool_input.get("repo_path", ""))),
            )

        if tool_name == "git_read_remotes":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=git_remotes(str(tool_input.get("repo_path", ""))),
            )

        if tool_name == "update_personality_settings":
            return self._update_personality_settings(
                tool_input=tool_input,
                trace_id=trace_id,
            )

        result = {
            "success": False,
            "message": f"Herramienta no soportada: {tool_name}",
            "updated_parameters": [],
        }

        return ToolExecutionResult(
            tool_name=tool_name,
            ok=False,
            message=result["message"],
            updated_parameters=[],
            raw_result=result,
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

    def _build_success_message(self, applied_updates: list[dict[str, Any]]) -> str:
        if len(applied_updates) == 1:
            update = applied_updates[0]
            parameter = update["parameter"]
            new_pct = round(float(update["new_value"]) * 100)
            return f"{parameter} actualizado al {new_pct}%."

        return f"Actualizados {len(applied_updates)} parámetros de personalidad."

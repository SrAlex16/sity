from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.cortex.tool_schemas import PERSONALITY_PARAMETERS
from app.settings.settings_service import SettingsService
from app.trace.logger import write_log


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
        if tool_name != "update_personality_settings":
            return ToolExecutionResult(
                tool_name=tool_name,
                ok=False,
                message=f"Herramienta no soportada: {tool_name}",
                updated_parameters=[],
            )

        return self._update_personality_settings(
            tool_input=tool_input,
            trace_id=trace_id,
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
            return ToolExecutionResult(
                tool_name="update_personality_settings",
                ok=False,
                message="No hay actualizaciones válidas.",
                updated_parameters=[],
            )

        applied_updates: list[dict[str, Any]] = []
        updated_parameters: list[str] = []

        for raw_update in raw_updates[:12]:
            if not isinstance(raw_update, dict):
                continue

            parameter = raw_update.get("parameter")
            operation = raw_update.get("operation")
            value = raw_update.get("value")

            if parameter not in PERSONALITY_PARAMETERS:
                continue

            if operation not in ALLOWED_OPERATIONS:
                continue

            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue

            if amount < 0 or amount > 1:
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
                },
                audit=True,
            )

            return ToolExecutionResult(
                tool_name="update_personality_settings",
                ok=False,
                message="Claude pidió cambios, pero ninguno era válido.",
                updated_parameters=[],
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
            },
            audit=True,
        )

        return ToolExecutionResult(
            tool_name="update_personality_settings",
            ok=True,
            message=self._build_success_message(applied_updates),
            updated_parameters=updated_parameters,
        )

    def _build_success_message(self, applied_updates: list[dict[str, Any]]) -> str:
        if len(applied_updates) == 1:
            update = applied_updates[0]
            parameter = update["parameter"]
            new_pct = round(float(update["new_value"]) * 100)
            return f"{parameter} actualizado al {new_pct}%."

        return f"Actualizados {len(applied_updates)} parámetros de personalidad."

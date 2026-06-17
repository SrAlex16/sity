from __future__ import annotations

import json
from dataclasses import dataclass

from app.actions.confirmation_manager import ConfirmationManager
from app.actions.file_actions import execute_file_action
from app.actions.git_actions import execute_git_action
from app.actions.git_actions import parse_payload as parse_git_payload
from app.actions.sense_actions import execute_sense_action
from app.actions.sense_actions import parse_payload as parse_sense_payload
from app.actions.system_actions import execute_system_action
from app.actions.system_actions import parse_payload as parse_system_payload
from app.actions.system_config_actions import (
    execute_system_config_action,
    parse_payload as parse_system_config_payload,
)
from app.api.schemas import ChatArtifact, ChatMessageResponse, UsageSummary
from app.chat.artifacts import capture_artifact_from_path
from app.chat.local_flow import LocalFlowContext
from app.memory.models import PendingAction


@dataclass
class _ActionResult:
    text: str
    artifact: ChatArtifact | None = None


class PendingActionRunner:
    def __init__(self, confirmation_manager: ConfirmationManager):
        self.cm = confirmation_manager

    def run(self, pending_action: PendingAction, ctx: LocalFlowContext) -> ChatMessageResponse:
        result = self._execute(pending_action, ctx.trace_id)

        ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
        ctx.save_message(role="sity", text=result.text, trace_id=ctx.trace_id)

        daily_used = ctx.get_usage(ctx.session)
        daily_ratio = daily_used / ctx.daily_budget if ctx.daily_budget > 0 else 0.0

        return ChatMessageResponse(
            ok=True,
            trace_id=ctx.trace_id,
            text=result.text,
            provider="local",
            model="confirmation-manager",
            fallback_used=False,
            error_type=None,
            usage=UsageSummary(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                daily_used_tokens=daily_used,
                daily_budget_tokens=ctx.daily_budget,
                daily_ratio=round(daily_ratio, 4),
            ),
            warnings=[],
            personality_updated=False,
            updated_parameter=None,
            updated_parameters=[],
            artifacts=[result.artifact] if result.artifact else [],
        )

    def _execute(self, action: PendingAction, trace_id: str) -> _ActionResult:
        if action.action_type == "git":
            return self._run_git(action, trace_id)
        if action.action_type == "system":
            return self._run_system(action, trace_id)
        if action.action_type == "system_config":
            return self._run_system_config(action, trace_id)
        if action.action_type == "file":
            return self._run_file(action, trace_id)
        if action.action_type == "sense":
            return self._run_sense(action, trace_id)
        return _ActionResult(text=f"Tipo de acción desconocido: {action.action_type}")

    def _run_git(self, action: PendingAction, trace_id: str) -> _ActionResult:
        try:
            payload = parse_git_payload(action.payload_json)
            result = execute_git_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                lines = [f"Acción ejecutada: {action.summary}"]
                if result.get("pre_command"):
                    lines.append(f"\nPreparación: {' '.join(str(x) for x in result['pre_command'])}")
                    pre_out = result.get("pre_stdout", "").strip()
                    if pre_out:
                        lines.append(f"Salida: {pre_out}")
                lines.append(f"\nComando: {' '.join(str(x) for x in result.get('command', []))}")
                lines.append(f"Salida:\n{result.get('stdout', '') or '(sin salida)'}")
                return _ActionResult(text="\n".join(lines))
            else:
                error = result.get("stderr", "Error desconocido")
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=f"No he podido ejecutar la acción pendiente {action.id}.\n\nError:\n{error}"
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=f"Falló la ejecución de la acción pendiente {action.id}: {exc}")

    def _run_system(self, action: PendingAction, trace_id: str) -> _ActionResult:
        try:
            payload = parse_system_payload(action.payload_json)
            result = execute_system_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                text = (
                    f"Acción ejecutada: {action.summary}\n\n"
                    f"Comando: {' '.join(str(x) for x in result.get('command', []))}\n"
                    f"Salida:\n{result.get('stdout', '') or '(sin salida)'}"
                )
                if result.get("post_status"):
                    text += f"\nEstado posterior: {result['post_status']}"
                return _ActionResult(text=text)
            else:
                error = (
                    result.get("stderr")
                    or result.get("stdout")
                    or f"El comando terminó sin confirmación de éxito. Estado posterior: {result.get('post_status', 'desconocido')}"
                )
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=f"No he podido ejecutar la acción pendiente {action.id}.\n\nError:\n{error}"
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=f"Falló la ejecución de la acción pendiente {action.id}: {exc}")

    def _run_system_config(self, action: PendingAction, trace_id: str) -> _ActionResult:
        try:
            payload = parse_system_config_payload(action.payload_json)
            result = execute_system_config_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                return _ActionResult(
                    text=(
                        f"Acción ejecutada: {action.summary}\n\n"
                        f"{result.get('message', 'Configuración actualizada.')}"
                    )
                )
            else:
                error = result.get("stderr", "Error desconocido")
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=f"No he podido ejecutar la acción pendiente {action.id}.\n\nError:\n{error}"
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=f"Falló la ejecución de la acción pendiente {action.id}: {exc}")

    def _run_file(self, action: PendingAction, trace_id: str) -> _ActionResult:
        try:
            payload = json.loads(action.payload_json)
            payload["pending_action_id"] = action.id
            payload["trace_id"] = trace_id
            file_action = payload.get("action", "")
            result = execute_file_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                path = result.get("path", "")
                if file_action == "apply_unified_diff":
                    text = f"Unified diff aplicado: {path}"
                elif file_action == "rollback_file_change":
                    restored_from = result.get("restored_from_backup_path", "")
                    text = f"Rollback aplicado: {path}\nRestaurado desde: {restored_from}"
                elif file_action == "apply_text_patch":
                    text = f"Patch aplicado: {path}"
                elif file_action == "write_file":
                    created = result.get("created", True)
                    text = f"Archivo {'creado' if created else 'sobreescrito'}: {path}"
                else:
                    text = f"Acción de archivo ejecutada: {path}"
                return _ActionResult(text=text)
            else:
                error = result.get("error", "Error desconocido")
                self.cm.mark_failed(action, trace_id, error)
                if file_action == "apply_unified_diff":
                    text = f"No he podido aplicar el unified diff: {error}"
                elif file_action == "rollback_file_change":
                    text = f"No he podido hacer el rollback: {error}"
                elif file_action == "apply_text_patch":
                    text = f"No he podido aplicar el patch: {error}"
                else:
                    text = f"No he podido escribir el archivo: {error}"
                return _ActionResult(text=text)
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=f"Falló la acción de archivo: {exc}")

    def _run_sense(self, action: PendingAction, trace_id: str) -> _ActionResult:
        try:
            payload = parse_sense_payload(action.payload_json)
            result = execute_sense_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                artifact = capture_artifact_from_path(str(result.get("path", "")))
                return _ActionResult(text=f"Listo. {action.summary}.", artifact=artifact)
            else:
                error = result.get("stderr") or result.get("stdout") or "Error desconocido"
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=f"No he podido ejecutar la acción pendiente {action.id}.\n\nError:\n{error}"
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=f"Falló la ejecución de la acción pendiente {action.id}: {exc}")

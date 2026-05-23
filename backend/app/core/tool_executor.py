from __future__ import annotations

import app.tools.handlers  # noqa: F401 — registers all tool handlers
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from app.cortex.tool_schemas import PERSONALITY_PARAMETERS
from app.settings.settings_service import SettingsService
from app.actions.confirmation_manager import ConfirmationManager
from app.actions.capture_retention_actions import execute_capture_retention_action
from app.actions.file_actions import execute_file_action
from app.actions.sense_actions import execute_sense_action
from app.core.realtime_events import publish_event_sync
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
from app.senses.audio import list_audio_devices
from app.senses.camera import list_camera_devices


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
            ))

        if tool_name == "write_file":
            path = str(tool_input.get("path", ""))
            content = str(tool_input.get("content", ""))
            create_parent_dirs = bool(tool_input.get("create_parent_dirs", False))

            from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
            try:
                assert_write_allowed(_resolve_path(path))
            except FileAccessError as exc:
                err = str(exc)
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=err,
                    updated_parameters=[], raw_result={
                        "success": False, "message": err,
                        "local_final": True, "text": f"No puedo escribir en esa ruta: {err}", "local_model": "tool-policy",
                    },
                )

            write_payload = {
                "action": "write_file",
                "path": path,
                "content": content,
                "create_parent_dirs": create_parent_dirs,
            }
            manager = ConfirmationManager(self.session)
            existing = manager.find_equivalent_pending_action(
                action_type="file",
                payload=write_payload,
            )
            if existing:
                local_text = (
                    f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
                    f"Confirma con: `{existing.confirmation_phrase}`"
                )
                result = {
                    "success": True,
                    "message": local_text,
                    "action_id": existing.id,
                    "confirmation_phrase": existing.confirmation_phrase,
                    "summary": existing.summary,
                    "already_existed": True,
                    "local_final": True,
                    "text": local_text,
                    "local_model": "pending-action-manager",
                }
                return ToolExecutionResult(
                    tool_name=tool_name, ok=True, message=local_text,
                    updated_parameters=[], raw_result=result,
                )

            created = manager.create_pending_action(
                action_type="file",
                risk_level="critical",
                summary=f"Escribir archivo {path}",
                payload=write_payload,
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
                "confirmation_phrase": created.confirmation_phrase,
                "summary": created.summary,
                "local_final": True,
                "text": local_text,
                "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name,
                ok=True,
                message=local_text,
                updated_parameters=[],
                raw_result=result,
            )

        if tool_name == "apply_text_patch":
            path = str(tool_input.get("path", ""))
            old_text = str(tool_input.get("old_text", ""))
            new_text = str(tool_input.get("new_text", ""))

            from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
            try:
                assert_write_allowed(_resolve_path(path))
            except FileAccessError as exc:
                err = str(exc)
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=err,
                    updated_parameters=[], raw_result={
                        "success": False, "message": err,
                        "local_final": True, "text": f"No puedo modificar esa ruta: {err}", "local_model": "tool-policy",
                    },
                )

            preview = execute_file_action({
                "action": "preview_text_patch",
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
            })

            if not preview.get("ok"):
                msg = preview.get("error", "Error generando preview")
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={
                        "success": False, "message": msg,
                        "local_final": True, "text": f"Error al generar el preview del patch: {msg}", "local_model": "tool-policy",
                    },
                )

            diff = preview.get("diff", "")
            diff_truncated = preview.get("diff_truncated", False)
            diff_display = diff[:2000] + ("\n... diff truncado ..." if len(diff) > 2000 else "")

            patch_payload = {
                "action": "apply_text_patch",
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
            }
            manager = ConfirmationManager(self.session)
            existing = manager.find_equivalent_pending_action(
                action_type="file",
                payload=patch_payload,
            )
            if existing:
                local_text = (
                    f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
                    f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
                    f"Confirma con: `{existing.confirmation_phrase}`"
                )
                result = {
                    "success": True,
                    "message": local_text,
                    "action_id": existing.id,
                    "confirmation_phrase": existing.confirmation_phrase,
                    "summary": existing.summary,
                    "diff": diff_display,
                    "diff_truncated": diff_truncated,
                    "already_existed": True,
                    "local_final": True,
                    "text": local_text,
                    "local_model": "pending-action-manager",
                }
                return ToolExecutionResult(
                    tool_name=tool_name, ok=True, message=local_text,
                    updated_parameters=[], raw_result=result,
                )

            created = manager.create_pending_action(
                action_type="file",
                risk_level="critical",
                summary=f"Modificar {path}",
                payload={
                    "action": "apply_text_patch",
                    "path": path,
                    "old_text": old_text,
                    "new_text": new_text,
                },
                trace_id=trace_id,
            )

            display_message = (
                f"Acción pendiente creada: {created.summary}\n\n"
                f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
                f"Confirma con: `{created.confirmation_phrase}`"
            )

            result = {
                "success": True,
                "message": display_message,
                "action_id": created.id,
                "confirmation_phrase": created.confirmation_phrase,
                "summary": created.summary,
                "diff": diff_display,
                "diff_truncated": diff_truncated,
                "local_final": True,
                "text": display_message,
                "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name, ok=True, message=display_message,
                updated_parameters=[], raw_result=result,
            )

        if tool_name == "apply_unified_diff":
            diff_text = str(tool_input.get("diff", ""))

            preview = execute_file_action({
                "action": "preview_unified_diff",
                "diff": diff_text,
            })

            if not preview.get("ok"):
                msg = preview.get("error", "Error generando preview de unified diff")
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={
                        "success": False, "message": msg,
                        "local_final": True, "text": f"Error al validar el unified diff: {msg}", "local_model": "tool-policy",
                    },
                )

            path = str(preview.get("path", "archivo desconocido"))
            diff_preview = str(preview.get("diff", ""))
            diff_truncated = bool(preview.get("diff_truncated", False))
            diff_display = diff_preview[:2000] + ("\n... diff truncado ..." if len(diff_preview) > 2000 else "")

            unified_payload = {
                "action": "apply_unified_diff",
                "diff": diff_text,
            }
            manager = ConfirmationManager(self.session)
            existing = manager.find_equivalent_pending_action(
                action_type="file",
                payload=unified_payload,
            )
            if existing:
                local_text = (
                    f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
                    f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
                    f"Confirma con: `{existing.confirmation_phrase}`"
                )
                result = {
                    "success": True,
                    "message": local_text,
                    "action_id": existing.id,
                    "confirmation_phrase": existing.confirmation_phrase,
                    "summary": existing.summary,
                    "diff": diff_display,
                    "diff_truncated": diff_truncated,
                    "already_existed": True,
                    "local_final": True,
                    "text": local_text,
                    "local_model": "pending-action-manager",
                }
                return ToolExecutionResult(
                    tool_name=tool_name, ok=True, message=local_text,
                    updated_parameters=[], raw_result=result,
                )

            created = manager.create_pending_action(
                action_type="file",
                risk_level="critical",
                summary=f"Aplicar unified diff en {path}",
                payload=unified_payload,
                trace_id=trace_id,
            )

            display_message = (
                f"Acción pendiente creada: {created.summary}\n\n"
                f"Diff propuesto:\n```diff\n{diff_display}```\n\n"
                f"Confirma con: `{created.confirmation_phrase}`"
            )

            result = {
                "success": True,
                "message": display_message,
                "action_id": created.id,
                "confirmation_phrase": created.confirmation_phrase,
                "summary": created.summary,
                "diff": diff_display,
                "diff_truncated": diff_truncated,
                "local_final": True,
                "text": display_message,
                "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name, ok=True, message=display_message,
                updated_parameters=[], raw_result=result,
            )

        if tool_name == "apply_multi_file_unified_diff_plan":
            diff_text = str(tool_input.get("diff", ""))

            split_result = execute_file_action({
                "action": "split_unified_diff_by_file",
                "diff": diff_text,
            })

            if not split_result.get("ok"):
                if split_result.get("rejected_entire_plan"):
                    closed_text = (
                        "Plan multiarchivo rechazado completo. "
                        "No he creado ninguna acción pendiente ni modificado ningún archivo. "
                        "Si quieres aplicar solo la parte permitida, envía un patch nuevo sin los archivos bloqueados."
                    )
                    return ToolExecutionResult(
                        tool_name=tool_name, ok=False, message=closed_text,
                        updated_parameters=[], raw_result={
                            "success": False,
                            "message": closed_text,
                            "error": split_result.get("error"),
                            "rejected_entire_plan": True,
                            "local_final": True,
                            "text": closed_text,
                            "local_model": "multi-file-plan-manager",
                        },
                    )

                msg = split_result.get("error", "Error separando diff multiarchivo")
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={
                        "success": False, "message": msg,
                        "local_final": True, "text": msg, "local_model": "multi-file-plan-manager",
                    },
                )

            items = split_result.get("items") or []

            if not items:
                msg = "No hay cambios aplicables en el diff multiarchivo."
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={
                        "success": False, "message": msg,
                        "local_final": True, "text": msg, "local_model": "multi-file-plan-manager",
                    },
                )

            manager = ConfirmationManager(self.session)
            created_actions = []

            for item in items:
                path = str(item.get("path", "archivo desconocido"))
                file_diff = str(item.get("diff", ""))
                preview_diff = str(item.get("preview_diff", ""))
                diff_display = preview_diff[:2000] + ("\n... diff truncado ..." if len(preview_diff) > 2000 else "")

                unified_payload = {
                    "action": "apply_unified_diff",
                    "diff": file_diff,
                }

                existing = manager.find_equivalent_pending_action(
                    action_type="file",
                    payload=unified_payload,
                )

                if existing:
                    created_actions.append({
                        "path": path,
                        "action_id": existing.id,
                        "confirmation_phrase": existing.confirmation_phrase,
                        "already_existed": True,
                    })
                    continue

                created = manager.create_pending_action(
                    action_type="file",
                    risk_level="critical",
                    summary=f"Aplicar unified diff en {path}",
                    payload=unified_payload,
                    trace_id=trace_id,
                )
                created_actions.append({
                    "path": path,
                    "action_id": created.id,
                    "confirmation_phrase": created.confirmation_phrase,
                    "diff_preview": diff_display,
                    "already_existed": False,
                })

            lines = [
                f"Plan multiarchivo creado: {len(created_actions)} acciones pendientes.",
                "",
            ]
            for index, entry in enumerate(created_actions, start=1):
                existed = entry.get("already_existed", False)
                lines.append(f"{index}. {entry['path']}{' (ya existía)' if existed else ''}")
                lines.append(f"   Confirma con: `{entry['confirmation_phrase']}`")

            lines += [
                "",
                "Confirma cada acción por separado.",
                "No se ha modificado ningún archivo todavía.",
            ]

            display_message = "\n".join(lines)

            result = {
                "success": True,
                "message": display_message,
                "pending_actions": created_actions,
                "local_final": True,
                "text": display_message,
                "local_model": "multi-file-plan-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name, ok=True, message=display_message,
                updated_parameters=[], raw_result=result,
            )

        if tool_name == "rollback_latest_file_change":
            lookup = execute_file_action({
                "action": "find_latest_reversible_file_change",
                "include_rollbacks": bool(tool_input.get("include_rollbacks", False)),
            })

            if not lookup.get("ok"):
                msg = lookup.get("error", "No se encontró ningún cambio reversible.")
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={
                        "success": False, "message": msg,
                        "local_final": True, "text": f"No encontré ningún cambio reversible: {msg}", "local_model": "tool-policy",
                    },
                )

            event = lookup.get("event") or {}
            backup_path = str(lookup.get("backup_path", ""))
            target_path = str(event.get("path", "archivo desconocido"))
            source_action = str(event.get("action", "cambio desconocido"))
            source_trace = str(event.get("trace_id", ""))
            source_pending = str(event.get("pending_action_id", ""))

            from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
            try:
                assert_write_allowed(_resolve_path(target_path))
            except FileAccessError as exc:
                err = str(exc)
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=err,
                    updated_parameters=[], raw_result={
                        "success": False, "message": err,
                        "local_final": True, "text": f"No puedo revertir ese archivo: {err}", "local_model": "tool-policy",
                    },
                )

            rollback_payload = {
                "action": "rollback_file_change",
                "backup_path": backup_path,
            }
            manager = ConfirmationManager(self.session)
            existing = manager.find_equivalent_pending_action(
                action_type="file",
                payload=rollback_payload,
            )
            if existing:
                local_text = (
                    f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
                    f"Confirma con: `{existing.confirmation_phrase}`"
                )
                result = {
                    "success": True,
                    "message": local_text,
                    "action_id": existing.id,
                    "confirmation_phrase": existing.confirmation_phrase,
                    "summary": existing.summary,
                    "already_existed": True,
                    "local_final": True,
                    "text": local_text,
                    "local_model": "pending-action-manager",
                }
                return ToolExecutionResult(
                    tool_name=tool_name, ok=True, message=local_text,
                    updated_parameters=[], raw_result=result,
                )

            created = manager.create_pending_action(
                action_type="file",
                risk_level="critical",
                summary=f"Revertir último cambio de archivo: {target_path}",
                payload=rollback_payload,
                trace_id=trace_id,
            )
            display_message = (
                f"Acción pendiente creada: {created.summary}\n\n"
                f"Archivo: {target_path}\n"
                f"Acción original: {source_action}\n"
                f"Trace original: {source_trace}\n"
                f"Pending action original: {source_pending}\n"
                f"Backup: {backup_path}\n\n"
                "Antes de restaurar, Sity creará un backup del estado actual.\n\n"
                f"Confirma con: `{created.confirmation_phrase}`"
            )
            result = {
                "success": True,
                "message": display_message,
                "action_id": created.id,
                "confirmation_phrase": created.confirmation_phrase,
                "summary": created.summary,
                "local_final": True,
                "text": display_message,
                "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name, ok=True, message=display_message,
                updated_parameters=[], raw_result=result,
            )

        if tool_name == "rollback_file_change":
            backup_path = str(tool_input.get("backup_path", ""))

            from app.system_agent.file_access import FileAccessError, _resolve_path, assert_write_allowed
            from app.system_agent.file_audit import find_audit_event_by_backup_path, _resolve_backup_path
            try:
                source_event = find_audit_event_by_backup_path(backup_path)
                if not source_event:
                    msg = "No se encontró ningún evento de auditoría asociado a ese backup."
                    return ToolExecutionResult(
                        tool_name=tool_name, ok=False, message=msg,
                        updated_parameters=[], raw_result={
                            "success": False, "message": msg,
                            "local_final": True, "text": msg, "local_model": "tool-policy",
                        },
                    )
                target_path = str(source_event.get("path", ""))
                assert_write_allowed(_resolve_path(target_path))
            except FileAccessError as exc:
                err = str(exc)
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=err,
                    updated_parameters=[], raw_result={
                        "success": False, "message": err,
                        "local_final": True, "text": err, "local_model": "tool-policy",
                    },
                )
            except Exception as exc:
                err = str(exc)
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=err,
                    updated_parameters=[], raw_result={
                        "success": False, "message": err,
                        "local_final": True, "text": err, "local_model": "tool-policy",
                    },
                )

            rollback_payload = {
                "action": "rollback_file_change",
                "backup_path": backup_path,
            }
            manager = ConfirmationManager(self.session)
            existing = manager.find_equivalent_pending_action(
                action_type="file",
                payload=rollback_payload,
            )
            if existing:
                local_text = (
                    f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
                    f"Confirma con: `{existing.confirmation_phrase}`"
                )
                result = {
                    "success": True,
                    "message": local_text,
                    "action_id": existing.id,
                    "confirmation_phrase": existing.confirmation_phrase,
                    "summary": existing.summary,
                    "already_existed": True,
                    "local_final": True,
                    "text": local_text,
                    "local_model": "pending-action-manager",
                }
                return ToolExecutionResult(
                    tool_name=tool_name, ok=True, message=local_text,
                    updated_parameters=[], raw_result=result,
                )

            created = manager.create_pending_action(
                action_type="file",
                risk_level="critical",
                summary=f"Restaurar {target_path} desde backup",
                payload=rollback_payload,
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
                "confirmation_phrase": created.confirmation_phrase,
                "summary": created.summary,
                "local_final": True,
                "text": local_text,
                "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name, ok=True, message=local_text,
                updated_parameters=[], raw_result=result,
            )

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

        if tool_name == "list_camera_devices":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=list_camera_devices(),
            )

        if tool_name == "list_audio_devices":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=list_audio_devices(),
            )

        if tool_name == "capture_camera_snapshot":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=execute_sense_action({
                    "action": "capture_camera_snapshot",
                    "device": str(tool_input.get("device", "/dev/video0")),
                    "width": int(tool_input.get("width", 1280)),
                    "height": int(tool_input.get("height", 720)),
                    "skip_frames": int(tool_input.get("skip_frames", 20)),
                    "client_turn_id": client_turn_id,
                }),
            )

        if tool_name == "record_audio_sample":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=execute_sense_action({
                    "action": "record_audio_sample",
                    "duration_seconds": int(tool_input.get("duration_seconds", 3)),
                    "device": str(tool_input.get("device", "plughw:CARD=webcam,DEV=0")),
                    "client_turn_id": client_turn_id,
                }),
            )

        if tool_name == "get_capture_storage_summary":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=execute_capture_retention_action({"action": "get_capture_storage_summary"}),
            )

        if tool_name == "clean_old_captures":
            return self._simple_read_tool(
                tool_name=tool_name,
                trace_id=trace_id,
                result=execute_capture_retention_action({
                    "action": "clean_old_captures",
                    "older_than_days": int(tool_input.get("older_than_days", 7)),
                    "max_files_per_type": int(tool_input.get("max_files_per_type", 100)),
                    "dry_run": bool(tool_input.get("dry_run", False)),
                }),
            )

        if tool_name == "cancel_pending_action":
            return self._cancel_pending_action(
                tool_input=tool_input,
                trace_id=trace_id,
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

        if tool_name == "git_propose_action":
            return self._git_propose_action(
                tool_input=tool_input,
                trace_id=trace_id,
            )

        if tool_name in {"restart_service", "start_service", "stop_service"}:
            return self._system_propose_action(
                tool_input={
                    "action": tool_name,
                    "service_name": str(tool_input.get("service_name", "")).strip(),
                    "risk_level": "safe",
                    "summary": f"{tool_name} {tool_input.get('service_name', '')}",
                },
                trace_id=trace_id,
            )

        if tool_name in {"add_allowed_service", "remove_allowed_service"}:
            service_name = str(tool_input.get("service_name", "")).strip()
            if not service_name or not all(c.isalnum() or c in "@_.-" for c in service_name):
                msg = f"Nombre de servicio inválido: {service_name!r}"
                return ToolExecutionResult(
                    tool_name=tool_name, ok=False, message=msg,
                    updated_parameters=[], raw_result={
                        "success": False, "message": msg,
                        "local_final": True, "text": msg, "local_model": "tool-policy",
                    },
                )
            verb = "Añadir" if tool_name == "add_allowed_service" else "Quitar"
            action_key = tool_name
            created = ConfirmationManager(self.session).create_pending_action(
                action_type="system_config",
                risk_level="critical",
                summary=f"{verb} {service_name} {'a' if tool_name == 'add_allowed_service' else 'de'} servicios permitidos",
                payload={"action": action_key, "service_name": service_name},
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
                "confirmation_phrase": created.confirmation_phrase,
                "summary": created.summary,
                "local_final": True,
                "text": local_text,
                "local_model": "pending-action-manager",
            }
            return ToolExecutionResult(
                tool_name=tool_name, ok=True, message=local_text,
                updated_parameters=[], raw_result=result,
            )

        if tool_name == "list_allowed_services":
            from app.actions.system_config_actions import execute_system_config_action
            raw = execute_system_config_action({"action": "list_allowed_services"})
            return self._simple_read_tool(tool_name=tool_name, trace_id=trace_id, result=raw)

        if tool_name == "system_propose_action":
            return self._system_propose_action(
                tool_input=tool_input,
                trace_id=trace_id,
            )

        if tool_name == "update_personality_settings":
            return self._update_personality_settings(
                tool_input=tool_input,
                trace_id=trace_id,
            )

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
        allowed_services = {"sity-backend", "sity-frontend"}

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

    def _cancel_pending_action(
        self,
        *,
        tool_input: dict[str, Any],
        trace_id: str,
    ) -> ToolExecutionResult:
        action_id = str(tool_input.get("action_id", "")).strip().lower()
        reason = str(tool_input.get("reason", "")).strip()

        manager = ConfirmationManager(self.session)

        if action_id:
            action = manager.find_action_by_id(action_id)
        else:
            active = manager._get_active_pending_actions()
            action = active[-1] if active else None

        if not action or action.status != "pending":
            msg = "No encontré ninguna acción pendiente activa para cancelar."
            result = {
                "ok": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            }
            return ToolExecutionResult(
                tool_name="cancel_pending_action",
                ok=False,
                message=msg,
                updated_parameters=[],
                raw_result=result,
            )

        action.status = "cancelled"
        self.session.add(action)
        self.session.commit()

        write_log(
            level="AUDIT",
            module="tools",
            event="pending_action_cancelled",
            trace_id=trace_id,
            payload={
                "action_id": action.id,
                "action_type": action.action_type,
                "reason": reason,
            },
            audit=True,
        )

        cancel_text = f"Acción {action.id} cancelada."
        result = {
            "ok": True,
            "message": cancel_text,
            "action_id": action.id,
            "summary": action.summary,
            "local_final": True,
            "text": cancel_text,
            "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name="cancel_pending_action",
            ok=True,
            message=cancel_text,
            updated_parameters=[],
            raw_result=result,
        )

    def _build_success_message(self, applied_updates: list[dict[str, Any]]) -> str:
        if len(applied_updates) == 1:
            update = applied_updates[0]
            parameter = update["parameter"]
            new_pct = round(float(update["new_value"]) * 100)
            return f"{parameter} actualizado al {new_pct}%."

        return f"Actualizados {len(applied_updates)} parámetros de personalidad."

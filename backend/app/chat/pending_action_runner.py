from __future__ import annotations

import json
from dataclasses import dataclass

from app.actions.confirmation_manager import ConfirmationManager
from app.actions.file_actions import execute_file_action
from app.actions.git_actions import execute_git_action
from app.actions.git_actions import parse_payload as parse_git_payload
from app.actions.google_actions import execute_google_action
from app.actions.google_actions import parse_payload as parse_google_payload
from app.actions.ha_actions import execute_ha_action
from app.actions.ha_actions import parse_payload as parse_ha_payload
from app.actions.sense_actions import execute_sense_action
from app.actions.sense_actions import parse_payload as parse_sense_payload
from app.actions.system_actions import execute_system_action
from app.actions.system_actions import parse_payload as parse_system_payload
from app.actions.system_config_actions import (
    execute_system_config_action,
    parse_payload as parse_system_config_payload,
)
from app.api.schemas import ChatArtifact, ChatMessageResponse, UsageSummary
from app.audio.tts_service import maybe_attach_tts
from app.chat.artifacts import capture_artifact_from_path
from app.chat.local_flow import LocalFlowContext
from app.core.language import resolve_lang
from app.core.system_messages import t
from app.memory.models import ChatMessage, PendingAction
from sqlmodel import select


@dataclass
class _ActionResult:
    text: str
    artifact: ChatArtifact | None = None
    was_executed: bool = False


class PendingActionRunner:
    def __init__(self, confirmation_manager: ConfirmationManager):
        self.cm = confirmation_manager

    def run(self, pending_action: PendingAction, ctx: LocalFlowContext) -> ChatMessageResponse:
        lang = resolve_lang(ctx.language_override)
        result = self._execute(pending_action, ctx.trace_id, lang)

        if result.was_executed:
            from app.achievements.triggers.inline import fire as _fire_ach
            _fire_ach(ctx.session, self.cm._session_id, "would_you_kindly")

        ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
        ctx.save_message(role="sity", text=result.text, trace_id=ctx.trace_id)

        daily_used = ctx.get_usage(ctx.session)
        daily_ratio = daily_used / ctx.daily_budget if ctx.daily_budget > 0 else 0.0

        response = ChatMessageResponse(
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

        tts_result = maybe_attach_tts(
            text=result.text,
            session=ctx.session,
            session_id=self.cm._session_id,
            trace_id=ctx.trace_id,
            result=response,
            language_override=ctx.language_override,
        )
        if tts_result is not None:
            n_fragments, audio_filename = tts_result
            tts_row = ctx.session.exec(
                select(ChatMessage).where(
                    ChatMessage.trace_id == ctx.trace_id,
                    ChatMessage.role == "sity",
                )
            ).first()
            if tts_row is not None:
                tts_row.tts_fragments = n_fragments
                tts_row.audio_filename = audio_filename
                ctx.session.add(tts_row)
                ctx.session.commit()

        return response

    def _execute(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        if action.action_type == "git":
            return self._run_git(action, trace_id, lang)
        if action.action_type == "system":
            return self._run_system(action, trace_id, lang)
        if action.action_type == "system_config":
            return self._run_system_config(action, trace_id, lang)
        if action.action_type == "file":
            return self._run_file(action, trace_id, lang)
        if action.action_type == "sense":
            return self._run_sense(action, trace_id, lang)
        if action.action_type == "google":
            return self._run_google(action, trace_id, lang)
        if action.action_type == "ha":
            return self._run_ha(action, trace_id, lang)
        return _ActionResult(text=t("action_unknown_type", lang, action_type=action.action_type))

    def _run_git(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        try:
            payload = parse_git_payload(action.payload_json)
            result = execute_git_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                no_output = t("no_output", lang)
                lines = [t("action_executed", lang, summary=action.summary)]
                if result.get("pre_command"):
                    cmd_str = ' '.join(str(x) for x in result['pre_command'])
                    lines.append(t("action_pre_command", lang, cmd=cmd_str))
                    pre_out = result.get("pre_stdout", "").strip()
                    if pre_out:
                        lines.append(t("action_pre_stdout", lang, out=pre_out))
                cmd_str = ' '.join(str(x) for x in result.get('command', []))
                lines.append(t("action_command", lang, cmd=cmd_str))
                lines.append(t("action_stdout", lang, stdout=result.get('stdout', '') or no_output))
                return _ActionResult(text="\n".join(lines), was_executed=True)
            else:
                error = result.get("stderr") or t("unknown_error", lang)
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=t("action_exec_failed", lang, action_id=action.id, error=error)
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("action_exec_exception", lang, action_id=action.id, exc=str(exc)))

    def _run_system(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        try:
            payload = parse_system_payload(action.payload_json)
            result = execute_system_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                no_output = t("no_output", lang)
                cmd_str = ' '.join(str(x) for x in result.get('command', []))
                stdout = result.get('stdout', '') or no_output
                text = (
                    t("action_executed", lang, summary=action.summary) + "\n\n"
                    + t("action_command", lang, cmd=cmd_str).lstrip() + "\n"
                    + t("action_stdout", lang, stdout=stdout)
                )
                if result.get("post_status"):
                    text += t("sys_post_status", lang, status=result['post_status'])
                return _ActionResult(text=text, was_executed=True)
            else:
                error = (
                    result.get("stderr")
                    or result.get("stdout")
                    or t("sys_no_confirm", lang, post_status=result.get('post_status', t("unknown_error", lang)))
                )
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=t("action_exec_failed", lang, action_id=action.id, error=error)
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("action_exec_exception", lang, action_id=action.id, exc=str(exc)))

    def _run_system_config(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        try:
            payload = parse_system_config_payload(action.payload_json)
            result = execute_system_config_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                return _ActionResult(
                    text=(
                        t("action_executed", lang, summary=action.summary) + "\n\n"
                        + result.get('message', t("config_updated", lang))
                    ),
                    was_executed=True,
                )
            else:
                error = result.get("stderr") or t("unknown_error", lang)
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=t("action_exec_failed", lang, action_id=action.id, error=error)
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("action_exec_exception", lang, action_id=action.id, exc=str(exc)))

    def _run_file(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
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
                    text = t("file_diff_applied", lang, path=path)
                elif file_action == "rollback_file_change":
                    backup = result.get("restored_from_backup_path", "")
                    text = t("file_rollback_applied", lang, path=path, backup=backup)
                elif file_action == "apply_text_patch":
                    text = t("file_patch_applied", lang, path=path)
                elif file_action == "write_file":
                    key = "file_created" if result.get("created", True) else "file_overwritten"
                    text = t(key, lang, path=path)
                else:
                    text = t("file_action_executed", lang, path=path)
                return _ActionResult(text=text, was_executed=True)
            else:
                error = result.get("error") or t("unknown_error", lang)
                self.cm.mark_failed(action, trace_id, error)
                if file_action == "apply_unified_diff":
                    text = t("file_diff_failed", lang, error=error)
                elif file_action == "rollback_file_change":
                    text = t("file_rollback_failed", lang, error=error)
                elif file_action == "apply_text_patch":
                    text = t("file_patch_failed", lang, error=error)
                else:
                    text = t("file_write_failed", lang, error=error)
                return _ActionResult(text=text)
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("file_action_exception", lang, exc=str(exc)))

    def _run_sense(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        try:
            payload = parse_sense_payload(action.payload_json)
            result = execute_sense_action(payload)
            if result.get("ok"):
                self.cm.mark_executed(action, trace_id)
                artifact = capture_artifact_from_path(str(result.get("path", "")))
                return _ActionResult(
                    text=t("sense_done", lang, summary=action.summary),
                    artifact=artifact,
                    was_executed=True,
                )
            else:
                error = result.get("stderr") or result.get("stdout") or t("unknown_error", lang)
                self.cm.mark_failed(action, trace_id, error)
                return _ActionResult(
                    text=t("action_exec_failed", lang, action_id=action.id, error=error)
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("action_exec_exception", lang, action_id=action.id, exc=str(exc)))

    def _run_ha(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        try:
            payload = parse_ha_payload(action.payload_json)
            result = execute_ha_action(payload)
            if result.ok:
                self.cm.mark_executed(action, trace_id)
                return _ActionResult(text=result.text, was_executed=True)
            else:
                self.cm.mark_failed(action, trace_id, result.text)
                return _ActionResult(
                    text=t("action_exec_failed", lang, action_id=action.id, error=result.text)
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("action_exec_exception", lang, action_id=action.id, exc=str(exc)))

    def _run_google(self, action: PendingAction, trace_id: str, lang: str) -> _ActionResult:
        try:
            payload = parse_google_payload(action.payload_json)
            sid: str = self.cm._session_id
            user_id: int | None = None
            if sid.startswith("user:"):
                try:
                    user_id = int(sid.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass
            result = execute_google_action(payload, user_id=user_id, session=self.cm.session)
            if result.ok:
                self.cm.mark_executed(action, trace_id)
                return _ActionResult(text=result.text, was_executed=True)
            else:
                self.cm.mark_failed(action, trace_id, result.text)
                return _ActionResult(
                    text=t("action_exec_failed", lang, action_id=action.id, error=result.text)
                )
        except Exception as exc:
            self.cm.mark_failed(action, trace_id, str(exc))
            return _ActionResult(text=t("action_exec_exception", lang, action_id=action.id, exc=str(exc)))

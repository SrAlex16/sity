from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Union

from sqlmodel import Session

from app.actions.confirmation_manager import ConfirmationManager
from app.api.schemas import ChatMessageResponse, UsageSummary
from app.chat.model_router import LocalFlowSignal, clear_proposal, get_proposal
from app.core.language import resolve_lang
from app.core.system_messages import t

log = logging.getLogger(__name__)


@dataclass
class LocalFlowContext:
    session: Session
    trace_id: str
    message: str
    daily_budget: int
    warnings: list[str]
    save_message: Callable[..., None]
    get_usage: Callable[[Session], int]
    language_override: str = field(default="auto")


class ChatLocalFlow:
    def __init__(self, confirmation_manager: ConfirmationManager):
        self.confirmation_manager = confirmation_manager

    def try_handle(
        self, ctx: LocalFlowContext
    ) -> Union[ChatMessageResponse, LocalFlowSignal, None]:
        proposal = get_proposal()
        log.info(
            "model_router_check trace_id=%s proposal_active=%s msg=%r",
            ctx.trace_id, proposal is not None, ctx.message[:60],
        )
        if proposal and not proposal.is_expired():
            msg_lower = ctx.message.strip().lower()
            affirmative = {"sí", "si", "vale", "ok", "adelante", "sí, úsalo", "usa sonnet"}
            negative = {"no", "no gracias", "usa haiku", "quédate en haiku", "no hace falta"}
            is_affirmative = any(msg_lower.startswith(w) for w in affirmative)
            is_negative = any(msg_lower.startswith(w) for w in negative)
            log.info(
                "model_router_response trace_id=%s msg_lower=%r is_affirmative=%s is_negative=%s",
                ctx.trace_id, msg_lower, is_affirmative, is_negative,
            )
            if is_affirmative:
                ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
                clear_proposal()
                return LocalFlowSignal(
                    kind="model_upgrade_accepted",
                    original_message=proposal.original_message,
                    strong_model=proposal.strong_model,
                    selected_tools=proposal.selected_tools,
                )
            elif is_negative:
                ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
                clear_proposal()
                return LocalFlowSignal(
                    kind="model_upgrade_rejected",
                    original_message=proposal.original_message,
                    strong_model=proposal.strong_model,
                    selected_tools=proposal.selected_tools,
                )
            else:
                clear_proposal()

        response = self._handle_referenced_action_id(ctx)
        if response:
            return response

        response = self._handle_pending_confirmation(ctx)
        if response:
            return response

        return None

    def _response(
        self,
        *,
        ctx: LocalFlowContext,
        text: str,
        model: str = "confirmation-manager",
        artifacts: list[Any] | None = None,
    ) -> ChatMessageResponse:
        ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
        ctx.save_message(role="sity", text=text, trace_id=ctx.trace_id)

        daily_used = ctx.get_usage(ctx.session)
        daily_ratio = daily_used / ctx.daily_budget if ctx.daily_budget > 0 else 0.0

        return ChatMessageResponse(
            ok=True,
            trace_id=ctx.trace_id,
            text=text,
            provider="local",
            model=model,
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
            artifacts=artifacts or [],
        )

    def _handle_referenced_action_id(self, ctx: LocalFlowContext) -> ChatMessageResponse | None:
        referenced_action_id = self.confirmation_manager.extract_action_id_from_message(ctx.message)

        if not referenced_action_id:
            return None

        referenced_action = self.confirmation_manager.find_action_by_id(referenced_action_id)
        lang = resolve_lang(ctx.language_override)

        if referenced_action and referenced_action.status == "pending":
            normalized = ctx.message.strip().lower()
            expected = referenced_action.confirmation_phrase.strip().lower()

            if normalized == expected:
                return None

            if self.confirmation_manager.message_starts_with_confirmation_prefix(ctx.message):
                text = t(
                    "action_id_exact_needed", lang,
                    action_id=referenced_action_id,
                    phrase=referenced_action.confirmation_phrase,
                )
                return self._response(ctx=ctx, text=text)

            return None

        if referenced_action and referenced_action.status != "pending":
            text = t(
                "action_not_pending", lang,
                action_id=referenced_action_id,
                status=referenced_action.status,
            )
            if referenced_action.status == "executed":
                text += t("action_already_executed", lang)
            elif referenced_action.status == "expired":
                text += t("action_expired", lang)
            elif referenced_action.status == "failed":
                text += t("action_previously_failed", lang)

            return self._response(ctx=ctx, text=text)

        if not referenced_action:
            text = t("action_not_found", lang, action_id=referenced_action_id)
            return self._response(ctx=ctx, text=text)

        return None

    def _handle_pending_confirmation(self, ctx: LocalFlowContext) -> ChatMessageResponse | None:
        pending_action = self.confirmation_manager.find_pending_action_by_confirmation(ctx.message)

        if pending_action:
            return None

        lang = resolve_lang(ctx.language_override)

        if (
            self.confirmation_manager.has_multiple_active_pending_actions()
            and self.confirmation_manager.is_generic_confirmation_message(ctx.message)
        ):
            return self._response(ctx=ctx, text=t("multiple_pending_actions", lang))

        pending_action = self.confirmation_manager.find_pending_action_by_context(ctx.message)

        if pending_action:
            return None

        if self.confirmation_manager.is_generic_confirmation_message(ctx.message):
            latest = self.confirmation_manager.get_latest_active_pending_action()
            if latest:
                text = t(
                    "ambiguous_confirmation", lang,
                    summary=latest.summary,
                    phrase=latest.confirmation_phrase,
                )
                return self._response(ctx=ctx, text=text)

            # No pending action exists → this is just casual conversation ("ok", "vale", "si").
            # Do NOT intercept. Fall through to normal chat so the message reaches the AI.
            return None

        return None

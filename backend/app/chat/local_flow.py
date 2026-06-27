from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Union

from sqlmodel import Session

from app.actions.confirmation_manager import ConfirmationManager
from app.api.schemas import ChatMessageResponse, UsageSummary
from app.chat.model_router import LocalFlowSignal, clear_proposal, get_proposal


@dataclass
class LocalFlowContext:
    session: Session
    trace_id: str
    message: str
    daily_budget: int
    warnings: list[str]
    save_message: Callable[..., None]
    get_usage: Callable[[Session], int]


class ChatLocalFlow:
    def __init__(self, confirmation_manager: ConfirmationManager):
        self.confirmation_manager = confirmation_manager

    def try_handle(
        self, ctx: LocalFlowContext
    ) -> Union[ChatMessageResponse, LocalFlowSignal, None]:
        proposal = get_proposal()
        if proposal and not proposal.is_expired():
            msg_lower = ctx.message.strip().lower()
            affirmative = {"sí", "si", "vale", "ok", "adelante", "sí, úsalo", "usa sonnet"}
            negative = {"no", "no gracias", "usa haiku", "quédate en haiku", "no hace falta"}
            if any(msg_lower.startswith(w) for w in affirmative):
                clear_proposal()
                return LocalFlowSignal(
                    kind="model_upgrade_accepted",
                    original_message=proposal.original_message,
                    strong_model=proposal.strong_model,
                )
            elif any(msg_lower.startswith(w) for w in negative):
                clear_proposal()
                return self._response(ctx=ctx, text="Vale, lo intento con el modelo actual.")
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

        if referenced_action and referenced_action.status == "pending":
            normalized = ctx.message.strip().lower()
            expected = referenced_action.confirmation_phrase.strip().lower()

            if normalized == expected:
                return None

            if self.confirmation_manager.message_starts_with_confirmation_prefix(ctx.message):
                text = (
                    f"He detectado la acción `{referenced_action_id}`, pero la confirmación debe ser exacta.\n\n"
                    f"Usa: `{referenced_action.confirmation_phrase}`"
                )
                return self._response(ctx=ctx, text=text)

            return None

        if referenced_action and referenced_action.status != "pending":
            text = (
                f"La acción `{referenced_action_id}` no está pendiente; "
                f"su estado actual es `{referenced_action.status}`."
            )

            if referenced_action.status == "executed":
                text += " Ya fue ejecutada, no voy a repetirla."
            elif referenced_action.status == "expired":
                text += " Ya expiró. Crea una acción nueva si todavía quieres hacer eso."
            elif referenced_action.status == "failed":
                text += " Falló anteriormente. Crea una acción nueva si quieres reintentarlo."

            return self._response(ctx=ctx, text=text)

        if not referenced_action:
            text = (
                f"No encuentro ninguna acción con ID `{referenced_action_id}`. "
                "Puede que sea antigua, incorrecta o de otra base de datos."
            )
            return self._response(ctx=ctx, text=text)

        return None

    def _handle_pending_confirmation(self, ctx: LocalFlowContext) -> ChatMessageResponse | None:
        pending_action = self.confirmation_manager.find_pending_action_by_confirmation(ctx.message)

        if pending_action:
            return None

        if (
            self.confirmation_manager.has_multiple_active_pending_actions()
            and self.confirmation_manager.is_generic_confirmation_message(ctx.message)
        ):
            text = (
                "Hay varias acciones pendientes, así que no voy a adivinar cuál quieres ejecutar. "
                "Confirma usando la frase exacta de la acción, tipo `confirmo ejecutar act_xxxxxxxx`."
            )
            return self._response(ctx=ctx, text=text)

        pending_action = self.confirmation_manager.find_pending_action_by_context(ctx.message)

        if pending_action:
            return None

        if self.confirmation_manager.is_generic_confirmation_message(ctx.message):
            latest = self.confirmation_manager.get_latest_active_pending_action()
            if latest:
                text = (
                    f"¿Te refieres a «{latest.summary}»? "
                    f"Usa `{latest.confirmation_phrase}` para confirmar."
                )
                return self._response(ctx=ctx, text=text)

            # No pending action exists → this is just casual conversation ("ok", "vale", "si").
            # Do NOT intercept. Fall through to normal chat so the message reaches the AI.
            return None

        return None

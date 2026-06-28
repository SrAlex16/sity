"""ChatPreAIFlow — early-return flows that run before the AI provider is called.

Groups the three pre-AI gates (local_flow, pending_action, budget_guard) into one
class so that _chat_message_inner can delegate them in a single call. If try_handle
returns None, the caller should proceed to the AI path; runtime_config is always
set on the instance after try_handle returns.
"""
from __future__ import annotations

from sqlmodel import Session

from app.actions.confirmation_manager import ConfirmationManager
from app.api.schemas import ChatMessageRequest, ChatMessageResponse
from app.chat.budget_guard import BudgetGuardContext, ChatBudgetGuard
from app.chat.chat_persistence import get_today_token_usage
from app.chat.local_flow import ChatLocalFlow, LocalFlowContext
from app.chat.model_router import LocalFlowSignal
from app.chat.pending_action_runner import PendingActionRunner
from app.chat.turn_context import TurnContext
from app.core.runtime_config import RuntimeConfig, get_runtime_config


class ChatPreAIFlow:
    def __init__(self, session: Session, ctx: TurnContext) -> None:
        self.session = session
        self.ctx = ctx
        self.confirmation_manager = ConfirmationManager(session)
        self.local_flow = ChatLocalFlow(self.confirmation_manager)
        self.runtime_config: RuntimeConfig = get_runtime_config()

    def try_handle(
        self, request: ChatMessageRequest
    ) -> ChatMessageResponse | LocalFlowSignal | None:
        """Run all pre-AI gates in order; return the first response that handles the turn,
        or None if the caller should proceed to the AI provider path.

        Order:
        1. local_flow  — cancel, generic confirmations, model-router responses
        2. pending_action — explicit confirmation of a queued action
        3. budget_guard   — daily token budget exhausted
        """
        _local_ctx = LocalFlowContext(
            session=self.session,
            trace_id=self.ctx.trace_id,
            message=request.message,
            daily_budget=self.ctx.daily_budget,
            warnings=[],
            save_message=self.ctx.persistence.save,
            get_usage=get_today_token_usage,
        )

        local_response = self.local_flow.try_handle(_local_ctx)
        if local_response:
            return local_response

        pending_action = self.confirmation_manager.find_pending_action_by_confirmation(
            request.message
        )
        if not pending_action:
            pending_action = self.confirmation_manager.find_pending_action_by_context(
                request.message
            )
        if pending_action:
            _par = PendingActionRunner(self.confirmation_manager)
            return _par.run(pending_action, _local_ctx)

        budget_response = ChatBudgetGuard().try_handle(
            BudgetGuardContext(
                session=self.session,
                trace_id=self.ctx.trace_id,
                message=request.message,
                daily_budget=self.ctx.daily_budget,
                runtime_config=self.runtime_config,
                save_message=self.ctx.persistence.save,
                get_usage=get_today_token_usage,
            )
        )
        if budget_response:
            return budget_response

        return None

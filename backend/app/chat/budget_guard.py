from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from sqlmodel import Session

from app.api.schemas import ChatMessageResponse, UsageSummary
from app.core.language import resolve_lang
from app.core.runtime_config import RuntimeConfig
from app.core.system_messages import t


@dataclass
class BudgetGuardContext:
    session: Session
    trace_id: str
    message: str
    daily_budget: int
    runtime_config: RuntimeConfig
    save_message: Callable[..., None]
    get_usage: Callable[[Session], int]
    language_override: str = field(default="auto")


class ChatBudgetGuard:
    def try_handle(self, ctx: BudgetGuardContext) -> ChatMessageResponse | None:
        daily_used = ctx.get_usage(ctx.session)
        lang = resolve_lang(ctx.language_override)

        if ctx.runtime_config.local_only:
            return self._response(
                ctx=ctx,
                text=t("budget_local_only", lang),
                model="local-only-guard",
                daily_used_tokens=daily_used,
            )

        if (
            ctx.runtime_config.daily_token_hard_cap
            and ctx.daily_budget > 0
            and daily_used >= ctx.daily_budget
        ):
            return self._response(
                ctx=ctx,
                text=t("budget_exhausted", lang),
                model="budget-guard",
                daily_used_tokens=daily_used,
            )

        return None

    def _response(
        self,
        *,
        ctx: BudgetGuardContext,
        text: str,
        model: str,
        daily_used_tokens: int,
    ) -> ChatMessageResponse:
        ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
        ctx.save_message(role="sity", text=text, trace_id=ctx.trace_id)

        daily_ratio = round(daily_used_tokens / ctx.daily_budget, 4) if ctx.daily_budget > 0 else 0.0

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
                daily_used_tokens=daily_used_tokens,
                daily_budget_tokens=ctx.daily_budget,
                daily_ratio=daily_ratio,
            ),
            warnings=[],
            personality_updated=False,
            updated_parameter=None,
            updated_parameters=[],
            artifacts=[],
        )

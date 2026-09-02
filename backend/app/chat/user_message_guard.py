"""UserMessageGuard — per-session daily message-count limit.

Runs after local_flow and pending_action in ChatPreAIFlow so that
cancel commands and action confirmations are never blocked.

Admin sessions (is_admin=True) are exempt. Limits are read from
config/default_config.yaml under auth.user_daily_message_limit and
auth.guest_daily_message_limit. Setting either limit to 0 disables it.

Counter resets automatically at midnight without a cron job: a
count_date field stores the ISO date; when the guard sees a different
date it resets the counter before checking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from sqlmodel import Session

from app.api.schemas import ChatMessageResponse, UsageSummary
from app.core.language import resolve_lang
from app.core.system_messages import t
from app.memory.models import DailyMessageUsage
from app.trace.logger import write_log


@dataclass
class UserMessageGuardContext:
    session: Session
    trace_id: str
    session_id: str
    message: str
    is_admin: bool
    user_limit: int
    guest_limit: int
    save_message: Callable[..., None]
    language_override: str = field(default="auto")


class UserMessageGuard:
    def try_handle(self, ctx: UserMessageGuardContext) -> ChatMessageResponse | None:
        if ctx.is_admin:
            return None

        is_guest = ctx.session_id.startswith("guest:")
        limit = ctx.guest_limit if is_guest else ctx.user_limit

        if limit <= 0:
            return None

        today = date.today().isoformat()
        row = ctx.session.get(DailyMessageUsage, ctx.session_id)

        if row is None:
            row = DailyMessageUsage(session_id=ctx.session_id, count=0, count_date=today)
        elif row.count_date != today:
            row.count = 0
            row.count_date = today

        if row.count >= limit:
            write_log(
                level="WARN",
                module="chat",
                event="user_message_limit_reached",
                payload={
                    "session_id": ctx.session_id,
                    "count": row.count,
                    "limit": limit,
                    "role": "guest" if is_guest else "user",
                },
            )
            text = t("msg_limit_reached", resolve_lang(ctx.language_override))
            ctx.save_message(role="user", text=ctx.message, trace_id=ctx.trace_id)
            ctx.save_message(role="sity", text=text, trace_id=ctx.trace_id)
            return ChatMessageResponse(
                ok=True,
                trace_id=ctx.trace_id,
                text=text,
                provider="local",
                model="user-message-guard",
                fallback_used=False,
                error_type=None,
                usage=UsageSummary(
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    daily_used_tokens=0,
                    daily_budget_tokens=0,
                    daily_ratio=0.0,
                ),
                warnings=[],
                personality_updated=False,
                updated_parameter=None,
                updated_parameters=[],
                artifacts=[],
            )

        row.count += 1
        ctx.session.add(row)
        ctx.session.commit()
        return None

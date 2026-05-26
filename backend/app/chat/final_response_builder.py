"""
build_final_ai_response — finalization stage for the AI chat response path.

Covers, in order:
  1. Persist AIUsage row
  2. build_budget_snapshot (fresh token count after persist)
  3. write_log ai_call_completed / ai_call_failed
  4. ResponseGuard (pseudo tool call / content guard)
  5. save_chat_message (sity role)
  6. set_last_refusal if refusal_mode
  7. Return ChatMessageResponse via ai_final_response

Does NOT handle:
  - Tool loop
  - Provider calls
  - Prompts or personality
  - Early returns (local_final, sensor_*)
"""

from __future__ import annotations

from typing import Any, Callable

from sqlmodel import Session

from app.api.schemas import ChatArtifact, ChatMessageResponse
from app.chat.budget_snapshot import build_budget_snapshot
from app.chat.response_factory import ai_final_response
from app.chat.response_guard import ResponseGuard
from app.core.refusal_tracker import set_last_refusal
from app.cortex.schemas import AIResponse
from app.memory.models import AIUsage
from app.trace.logger import write_log


def build_final_ai_response(
    *,
    session: Session,
    trace_id: str,
    response: AIResponse,
    daily_budget: int,
    warning_threshold: float,
    critical_threshold: float,
    get_today_token_usage: Callable[[Session], int],
    save_message: Callable[..., None],
    refusal_mode: bool,
    user_message: str,
    updated_parameters: list[str],
    artifacts: list[ChatArtifact],
) -> ChatMessageResponse:
    # 1. Persist AIUsage row
    usage_row = AIUsage(
        trace_id=trace_id,
        session_id=None,
        provider=response.provider,
        model=response.model,
        task_type="chat_message",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        estimated_cost=0.0,
        latency_ms=response.latency_ms,
        fallback_used=response.fallback_used,
        success=response.ok,
        error_type=response.error_type,
    )
    session.add(usage_row)
    session.commit()

    # 2. Budget snapshot (after persist so daily_used is current)
    snap = build_budget_snapshot(
        daily_used=get_today_token_usage(session),
        daily_budget=daily_budget,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    )

    # 3. Completion log
    write_log(
        level="INFO" if response.ok else "ERROR",
        module="cortex",
        event="ai_call_completed" if response.ok else "ai_call_failed",
        trace_id=trace_id,
        payload={
            "provider": response.provider,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "fallback_used": response.fallback_used,
            "error_type": response.error_type,
            "daily_used_tokens": snap.daily_used,
            "daily_ratio": snap.daily_ratio,
        },
    )

    # 4. ResponseGuard
    guard_result = ResponseGuard().validate_final_text(response.text)
    if not guard_result.allowed:
        write_log(
            level="WARN",
            module="chat",
            event="model_response_blocked",
            trace_id=trace_id,
            payload={"reason": guard_result.reason},
        )
    response.text = guard_result.text

    # 5. Persist assistant message
    save_message(session, role="sity", text=response.text, trace_id=trace_id)

    # 6. Track refusal if applicable
    if refusal_mode:
        set_last_refusal(
            user_message=user_message,
            assistant_message=response.text,
            trace_id=trace_id,
        )

    # 7. Return response
    return ai_final_response(
        trace_id=trace_id,
        response=response,
        daily_used=snap.daily_used,
        daily_budget=snap.daily_budget,
        daily_ratio=snap.daily_ratio,
        warnings=snap.warnings,
        updated_parameters=updated_parameters,
        artifacts=artifacts,
    )

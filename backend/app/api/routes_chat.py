from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.core.persona_engine import PersonaEngine
from app.cortex.ai_gateway import AIGateway
from app.cortex.schemas import AIRequest
from app.memory.db import get_session
from app.memory.models import AIUsage
from app.settings.config_loader import load_default_config
from app.settings.settings_service import SettingsService
from app.trace.logger import new_trace_id, write_log


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    message: str


class UsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    daily_used_tokens: int
    daily_budget_tokens: int
    daily_ratio: float


class ChatMessageResponse(BaseModel):
    ok: bool
    trace_id: str
    text: str
    provider: str
    model: str
    fallback_used: bool
    error_type: Optional[str] = None
    usage: UsageSummary
    warnings: list[str] = []


def get_today_token_usage(session: Session) -> int:
    today = date.today().isoformat()
    rows = session.query(AIUsage).all()

    total = 0
    for row in rows:
        if row.created_at.date().isoformat() == today:
            total += row.input_tokens + row.output_tokens

    return total


@router.post("/message", response_model=ChatMessageResponse)
def chat_message(
    request: ChatMessageRequest,
    session: Session = Depends(get_session),
):
    trace_id = new_trace_id()
    config = load_default_config()
    settings_service = SettingsService(session)
    personality = settings_service.get_personality()

    write_log(
        level="INFO",
        module="chat",
        event="user_message_received",
        trace_id=trace_id,
        payload={
            "message_length": len(request.message),
        },
    )

    persona_prompt = PersonaEngine().build_persona_prompt(personality)

    ai_config = config.get("ai", {})
    usage_config = config.get("usage", {})

    max_tokens = int(ai_config.get("claude", {}).get("max_tokens", 220))
    daily_budget = int(usage_config.get("daily_token_budget", 50000))
    warning_threshold = float(usage_config.get("warning_threshold", 0.80))
    critical_threshold = float(usage_config.get("critical_threshold", 0.95))

    ai_request = AIRequest(
        trace_id=trace_id,
        task_type="chat_message",
        system_prompt=persona_prompt,
        user_message=request.message,
        max_tokens=max_tokens,
    )

    write_log(
        level="INFO",
        module="cortex",
        event="ai_call_started",
        trace_id=trace_id,
        payload={
            "provider": "anthropic",
            "task_type": "chat_message",
            "max_tokens": max_tokens,
        },
    )

    response = AIGateway(config=config).generate(ai_request)

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

    daily_used = get_today_token_usage(session)
    total_tokens = response.usage.input_tokens + response.usage.output_tokens
    daily_ratio = daily_used / daily_budget if daily_budget > 0 else 0.0

    warnings: list[str] = []
    if daily_ratio >= critical_threshold:
        warnings.append(
            f"Uso crítico: has consumido aproximadamente el {round(daily_ratio * 100)}% del presupuesto diario configurado."
        )
    elif daily_ratio >= warning_threshold:
        warnings.append(
            f"Aviso: has consumido aproximadamente el {round(daily_ratio * 100)}% del presupuesto diario configurado."
        )

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
            "daily_used_tokens": daily_used,
            "daily_ratio": daily_ratio,
        },
    )

    return ChatMessageResponse(
        ok=response.ok,
        trace_id=trace_id,
        text=response.text,
        provider=response.provider,
        model=response.model,
        fallback_used=response.fallback_used,
        error_type=response.error_type,
        usage=UsageSummary(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=total_tokens,
            daily_used_tokens=daily_used,
            daily_budget_tokens=daily_budget,
            daily_ratio=round(daily_ratio, 4),
        ),
        warnings=warnings,
    )

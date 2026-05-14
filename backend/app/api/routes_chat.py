from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.persona_engine import PersonaEngine
from app.core.tool_executor import ToolExecutor
from app.cortex.ai_gateway import AIGateway
from app.cortex.schemas import AIRequest
from app.memory.db import get_session
from app.memory.models import AIUsage, ChatMessage, ChatSession, utc_now
from app.settings.config_loader import load_default_config
from app.settings.settings_service import SettingsService
from app.trace.logger import new_trace_id, write_log


router = APIRouter(prefix="/chat", tags=["chat"])

DEFAULT_CHAT_SESSION_ID = "default"


class ChatMessageItem(BaseModel):
    role: str
    text: str
    trace_id: Optional[str] = None


class CurrentChatResponse(BaseModel):
    ok: bool
    session_id: str
    messages: list[ChatMessageItem]


def get_or_create_default_chat_session(session: Session) -> ChatSession:
    chat_session = session.get(ChatSession, DEFAULT_CHAT_SESSION_ID)

    if chat_session:
        return chat_session

    chat_session = ChatSession(id=DEFAULT_CHAT_SESSION_ID)
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    return chat_session


def save_chat_message(
    session: Session,
    *,
    role: str,
    text: str,
    trace_id: Optional[str] = None,
) -> None:
    get_or_create_default_chat_session(session)

    session.add(
        ChatMessage(
            session_id=DEFAULT_CHAT_SESSION_ID,
            role=role,
            text=text,
            trace_id=trace_id,
        )
    )

    chat_session = session.get(ChatSession, DEFAULT_CHAT_SESSION_ID)
    if chat_session:
        chat_session.updated_at = utc_now()
        session.add(chat_session)

    session.commit()


def get_recent_db_messages(session: Session, limit: int = 8) -> list[ChatMessage]:
    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == DEFAULT_CHAT_SESSION_ID)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list(session.exec(statement))
    return list(reversed(rows))


@router.get("/current", response_model=CurrentChatResponse)
def current_chat(session: Session = Depends(get_session)):
    get_or_create_default_chat_session(session)

    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == DEFAULT_CHAT_SESSION_ID)
        .order_by(ChatMessage.id.asc())
        .limit(200)
    )

    messages = [
        ChatMessageItem(
            role=row.role,
            text=row.text,
            trace_id=row.trace_id,
        )
        for row in session.exec(statement)
    ]

    return CurrentChatResponse(
        ok=True,
        session_id=DEFAULT_CHAT_SESSION_ID,
        messages=messages,
    )



class ChatHistoryItem(BaseModel):
    role: str
    text: str


class ChatMessageRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = []


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
    personality_updated: bool = False
    updated_parameter: Optional[str] = None
    updated_parameters: list[str] = []


def get_today_token_usage(session: Session) -> int:
    today = date.today().isoformat()
    rows = session.query(AIUsage).all()

    total = 0
    for row in rows:
        if row.created_at.date().isoformat() == today:
            total += row.input_tokens + row.output_tokens

    return total


def max_tokens_for_verbosity(verbosity_level: float, configured_max_tokens: int) -> int:
    if verbosity_level <= 0.20:
        return min(configured_max_tokens, 140)
    if verbosity_level <= 0.50:
        return min(configured_max_tokens, 190)
    if verbosity_level <= 0.80:
        return min(configured_max_tokens, 260)
    return configured_max_tokens


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
            "history_items": len(request.history),
        },
    )

    updated_parameters: list[str] = []

    persona_decision = PersonaEngine().build_persona_prompt(personality, request.message)
    persona_prompt = persona_decision.system_prompt

    ai_config = config.get("ai", {})
    usage_config = config.get("usage", {})

    configured_max_tokens = int(ai_config.get("claude", {}).get("max_tokens", 300))
    verbosity_level = float(personality.get("verbosity_level", 0.45))
    max_tokens = max_tokens_for_verbosity(
        verbosity_level=verbosity_level,
        configured_max_tokens=configured_max_tokens,
    )
    daily_budget = int(usage_config.get("daily_token_budget", 50000))
    warning_threshold = float(usage_config.get("warning_threshold", 0.80))
    critical_threshold = float(usage_config.get("critical_threshold", 0.95))

    db_history = [
        ChatHistoryItem(role=row.role, text=row.text)
        for row in get_recent_db_messages(session, limit=8)
    ]
    recent_history = request.history[-8:] if request.history else db_history

    history_text = ""
    if recent_history:
        rendered_items: list[str] = []
        for item in recent_history:
            role = "Usuario" if item.role == "user" else "Sity"
            rendered_items.append(f"{role}: {item.text}")
        history_text = "\n".join(rendered_items)

    user_message_with_history = (
        f"Historial reciente de esta conversación:\n{history_text}\n\n"
        f"Mensaje actual del usuario:\n{request.message}"
        if history_text
        else request.message
    )

    ai_request = AIRequest(
        trace_id=trace_id,
        task_type="chat_message",
        system_prompt=persona_prompt,
        user_message=user_message_with_history,
        max_tokens=max_tokens,
    )

    write_log(
        level="INFO",
        module="core",
        event="persona_context_built",
        trace_id=trace_id,
        payload={
            "personality": personality,
            "refusal_mode": persona_decision.refusal_mode,
        },
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
            "verbosity_level": verbosity_level,
        },
    )

    response = AIGateway(config=config).generate(ai_request)

    write_log(
        level="INFO",
        module="cortex",
        event="ai_response_received",
        trace_id=trace_id,
        payload={
            "text_length": len(response.text or ""),
            "tool_calls_count": len(response.tool_calls),
            "tool_calls": [
                {
                    "name": tool_call.name,
                    "input": tool_call.input,
                }
                for tool_call in response.tool_calls
            ],
        },
    )

    tool_results = []

    if response.ok and response.tool_calls:
        executor = ToolExecutor(session)

        for tool_call in response.tool_calls:
            result = executor.execute_tool_call(
                tool_name=tool_call.name,
                tool_input=tool_call.input,
                trace_id=trace_id,
            )

            tool_results.append(
                {
                    "tool_name": result.tool_name,
                    "ok": result.ok,
                    "message": result.message,
                    "updated_parameters": result.updated_parameters,
                }
            )

            if result.ok:
                updated_parameters.extend(result.updated_parameters)

        if updated_parameters:
            personality = settings_service.get_personality()
            persona_decision = PersonaEngine().build_persona_prompt(personality, request.message)

            tool_summary = "\n".join(
                f"- {item['tool_name']}: {item['message']}"
                for item in tool_results
            )

            followup_request = AIRequest(
                trace_id=trace_id,
                task_type="chat_message_tool_confirmation",
                system_prompt=persona_decision.system_prompt,
                user_message=(
                    "El sistema ha ejecutado correctamente estas herramientas reales:\n"
                    f"{tool_summary}\n\n"
                    "Responde al usuario confirmando brevemente los cambios. "
                    "No digas que solo puedes sugerirlos: ya se aplicaron en SQLite."
                ),
                max_tokens=max_tokens,
                tools_enabled=False,
            )

            followup_response = AIGateway(config=config).generate(followup_request)

            response.text = followup_response.text
            response.usage.input_tokens += followup_response.usage.input_tokens
            response.usage.output_tokens += followup_response.usage.output_tokens
            response.latency_ms += followup_response.latency_ms

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

    save_chat_message(
        session,
        role="sity",
        text=response.text,
        trace_id=trace_id,
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
        personality_updated=bool(updated_parameters),
        updated_parameter=updated_parameters[0] if updated_parameters else None,
        updated_parameters=updated_parameters,
    )

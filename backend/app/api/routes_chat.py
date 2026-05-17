import json
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


def get_recent_db_messages(session: Session, limit: int = 20) -> list[ChatMessage]:
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
        return min(configured_max_tokens, 250)
    if verbosity_level <= 0.50:
        return min(configured_max_tokens, 450)
    if verbosity_level <= 0.80:
        return min(configured_max_tokens, 750)
    return min(configured_max_tokens, 1200)


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

    persona_decision = PersonaEngine().build_persona_prompt(personality, request.message)
    persona_prompt = persona_decision.system_prompt

    ai_config = config.get("ai", {})
    usage_config = config.get("usage", {})

    configured_max_tokens = int(ai_config.get("claude", {}).get("max_tokens", 1500))
    verbosity_level = float(personality.get("verbosity_level", 0.45))
    max_tokens = max_tokens_for_verbosity(
        verbosity_level=verbosity_level,
        configured_max_tokens=configured_max_tokens,
    )
    daily_budget = int(usage_config.get("daily_token_budget", 50000))
    warning_threshold = float(usage_config.get("warning_threshold", 0.80))
    critical_threshold = float(usage_config.get("critical_threshold", 0.95))

    recent_history = [
        ChatHistoryItem(role=row.role, text=row.text)
        for row in get_recent_db_messages(session, limit=20)
    ]

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

    save_chat_message(session, role="user", text=request.message, trace_id=trace_id)

    gateway = AIGateway(config=config)

    planner_request = AIRequest(
        trace_id=trace_id,
        task_type="action_planner",
        system_prompt=(
            persona_prompt
            + "\n\nFASE DE PLANIFICACIÓN: debes elegir exactamente una tool. "
            "Si el usuario pide cambiar personalidad, parámetros, sliders, tono, actitud "
            "o comportamiento configurable, usa update_personality_settings. "
            "Si no requiere acción real, usa no_action_required. "
            "No respondas con texto normal en esta fase."
        ),
        user_message=user_message_with_history,
        max_tokens=500,
        tools_enabled=True,
        tool_choice={"type": "any"},
    )

    write_log(
        level="INFO",
        module="cortex",
        event="ai_call_started",
        trace_id=trace_id,
        payload={
            "provider": "anthropic",
            "task_type": "action_planner",
            "max_tokens": 500,
            "verbosity_level": verbosity_level,
        },
    )

    planner_response = gateway.generate(planner_request)

    tool_results_for_claude: list[dict] = []
    updated_parameters: list[str] = []

    write_log(
        level="INFO",
        module="cortex",
        event="ai_response_received",
        trace_id=trace_id,
        payload={
            "text_length": len(planner_response.text or ""),
            "tool_calls_count": len(planner_response.tool_calls),
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                }
                for tc in planner_response.tool_calls
            ],
        },
    )

    response = planner_response

    if planner_response.ok and planner_response.tool_calls:
        first_tool = planner_response.tool_calls[0]

        if first_tool.name == "update_personality_settings":
            executor = ToolExecutor(session)
            result = executor.execute_tool_call(
                tool_name=first_tool.name,
                tool_input=first_tool.input,
                trace_id=trace_id,
            )

            if result.ok:
                updated_parameters.extend(result.updated_parameters)

            tool_results_for_claude.append(
                {
                    "type": "tool_result",
                    "tool_use_id": first_tool.id,
                    "content": json.dumps(result.raw_result, ensure_ascii=False),
                }
            )

            write_log(
                level="INFO",
                module="tools",
                event="tool_results_ready",
                trace_id=trace_id,
                payload={
                    "updated_parameters": updated_parameters,
                    "tool_results_count": len(tool_results_for_claude),
                },
            )

            personality = settings_service.get_personality()
            persona_decision = PersonaEngine().build_persona_prompt(personality, request.message)

            response = gateway.generate_with_tool_results(
                request=AIRequest(
                    trace_id=trace_id,
                    task_type="chat_message_tool_result",
                    system_prompt=persona_decision.system_prompt,
                    user_message=(
                        "El sistema acaba de ejecutar una herramienta real. "
                        "Confirma el resultado en 1 o 2 frases completas. "
                        "No listes todos los parámetros salvo que el usuario lo pida."
                    ),
                    max_tokens=max(max_tokens, 500),
                    tools_enabled=True,
                ),
                first_response_content=[
                    {
                        "type": "tool_use",
                        "id": first_tool.id,
                        "name": first_tool.name,
                        "input": first_tool.input,
                    }
                ],
                tool_results=tool_results_for_claude,
            )

            response.usage.input_tokens += planner_response.usage.input_tokens
            response.usage.output_tokens += planner_response.usage.output_tokens
            response.latency_ms += planner_response.latency_ms

        elif first_tool.name == "no_action_required":
            chat_request = AIRequest(
                trace_id=trace_id,
                task_type="chat_message",
                system_prompt=persona_prompt,
                user_message=user_message_with_history,
                max_tokens=max_tokens,
                tools_enabled=False,
            )
            response = gateway.generate(chat_request)

            response.usage.input_tokens += planner_response.usage.input_tokens
            response.usage.output_tokens += planner_response.usage.output_tokens
            response.latency_ms += planner_response.latency_ms

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

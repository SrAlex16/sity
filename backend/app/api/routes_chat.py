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
from app.cortex.tool_schemas import (
    ALL_TOOLS,
    DEBUG_TOOLSET,
    GIT_TOOLSET,
    PERSONALITY_TOOLSET,
    SYSTEM_TOOLSET,
)
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


def history_limit_for_message(message: str) -> int:
    normalized = message.lower()

    system_keywords = [
        "raspberry",
        "sistema",
        "cpu",
        "ram",
        "disco",
        "procesos",
        "servicio",
        "repo",
        "git",
        "commits",
        "ramas",
        "remotos",
        "logs",
        "traza",
        "debug",
        "tools",
    ]

    if any(keyword in normalized for keyword in system_keywords):
        return 4

    return 20


def select_toolset_for_message(message: str) -> list[dict]:
    normalized = message.lower()

    git_terms = [
        "git", "repo", "repositorio", "commit", "commits",
        "rama", "ramas", "branch", "origin", "pull", "push",
    ]

    system_terms = [
        "raspberry", "sistema", "cpu", "ram", "memoria",
        "disco", "espacio", "procesos", "servicio", "systemd", "ssh",
    ]

    debug_terms = [
        "debug", "log", "logs", "traza", "trace",
        "error", "errores", "tools", "herramientas",
    ]

    personality_terms = [
        "personalidad", "slider", "sliders", "sarcasmo", "calidez",
        "melancolía", "melancolia", "mala leche", "verbosidad",
        "paciencia", "tsundere",
    ]

    if any(term in normalized for term in git_terms):
        return GIT_TOOLSET

    if any(term in normalized for term in system_terms):
        return SYSTEM_TOOLSET

    if any(term in normalized for term in debug_terms):
        return DEBUG_TOOLSET

    if any(term in normalized for term in personality_terms):
        return PERSONALITY_TOOLSET

    return ALL_TOOLS


def detect_fast_read_tool(message: str) -> dict | None:
    normalized = message.lower()

    if "disco" in normalized or "espacio" in normalized:
        return {"name": "read_disk_usage", "input": {"path": "/"}}

    if "raspberry" in normalized and any(x in normalized for x in ["cómo está", "estado", "sistema"]):
        return {"name": "read_system_status", "input": {}}

    if "repo" in normalized or "repositorio" in normalized or "git" in normalized:
        if "commit" in normalized:
            return {"name": "git_read_log", "input": {"repo_path": "sity", "limit": 10}}
        if "rama" in normalized or "branch" in normalized:
            return {"name": "git_read_branches", "input": {"repo_path": "sity"}}
        return {"name": "git_read_status", "input": {"repo_path": "sity"}}

    return None


COMPACT_RESPONSE_PROMPT = (
    "Eres Sity. Responde directamente a la pregunta del usuario usando el resultado de la herramienta. "
    "Sé breve y clara. No inventes datos. No menciones detalles internos salvo que el usuario los pida."
)


def build_action_planner_prompt() -> str:
    return """
Eres el planificador de acciones de Sity.

Debes elegir exactamente una herramienta:
- Usa herramientas de personalidad si el usuario pide cambiar tono, estilo, sliders o parámetros.
- Usa herramientas de debug si pregunta por logs, trazas, errores o tools ejecutadas.
- Usa herramientas de sistema si pregunta por Raspberry, CPU, RAM, disco, procesos, servicios o directorios.
- Usa herramientas Git si pregunta por repos, commits, ramas, remotos, status o diff.
- Usa no_action_required si solo quiere conversar.

No respondas con texto normal en esta fase.
No inventes resultados.
""".strip()


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

    history_limit = history_limit_for_message(request.message)

    recent_history = [
        ChatHistoryItem(role=row.role, text=row.text)
        for row in get_recent_db_messages(session, limit=history_limit)
    ]

    def render_history(items: list[ChatHistoryItem]) -> str:
        return "\n".join(
            f"{'Usuario' if item.role == 'user' else 'Sity'}: {item.text}"
            for item in items
        )

    def with_history(history_text: str) -> str:
        if not history_text:
            return request.message
        return (
            f"Historial reciente de esta conversación:\n{history_text}\n\n"
            f"Mensaje actual del usuario:\n{request.message}"
        )

    user_message_with_history = with_history(render_history(recent_history))

    planner_history = [
        ChatHistoryItem(role=row.role, text=row.text)
        for row in get_recent_db_messages(session, limit=4)
    ]
    planner_user_message = with_history(render_history(planner_history))

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

    fast_tool_call = detect_fast_read_tool(request.message)

    if fast_tool_call:
        fast_result = ToolExecutor(session).execute_tool_call(
            tool_name=fast_tool_call["name"],
            tool_input=fast_tool_call["input"],
            trace_id=trace_id,
        )

        response = gateway.generate(
            AIRequest(
                trace_id=trace_id,
                task_type="fast_read_tool_summary",
                system_prompt=persona_prompt,
                user_message=(
                    f"Pregunta original del usuario:\n{request.message}\n\n"
                    f"Resultado real de la herramienta:\n"
                    f"{json.dumps(fast_result.raw_result, ensure_ascii=False)}\n\n"
                    "Responde de forma breve y clara."
                ),
                max_tokens=max_tokens,
                tools_enabled=False,
            )
        )

        save_chat_message(session, role="sity", text=response.text, trace_id=trace_id)

        daily_used = get_today_token_usage(session)
        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        daily_ratio = daily_used / daily_budget if daily_budget > 0 else 0.0

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
            warnings=[],
            personality_updated=False,
            updated_parameter=None,
            updated_parameters=[],
        )

    selected_tools = select_toolset_for_message(request.message)

    planner_request = AIRequest(
        trace_id=trace_id,
        task_type="action_planner",
        system_prompt=build_action_planner_prompt(),
        user_message=planner_user_message,
        max_tokens=500,
        tools_enabled=True,
        tool_choice={"type": "any"},
        tools=selected_tools,
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

        if first_tool.name == "no_action_required":
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
        else:
            executor = ToolExecutor(session)

            for tool_call in planner_response.tool_calls:
                result = executor.execute_tool_call(
                    tool_name=tool_call.name,
                    tool_input=tool_call.input,
                    trace_id=trace_id,
                )

                if result.ok:
                    updated_parameters.extend(result.updated_parameters)

                tool_results_for_claude.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
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

    if tool_results_for_claude:
        response_after_tools = gateway.generate_with_tool_results(
            request=AIRequest(
                trace_id=trace_id,
                task_type="chat_message_tool_result",
                system_prompt=persona_decision.system_prompt,
                user_message=(
                    "Acabas de recibir el resultado real de una herramienta ejecutada por el backend. "
                    "Responde directamente a la pregunta original del usuario usando ese resultado. "
                    "No digas que no ves resultados previos. "
                    "No preguntes qué herramienta debía resumirse. "
                    "No menciones detalles internos salvo que el usuario pregunte por debug. "
                    "Si la herramienta devolvió datos válidos, da la respuesta final de forma breve y clara."
                ),
                max_tokens=max(max_tokens, 700),
                tools_enabled=False,
                tools=selected_tools,
            ),
            first_response_content=[
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.input,
                }
                for tool_call in response.tool_calls
            ],
            tool_results=tool_results_for_claude,
        )

        response.text = response_after_tools.text
        response.usage.input_tokens += response_after_tools.usage.input_tokens
        response.usage.output_tokens += response_after_tools.usage.output_tokens
        response.latency_ms += response_after_tools.latency_ms
        response.error_type = response_after_tools.error_type
        response.error_message = response_after_tools.error_message

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

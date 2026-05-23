import json
from datetime import datetime, timezone
from typing import Optional


from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.api.schemas import ChatArtifact, ChatHistoryItem, ChatMessageResponse, UsageSummary
from app.chat.prompt_context import PromptContextBuilder
from app.chat.local_flow import ChatLocalFlow, LocalFlowContext
from app.chat.budget_guard import BudgetGuardContext, ChatBudgetGuard
from app.chat.artifacts import capture_artifact_from_path
from app.chat.claude_request_builder import ClaudeRequestBuilder, max_tokens_for_verbosity
from app.chat.response_guard import ResponseGuard
from app.chat.toolset_selector import (
    history_limit_for_message,
    message_mentions_file_path,
    select_toolset_for_message,
)
from app.chat.pending_action_runner import PendingActionRunner

from app.actions.confirmation_manager import ConfirmationManager
from app.core.cancellation import clear_operation, register_operation
from app.core.runtime_config import get_runtime_config
from app.core.realtime_events import publish_event_sync
from app.core.micro_reactions import generate_micro_reaction
from app.core.order_override import has_direct_order_override
from app.core.persona_engine import PersonaEngine
from app.core.refusal_tracker import get_last_refusal, set_last_refusal
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
        .order_by(ChatMessage.id.desc())
        .limit(200)
    )

    rows = list(session.exec(statement))
    rows.reverse()

    messages = [
        ChatMessageItem(
            role=row.role,
            text=row.text,
            trace_id=row.trace_id,
        )
        for row in rows
    ]

    return CurrentChatResponse(
        ok=True,
        session_id=DEFAULT_CHAT_SESSION_ID,
        messages=messages,
    )




class ChatMessageRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = []
    client_turn_id: str | None = None



def get_today_token_usage(session: Session) -> int:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).replace(tzinfo=None)

    result = session.exec(
        select(func.sum(AIUsage.input_tokens + AIUsage.output_tokens)).where(
            AIUsage.created_at >= today_start
        )
    ).one()

    return int(result or 0)

















@router.post("/message", response_model=ChatMessageResponse)
def chat_message(
    request: ChatMessageRequest,
    session: Session = Depends(get_session),
):
    cid = request.client_turn_id
    if cid:
        register_operation(cid)

    try:
        return _chat_message_inner(request=request, session=session)
    except Exception:
        publish_event_sync(cid, {"type": "error", "label": "Error procesando la petición."})
        raise
    finally:
        publish_event_sync(cid, {"type": "done"})
        if cid:
            clear_operation(cid)


def _chat_message_inner(
    *,
    request: ChatMessageRequest,
    session: Session,
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

    if has_direct_order_override(request.message):
        last = get_last_refusal()
        if last:
            persona_prompt += (
                "\n\nCONTEXTO DE OVERRIDE: El usuario está ordenando ejecutar esta petición "
                "que fue rechazada antes por personalidad:\n"
                f"\"{last['user_message']}\"\n\n"
                "Responde a esa petición ahora. Mantén tu personalidad y tono, "
                "pero no rechaces por refusal_mode. La seguridad y las allowlists siguen activas."
            )

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

    confirmation_manager = ConfirmationManager(session)
    local_flow = ChatLocalFlow(confirmation_manager)

    local_response = local_flow.try_handle(
        LocalFlowContext(
            session=session,
            trace_id=trace_id,
            message=request.message,
            daily_budget=daily_budget,
            warnings=[],
            save_message=save_chat_message,
            get_usage=get_today_token_usage,
        )
    )
    if local_response:
        return local_response

    pending_action = confirmation_manager.find_pending_action_by_confirmation(request.message)

    if not pending_action:
        pending_action = confirmation_manager.find_pending_action_by_context(request.message)

    if pending_action:
        runner = PendingActionRunner(confirmation_manager)
        return runner.run(
            pending_action,
            LocalFlowContext(
                session=session,
                trace_id=trace_id,
                message=request.message,
                daily_budget=daily_budget,
                warnings=[],
                save_message=save_chat_message,
                get_usage=get_today_token_usage,
            ),
        )

    runtime_config = get_runtime_config()

    budget_response = ChatBudgetGuard().try_handle(
        BudgetGuardContext(
            session=session,
            trace_id=trace_id,
            message=request.message,
            daily_budget=daily_budget,
            runtime_config=runtime_config,
            save_message=save_chat_message,
            get_usage=get_today_token_usage,
        )
    )
    if budget_response:
        return budget_response

    history_limit = history_limit_for_message(request.message)
    if message_mentions_file_path(request.message):
        history_limit = 2

    prompt_context = PromptContextBuilder(
        get_recent_messages=get_recent_db_messages,
    ).build(
        session=session,
        message=request.message,
        history_limit=history_limit,
        planner_history_limit=4,
    )

    recent_history = prompt_context.recent_history
    planner_history = prompt_context.planner_history
    user_message_with_history = prompt_context.user_message_with_history
    planner_user_message = prompt_context.planner_user_message

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

    selected_tools = select_toolset_for_message(request.message)


    tool_results_for_claude: list[dict] = []
    updated_parameters: list[str] = []
    response_artifacts: list[ChatArtifact] = []
    planner_response = None

    _builder = ClaudeRequestBuilder()

    if not selected_tools:
        response = gateway.generate(
            _builder.chat_request(
                trace_id=trace_id,
                persona_prompt=persona_prompt,
                user_message=user_message_with_history,
                max_tokens=max_tokens,
            )
        )
    else:
        planner_request = _builder.planner_request(
            trace_id=trace_id,
            user_message=planner_user_message,
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

    if planner_response is not None and planner_response.ok and planner_response.tool_calls:
        first_tool = planner_response.tool_calls[0]

        if first_tool.name == "no_action_required":
            response = gateway.generate(
                _builder.chat_request(
                    trace_id=trace_id,
                    persona_prompt=persona_prompt,
                    user_message=user_message_with_history,
                    max_tokens=max_tokens,
                )
            )

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
                    client_turn_id=request.client_turn_id,
                )

                _raw = result.raw_result
                if _raw.get("local_final") and _raw.get("text"):
                    _local_text = str(_raw["text"]).strip()
                    _local_model = str(_raw.get("local_model", "tool-result"))
                    _planner_tokens = planner_response.usage.input_tokens + planner_response.usage.output_tokens

                    _usage_row = AIUsage(
                        trace_id=trace_id,
                        session_id=None,
                        provider=planner_response.provider,
                        model=planner_response.model,
                        task_type="action_planner",
                        input_tokens=planner_response.usage.input_tokens,
                        output_tokens=planner_response.usage.output_tokens,
                        estimated_cost=0.0,
                        latency_ms=planner_response.latency_ms,
                        fallback_used=planner_response.fallback_used,
                        success=planner_response.ok,
                        error_type=planner_response.error_type,
                    )
                    session.add(_usage_row)
                    session.commit()

                    _daily_used = get_today_token_usage(session)
                    _daily_ratio = _daily_used / daily_budget if daily_budget > 0 else 0.0

                    _local_warnings: list[str] = []
                    if _daily_ratio >= critical_threshold:
                        _local_warnings.append(
                            f"Uso crítico: has consumido aproximadamente el {round(_daily_ratio * 100)}% del presupuesto diario configurado."
                        )
                    elif _daily_ratio >= warning_threshold:
                        _local_warnings.append(
                            f"Aviso: has consumido aproximadamente el {round(_daily_ratio * 100)}% del presupuesto diario configurado."
                        )

                    write_log(
                        level="INFO",
                        module="cortex",
                        event="local_tool_response",
                        trace_id=trace_id,
                        payload={"tool": tool_call.name, "model": _local_model},
                    )

                    save_chat_message(session, role="sity", text=_local_text, trace_id=trace_id)

                    return ChatMessageResponse(
                        ok=True,
                        trace_id=trace_id,
                        text=_local_text,
                        provider="local",
                        model=_local_model,
                        fallback_used=False,
                        error_type=None,
                        usage=UsageSummary(
                            input_tokens=planner_response.usage.input_tokens,
                            output_tokens=planner_response.usage.output_tokens,
                            total_tokens=_planner_tokens,
                            daily_used_tokens=_daily_used,
                            daily_budget_tokens=daily_budget,
                            daily_ratio=round(_daily_ratio, 4),
                        ),
                        warnings=_local_warnings,
                        personality_updated=False,
                        updated_parameter=None,
                        updated_parameters=[],
                    )

                _inner = result.raw_result.get("result", {})
                _tool_name = tool_call.name
                _is_sensor = _tool_name in {"record_audio_sample", "capture_camera_snapshot"}
                _personality_dict = personality if isinstance(personality, dict) else {}

                if _inner.get("cancelled"):
                    _event_type = (
                        "audio_recording_cancelled"
                        if "audio" in _tool_name
                        else "camera_capture_cancelled"
                    )
                    _react_text = generate_micro_reaction(
                        ai_client=gateway.provider,
                        event_type=_event_type,
                        event_description="El usuario ha cancelado voluntariamente la operación.",
                        personality=_personality_dict,
                        trace_id=trace_id,
                    )
                    write_log(
                        level="AUDIT",
                        module="senses",
                        event=_event_type,
                        trace_id=trace_id,
                        payload={"tool": _tool_name},
                        audit=True,
                    )
                    save_chat_message(session, role="sity", text=_react_text, trace_id=trace_id)
                    return ChatMessageResponse(
                        ok=True,
                        trace_id=trace_id,
                        text=_react_text,
                        provider="local",
                        model="micro_reaction",
                        fallback_used=False,
                        error_type=None,
                        usage=UsageSummary(
                            input_tokens=0,
                            output_tokens=0,
                            total_tokens=0,
                            daily_used_tokens=get_today_token_usage(session),
                            daily_budget_tokens=daily_budget,
                            daily_ratio=0.0,
                        ),
                        warnings=[],
                        personality_updated=False,
                        updated_parameter=None,
                        updated_parameters=[],
                        artifacts=[],
                    )

                if result.ok and _is_sensor:
                    _event_type = (
                        "audio_recording_finished"
                        if "audio" in _tool_name
                        else "camera_capture_finished"
                    )
                    _react_text = generate_micro_reaction(
                        ai_client=gateway.provider,
                        event_type=_event_type,
                        event_description="La operación de sensor ha completado correctamente.",
                        personality=_personality_dict,
                        trace_id=trace_id,
                    )
                    write_log(
                        level="AUDIT",
                        module="senses",
                        event=_event_type,
                        trace_id=trace_id,
                        payload={"tool": _tool_name},
                        audit=True,
                    )
                    _finished_artifacts: list[ChatArtifact] = []
                    _raw_path = _inner.get("path")
                    if _raw_path:
                        _artifact = capture_artifact_from_path(str(_raw_path))
                        if _artifact:
                            _finished_artifacts.append(_artifact)
                    save_chat_message(session, role="sity", text=_react_text, trace_id=trace_id)
                    return ChatMessageResponse(
                        ok=True,
                        trace_id=trace_id,
                        text=_react_text,
                        provider="local",
                        model="micro_reaction",
                        fallback_used=False,
                        error_type=None,
                        usage=UsageSummary(
                            input_tokens=0,
                            output_tokens=0,
                            total_tokens=0,
                            daily_used_tokens=get_today_token_usage(session),
                            daily_budget_tokens=daily_budget,
                            daily_ratio=0.0,
                        ),
                        warnings=[],
                        personality_updated=False,
                        updated_parameter=None,
                        updated_parameters=[],
                        artifacts=_finished_artifacts,
                    )

                if result.ok:
                    updated_parameters.extend(result.updated_parameters)
                    _raw_path = _inner.get("path")
                    if _raw_path:
                        _artifact = capture_artifact_from_path(str(_raw_path))
                        if _artifact:
                            response_artifacts.append(_artifact)

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
                system_prompt=(
                    persona_decision.system_prompt
                    + "\n\nLa herramienta ya se ha ejecutado. Responde ahora a la petición original del usuario. "
                    "No digas que no ves la pregunta original: está en el historial de esta llamada. "
                    "Si la herramienta no era necesaria o no aporta nada, ignórala y responde conversacionalmente. "
                    "No menciones detalles internos salvo que el usuario pregunte por debug. "
                    "IMPORTANTE: Si el resultado de la herramienta contiene un campo 'diff', muéstralo completo al usuario en un bloque de código con lenguaje diff antes de pedir confirmación. "
                    "Si contiene 'confirmation_phrase', indícala claramente para que el usuario sepa cómo confirmar."
                ),
                user_message=user_message_with_history,
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

    save_chat_message(
        session,
        role="sity",
        text=response.text,
        trace_id=trace_id,
    )

    if persona_decision.refusal_mode:
        set_last_refusal(
            user_message=request.message,
            assistant_message=response.text,
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
        artifacts=response_artifacts,
    )

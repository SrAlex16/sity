import json
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.actions.confirmation_manager import ConfirmationManager
from app.actions.git_actions import execute_git_action
from app.actions.git_actions import parse_payload as parse_git_payload
from app.actions.system_actions import execute_system_action
from app.actions.system_actions import parse_payload as parse_system_payload
from app.system.system_reader import load_system_access_config
from app.actions.system_config_actions import (
    execute_system_config_action,
    list_allowed_services,
    parse_payload as parse_system_config_payload,
)
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


def is_git_mutating_request(message: str) -> bool:
    normalized = message.lower()

    mutating_terms = [
        "fetch",
        "pull",
        "push",
        "commit",
        "commitea",
        "commitear",
        "crear rama",
        "crea rama",
        "nueva rama",
        "cambia a la rama",
        "cambiar a la rama",
        "checkout",
        "merge",
        "rebase",
        "reset",
        "stash",
        "aplica",
        "aplicar",
    ]

    return any(term in normalized for term in mutating_terms)


def detect_fast_read_tool(message: str) -> dict | None:
    normalized = message.lower()

    if is_git_mutating_request(message):
        return None

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


def detect_fast_git_action(message: str) -> dict | None:
    normalized = message.lower().strip()

    if not any(term in normalized for term in ["git", "repo", "rama", "branch", "pull", "push", "fetch", "commit"]):
        return None

    repo_path = "sity"

    if "fetch" in normalized:
        return {
            "action": "fetch",
            "repo_path": repo_path,
            "branch": "main",
            "remote": "origin",
            "risk_level": "safe",
            "summary": "Fetch del repo sity",
        }

    if "pull" in normalized:
        return {
            "action": "pull_ff_only",
            "repo_path": repo_path,
            "branch": "main",
            "remote": "origin",
            "risk_level": "critical",
            "summary": "Pull fast-forward del repo sity desde origin",
        }

    if "push" in normalized:
        return {
            "action": "push",
            "repo_path": repo_path,
            "branch": "main",
            "remote": "origin",
            "risk_level": "critical",
            "summary": "Push del repo sity a origin/main",
        }

    checkout_patterns = [
        r"(?:cambia|cambiar|vuelve|volver|checkout)\s+a\s+la\s+rama\s+([a-zA-Z0-9._/\-]+)",
        r"(?:cambia|cambiar|vuelve|volver|checkout)\s+a\s+([a-zA-Z0-9._/\-]+)",
        r"(?:checkout)\s+([a-zA-Z0-9._/\-]+)",
    ]

    for pattern in checkout_patterns:
        checkout_match = re.search(pattern, normalized)
        if checkout_match:
            branch = checkout_match.group(1).strip()

            if branch in {"en", "a", "la", "rama", "branch", "repo", "sity"}:
                return None

            return {
                "action": "checkout_branch",
                "repo_path": repo_path,
                "branch": branch,
                "remote": "origin",
                "risk_level": "critical",
                "summary": f"Cambiar a la rama {branch} en el repo sity",
            }

    create_branch_patterns = [
        r"(?:crea|crear)\s+(?:una\s+)?(?:rama|branch)\s+([a-zA-Z0-9._/\-]+)",
        r"(?:nueva)\s+(?:rama|branch)\s+([a-zA-Z0-9._/\-]+)",
    ]

    for pattern in create_branch_patterns:
        create_branch_match = re.search(pattern, normalized)
        if create_branch_match:
            branch = create_branch_match.group(1).strip()

            if branch in {"en", "a", "la", "rama", "branch", "repo", "sity"}:
                return None

            return {
                "action": "create_branch",
                "repo_path": repo_path,
                "branch": branch,
                "remote": "origin",
                "risk_level": "critical",
                "summary": f"Crear rama {branch} en el repo sity",
            }

    commit_match = re.search(
        r"(?:commit|commitea|commitear).*?(?:mensaje|con mensaje)\s+['\"]?(.+?)['\"]?$",
        message,
        flags=re.IGNORECASE,
    )

    if commit_match:
        commit_message = commit_match.group(1).strip()

        return {
            "action": "commit",
            "repo_path": repo_path,
            "branch": "main",
            "remote": "origin",
            "risk_level": "critical",
            "summary": f"Commit en el repo sity: {commit_message}",
            "commit_message": commit_message,
        }

    return None


def build_pending_action_response(created, payload: dict) -> str:
    action = payload.get("action")
    branch = payload.get("branch")

    lines = [
        f"Acción pendiente creada: {created.summary}",
        "",
        "Para ejecutarla, confirma con:",
        f"`{created.confirmation_phrase}`",
    ]

    if action == "checkout_branch" and branch:
        lines.extend(["", f'También puedes decir: "sí, vuelve a {branch}".'])

    elif action == "create_branch" and branch:
        lines.extend(["", f'También puedes decir: "sí, crea la rama {branch}".'])

    elif action == "pull_ff_only":
        lines.extend(["", 'También puedes decir: "sí, haz pull".'])

    elif action == "push":
        lines.extend(["", 'También puedes decir: "sí, haz push".'])

    elif action == "fetch":
        lines.extend(["", 'También puedes decir: "sí, haz fetch".'])

    elif action == "commit":
        lines.extend(["", 'También puedes decir: "sí, haz commit".'])

    lines.extend(["", f"Riesgo: {created.risk_level}."])

    return "\n".join(lines)


def is_service_action_allowed(service_name: str) -> bool:
    config = load_system_access_config()
    allowed = (
        config.get("system_access", {})
        .get("safe_actions", {})
        .get("allowed_services", [])
    )
    return service_name in allowed


def detect_fast_system_action(message: str) -> dict | None:
    normalized = message.lower().strip()

    service_aliases = {
        "backend": "sity-backend",
        "front": "sity-frontend",
        "frontend": "sity-frontend",
    }

    service_name = None
    for alias, service in service_aliases.items():
        if alias in normalized:
            service_name = service
            break

    if not service_name:
        service_match = re.search(
            r"(?:reinicia|reiniciar|arranca|arrancar|lanza|lanzar|inicia|iniciar|para|parar|detén|detener|stop|start|restart)\s+(?:el\s+|la\s+)?(?:servicio\s+)?([a-zA-Z0-9_.@-]+)",
            normalized,
        )
        if service_match:
            candidate = service_match.group(1).strip()
            if candidate not in {"backend", "frontend", "front"}:
                service_name = candidate

    if not service_name:
        return None

    if any(term in normalized for term in ["reinicia", "reiniciar", "restart"]):
        action = "restart_service"
        verb = "Reiniciar"
    elif any(term in normalized for term in ["arranca", "arrancar", "lanza", "lanzar", "inicia", "iniciar", "start"]):
        action = "start_service"
        verb = "Arrancar"
    elif any(term in normalized for term in ["para", "parar", "detén", "detener", "stop"]):
        action = "stop_service"
        verb = "Parar"
    else:
        return None

    return {
        "action": action,
        "service_name": service_name,
        "risk_level": "safe",
        "summary": f"{verb} servicio {service_name}",
    }


def extract_service_name_from_message(words: list[str]) -> str | None:
    ignored = {
        "sí", "si", "ok", "vale", "dale", "confirmo",
        "añade", "agrega", "permite", "autoriza",
        "quita", "elimina", "borra", "desautoriza",
        "el", "la", "los", "las", "un", "una",
        "servicio", "servicios",
        "a", "al", "de", "del", "en", "como",
        "permitido", "permitidos", "permitida", "permitidas",
        "controlable", "controlables",
        "sity", "puedes", "controlar",
    }

    candidates = [word for word in words if word not in ignored]

    for candidate in candidates:
        if all(char.isalnum() or char in "@_.-" for char in candidate):
            return candidate

    return None


def detect_service_config_action(message: str) -> dict | None:
    normalized = message.lower().strip()

    if "servicio" not in normalized and "servicios" not in normalized:
        return None

    add_terms = ["añade", "agrega", "permite", "autoriza"]
    remove_terms = ["quita", "elimina", "borra", "desautoriza"]

    words = normalized.replace("`", "").replace('"', "").replace("'", "").split()

    if any(term in normalized for term in add_terms):
        service_name = extract_service_name_from_message(words)
        if service_name:
            return {
                "action": "add_allowed_service",
                "service_name": service_name,
                "risk_level": "critical",
                "summary": f"Añadir {service_name} a servicios permitidos",
            }

    if any(term in normalized for term in remove_terms):
        service_name = extract_service_name_from_message(words)
        if service_name:
            return {
                "action": "remove_allowed_service",
                "service_name": service_name,
                "risk_level": "critical",
                "summary": f"Quitar {service_name} de servicios permitidos",
            }

    if any(term in normalized for term in [
        "qué servicios", "que servicios", "servicios puedes",
        "servicios permitidos", "qué puedes controlar", "que puedes controlar",
    ]):
        return {"action": "list_allowed_services"}

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
- Usa herramientas Git de lectura si pregunta por repos, commits, ramas, remotos, status o diff.
- Usa git_propose_action si el usuario pide git pull, git push, commit, crear rama, checkout, merge, rebase, reset o stash. No respondas solo con texto para estas acciones.
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

    confirmation_manager = ConfirmationManager(session)

    referenced_action_id = confirmation_manager.extract_action_id_from_message(request.message)

    if referenced_action_id:
        referenced_action = confirmation_manager.find_action_by_id(referenced_action_id)

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

            save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
            save_chat_message(session, role="sity", text=text, trace_id=trace_id)

            return ChatMessageResponse(
                ok=True,
                trace_id=trace_id,
                text=text,
                provider="local",
                model="confirmation-manager",
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
            )

        if not referenced_action:
            text = (
                f"No encuentro ninguna acción con ID `{referenced_action_id}`. "
                "Puede que sea antigua, incorrecta o de otra base de datos."
            )

            save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
            save_chat_message(session, role="sity", text=text, trace_id=trace_id)

            return ChatMessageResponse(
                ok=True,
                trace_id=trace_id,
                text=text,
                provider="local",
                model="confirmation-manager",
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
            )

    pending_action = confirmation_manager.find_pending_action_by_confirmation(request.message)

    if not pending_action:
        pending_action = confirmation_manager.find_pending_action_by_context(request.message)

    if pending_action:
        if pending_action.action_type == "git":
            try:
                payload = parse_git_payload(pending_action.payload_json)
                execution_result = execute_git_action(payload)

                if execution_result.get("ok"):
                    confirmation_manager.mark_executed(pending_action, trace_id)
                    lines = [f"Acción ejecutada: {pending_action.summary}"]
                    if execution_result.get("pre_command"):
                        lines.append(f"\nPreparación: {' '.join(str(x) for x in execution_result['pre_command'])}")
                        pre_out = execution_result.get("pre_stdout", "").strip()
                        if pre_out:
                            lines.append(f"Salida: {pre_out}")
                    lines.append(f"\nComando: {' '.join(str(x) for x in execution_result.get('command', []))}")
                    lines.append(f"Salida:\n{execution_result.get('stdout', '') or '(sin salida)'}")
                    text = "\n".join(lines)
                else:
                    error = execution_result.get("stderr", "Error desconocido")
                    confirmation_manager.mark_failed(pending_action, trace_id, error)
                    text = (
                        f"No he podido ejecutar la acción pendiente {pending_action.id}.\n\n"
                        f"Error:\n{error}"
                    )

            except Exception as exc:
                confirmation_manager.mark_failed(pending_action, trace_id, str(exc))
                text = f"Falló la ejecución de la acción pendiente {pending_action.id}: {exc}"

        elif pending_action.action_type == "system":
            try:
                payload = parse_system_payload(pending_action.payload_json)
                execution_result = execute_system_action(payload)

                if execution_result.get("ok"):
                    confirmation_manager.mark_executed(pending_action, trace_id)
                    text = (
                        f"Acción ejecutada: {pending_action.summary}\n\n"
                        f"Comando: {' '.join(str(x) for x in execution_result.get('command', []))}\n"
                        f"Salida:\n{execution_result.get('stdout', '') or '(sin salida)'}"
                    )
                    post_status = execution_result.get("post_status")
                    if post_status:
                        text += f"\nEstado posterior: {post_status}"
                else:
                    error = (
                        execution_result.get("stderr")
                        or execution_result.get("stdout")
                        or f"El comando terminó sin confirmación de éxito. Estado posterior: {execution_result.get('post_status', 'desconocido')}"
                    )
                    confirmation_manager.mark_failed(pending_action, trace_id, error)
                    text = (
                        f"No he podido ejecutar la acción pendiente {pending_action.id}.\n\n"
                        f"Error:\n{error}"
                    )

            except Exception as exc:
                confirmation_manager.mark_failed(pending_action, trace_id, str(exc))
                text = f"Falló la ejecución de la acción pendiente {pending_action.id}: {exc}"

        elif pending_action.action_type == "system_config":
            try:
                payload = parse_system_config_payload(pending_action.payload_json)
                execution_result = execute_system_config_action(payload)

                if execution_result.get("ok"):
                    confirmation_manager.mark_executed(pending_action, trace_id)
                    text = (
                        f"Acción ejecutada: {pending_action.summary}\n\n"
                        f"{execution_result.get('message', 'Configuración actualizada.')}"
                    )
                else:
                    error = execution_result.get("stderr", "Error desconocido")
                    confirmation_manager.mark_failed(pending_action, trace_id, error)
                    text = (
                        f"No he podido ejecutar la acción pendiente {pending_action.id}.\n\n"
                        f"Error:\n{error}"
                    )

            except Exception as exc:
                confirmation_manager.mark_failed(pending_action, trace_id, str(exc))
                text = f"Falló la ejecución de la acción pendiente {pending_action.id}: {exc}"

        save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
        save_chat_message(session, role="sity", text=text, trace_id=trace_id)

        daily_used = get_today_token_usage(session)

        return ChatMessageResponse(
            ok=True,
            trace_id=trace_id,
            text=text,
            provider="local",
            model="confirmation-manager",
            fallback_used=False,
            error_type=None,
            usage=UsageSummary(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                daily_used_tokens=daily_used,
                daily_budget_tokens=daily_budget,
                daily_ratio=0.0,
            ),
            warnings=[],
            personality_updated=False,
            updated_parameter=None,
            updated_parameters=[],
        )

    if (
        not pending_action
        and confirmation_manager.has_multiple_active_pending_actions()
        and confirmation_manager.is_generic_confirmation_message(request.message)
    ):
        text = (
            "Hay varias acciones pendientes, así que no voy a adivinar cuál quieres ejecutar. "
            "Confirma usando la frase exacta de la acción, tipo `confirmo ejecutar act_xxxxxxxx`."
        )

        save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
        save_chat_message(session, role="sity", text=text, trace_id=trace_id)

        return ChatMessageResponse(
            ok=True,
            trace_id=trace_id,
            text=text,
            provider="local",
            model="confirmation-manager",
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
        )

    service_config_action = detect_service_config_action(request.message)

    if service_config_action:
        action = service_config_action.get("action")

        if action == "list_allowed_services":
            result = list_allowed_services()
            text = (
                "Servicios permitidos para lectura:\n"
                + "\n".join(f"- {service}" for service in result["read_allowed_services"])
                + "\n\nServicios permitidos para acciones:\n"
                + "\n".join(f"- {service}" for service in result["action_allowed_services"])
            )

            save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
            save_chat_message(session, role="sity", text=text, trace_id=trace_id)

            return ChatMessageResponse(
                ok=True,
                trace_id=trace_id,
                text=text,
                provider="local",
                model="system-config",
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
            )

        service_name = service_config_action.get("service_name", "")

        existing_action = confirmation_manager.find_equivalent_pending_action(
            action_type="system_config",
            payload=service_config_action,
        )

        if existing_action:
            text = (
                f"Ya hay una acción pendiente para esto: {existing_action.summary}\n\n"
                "Para ejecutarla, confirma con:\n"
                f"`{existing_action.confirmation_phrase}`\n\n"
                'O usa una confirmación clara como: "sí, hazlo".'
            )
        else:
            created = confirmation_manager.create_pending_action(
                action_type="system_config",
                risk_level=service_config_action.get("risk_level", "critical"),
                summary=service_config_action.get("summary", "Cambiar allowlist de servicios"),
                payload=service_config_action,
                trace_id=trace_id,
            )

            if action == "add_allowed_service":
                natural = f"sí, añade {service_name}"
            else:
                natural = f"sí, quita {service_name}"

            text = (
                f"Acción pendiente creada: {created.summary}\n\n"
                "Esto modifica la allowlist de servicios de Sity. "
                "No crea ni elimina servicios systemd; solo cambia qué servicios puedo controlar.\n\n"
                "Para ejecutarla, confirma con:\n"
                f"`{created.confirmation_phrase}`\n\n"
                f'También puedes decir: "{natural}".\n\n'
                f"Riesgo: {created.risk_level}."
            )

        save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
        save_chat_message(session, role="sity", text=text, trace_id=trace_id)

        return ChatMessageResponse(
            ok=True,
            trace_id=trace_id,
            text=text,
            provider="local",
            model="system-config",
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
        )

    fast_system_action = detect_fast_system_action(request.message)

    if fast_system_action:
        if not is_service_action_allowed(fast_system_action["service_name"]):
            service_name = fast_system_action["service_name"]
            text = (
                f"No puedo controlar `{service_name}` todavía porque no está en la allowlist de servicios.\n\n"
                f"Puedes pedirme: `añade {service_name} a servicios permitidos`."
            )

            save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
            save_chat_message(session, role="sity", text=text, trace_id=trace_id)

            return ChatMessageResponse(
                ok=True,
                trace_id=trace_id,
                text=text,
                provider="local",
                model="confirmation-manager",
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
            )

        existing_action = confirmation_manager.find_equivalent_pending_action(
            action_type="system",
            payload=fast_system_action,
        )

        if existing_action:
            text = (
                f"Ya hay una acción pendiente para esto: {existing_action.summary}\n\n"
                "Para ejecutarla, confirma con:\n"
                f"`{existing_action.confirmation_phrase}`\n\n"
                'O usa una confirmación clara como: "sí, hazlo".'
            )

            save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
            save_chat_message(session, role="sity", text=text, trace_id=trace_id)

            return ChatMessageResponse(
                ok=True,
                trace_id=trace_id,
                text=text,
                provider="local",
                model="confirmation-manager",
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
            )

        created = confirmation_manager.create_pending_action(
            action_type="system",
            risk_level=fast_system_action.get("risk_level", "safe"),
            summary=fast_system_action.get("summary", "Acción de sistema"),
            payload=fast_system_action,
            trace_id=trace_id,
        )

        service_name = fast_system_action.get("service_name", "servicio")
        action = fast_system_action.get("action", "")

        if action == "restart_service":
            natural_confirmation = f"sí, reinicia {service_name}"
        elif action == "start_service":
            natural_confirmation = f"sí, arranca {service_name}"
        elif action == "stop_service":
            natural_confirmation = f"sí, para {service_name}"
        else:
            natural_confirmation = "sí, hazlo"

        text = (
            f"Acción pendiente creada: {created.summary}\n\n"
            "Para ejecutarla, confirma con:\n"
            f"`{created.confirmation_phrase}`\n\n"
            f'También puedes decir: "{natural_confirmation}".\n\n'
            f"Riesgo: {created.risk_level}."
        )

        save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
        save_chat_message(session, role="sity", text=text, trace_id=trace_id)

        return ChatMessageResponse(
            ok=True,
            trace_id=trace_id,
            text=text,
            provider="local",
            model="confirmation-manager",
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
        )

    fast_git_action = detect_fast_git_action(request.message)

    if fast_git_action:
        created = ConfirmationManager(session).create_pending_action(
            action_type="git",
            risk_level=fast_git_action.get("risk_level", "critical"),
            summary=fast_git_action.get("summary", "Acción Git"),
            payload=fast_git_action,
            trace_id=trace_id,
        )

        text = build_pending_action_response(created, fast_git_action)

        save_chat_message(session, role="user", text=request.message, trace_id=trace_id)
        save_chat_message(session, role="sity", text=text, trace_id=trace_id)

        return ChatMessageResponse(
            ok=True,
            trace_id=trace_id,
            text=text,
            provider="local",
            model="confirmation-manager",
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
        )

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

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.actions.confirmation_manager import ConfirmationManager
from app.core.cancellation import clear_operation, register_operation
from app.core.realtime_events import publish_event_sync
from app.actions.git_actions import execute_git_action
from app.actions.git_actions import parse_payload as parse_git_payload
from app.actions.sense_actions import execute_sense_action
from app.actions.sense_actions import parse_payload as parse_sense_payload
from app.actions.system_actions import execute_system_action
from app.actions.system_actions import parse_payload as parse_system_payload
from app.system.system_reader import load_system_access_config
from app.actions.system_config_actions import (
    execute_system_config_action,
    list_allowed_services,
    parse_payload as parse_system_config_payload,
)
from app.core.micro_reactions import generate_micro_reaction
from app.core.order_override import has_direct_order_override
from app.core.persona_engine import PersonaEngine
from app.core.refusal_tracker import get_last_refusal, set_last_refusal
from app.core.tool_executor import ToolExecutor
from app.cortex.ai_gateway import AIGateway
from app.cortex.schemas import AIRequest
from app.actions.file_actions import execute_file_action
from app.cortex.tool_schemas import (
    ALL_TOOLS,
    BASE_TOOLSET,
    DEBUG_TOOLSET,
    GIT_TOOLSET,
    PERSONALITY_TOOLSET,
    SENSES_TOOLSET,
    SERVICE_CONFIG_TOOLSET,
    SERVICE_CONTROL_TOOLSET,
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



class ChatHistoryItem(BaseModel):
    role: str
    text: str


class ChatMessageRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = []
    client_turn_id: str | None = None


class ChatArtifact(BaseModel):
    type: Literal["image", "audio", "file"]
    url: str
    filename: str
    mime_type: Optional[str] = None


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
    artifacts: list[ChatArtifact] = Field(default_factory=list)


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

    context_heavy_terms = [
        "ayer", "antes", "recuerdas", "dijiste", "hablamos",
        "historial", "qué hicimos", "que hicimos", "resume",
    ]

    single_action_terms = [
        "añade", "agrega", "quita", "elimina",
        "reinicia", "arranca", "para el",
        "servicios permitidos", "allowlist",
        "saca una foto", "graba audio", "graba ",
    ]

    technical_terms = [
        "error", "bug", "trace", "debug", "logs", "falló", "fallo",
        "repo", "git", "servicio", "backend", "frontend",
        "raspberry", "sistema", "cpu", "ram", "disco",
    ]

    if any(term in normalized for term in single_action_terms):
        return 4

    if any(term in normalized for term in context_heavy_terms):
        return 8

    if any(term in normalized for term in technical_terms):
        return 8

    return 4


def _dedupe_tools(tools: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for tool in tools:
        name = tool.get("name", "")
        if name not in seen:
            seen.add(name)
            result.append(tool)
    return result


def _looks_like_conversation_only(message: str) -> bool:
    normalized = message.lower()
    action_terms = [
        "reinicia", "arranca", "para el servicio", "para el backend", "para el frontend",
        "haz pull", "haz push", "haz fetch", "haz commit",
        "saca una foto", "graba", "graba audio",
        "añade", "quita", "limpia capturas",
        "git", "repo", "repositorio",
        "foto", "cámara", "camara", "webcam", "micrófono", "microfono",
        "debug", "traza", "trace", "logs",
        "servicio", "systemd", "backend", "frontend",
        "cpu", "ram", "disco", "raspberry",
        "personalidad", "sarcasmo", "calidez",
    ]
    return not any(term in normalized for term in action_terms)


def select_toolset_for_message(message: str) -> list[dict]:
    if _looks_like_conversation_only(message):
        return list(BASE_TOOLSET)

    normalized = message.lower()

    git_terms = [
        "git", "commit", "commits",
        "rama", "ramas", "branch", "branches",
        "pull", "push", "fetch", "checkout",
        "diff", "estado git", "status git",
    ]

    service_config_terms = [
        "añade", "agrega", "quita", "elimina",
        "servicios permitidos", "allowlist",
        "lista de servicios", "servicios que puedes",
        "add_allowed", "remove_allowed",
    ]

    service_control_terms = [
        "reinicia", "arranca", "para el", "detén", "detener",
        "estado del servicio", "systemctl",
        "sity-backend", "sity-frontend", "sity-test",
        "backend", "frontend",
    ]

    system_terms = [
        "raspberry", "sistema", "cpu", "ram", "memoria",
        "disco", "espacio", "procesos", "systemd",
    ]

    sense_terms = [
        "foto", "cámara", "camara", "webcam",
        "micro", "micrófono", "microfono", "audio",
        "capturas", "graba", "grabar",
    ]

    debug_terms = [
        "debug", "traza", "trace", "logs", "eventos",
        "errores", "herramientas",
    ]

    personality_fields = [
        "sarcasmo", "rudeza", "borde", "calidez", "honestidad",
        "paciencia", "melancolía", "melancolia", "tsundere",
        "verbosidad", "personalidad", "mala leche",
    ]

    personality_action_terms = [
        "sube", "baja", "ajusta", "cambia", "pon", "ponte", "slider",
    ]

    selected = list(BASE_TOOLSET)

    if any(term in normalized for term in git_terms):
        selected.extend(GIT_TOOLSET)

    if any(term in normalized for term in service_config_terms):
        selected.extend(SERVICE_CONFIG_TOOLSET)
    elif any(term in normalized for term in service_control_terms):
        selected.extend(SERVICE_CONTROL_TOOLSET)
    elif any(term in normalized for term in system_terms):
        selected.extend(SYSTEM_TOOLSET)

    if any(term in normalized for term in sense_terms):
        selected.extend(SENSES_TOOLSET)

    if any(term in normalized for term in debug_terms):
        selected.extend(DEBUG_TOOLSET)

    if (
        any(field in normalized for field in personality_fields)
        and any(term in normalized for term in personality_action_terms)
    ):
        selected.extend(PERSONALITY_TOOLSET)

    return _dedupe_tools(selected)





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




def capture_artifact_from_path(path_value: str) -> ChatArtifact | None:
    if not path_value:
        return None

    path = Path(path_value)
    filename = path.name
    suffix = path.suffix.lower()

    if suffix in {".jpg", ".jpeg", ".png"}:
        return ChatArtifact(
            type="image",
            url=f"/captures/camera/{filename}",
            filename=filename,
            mime_type="image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png",
        )

    if suffix in {".wav", ".mp3", ".ogg", ".m4a"}:
        return ChatArtifact(
            type="audio",
            url=f"/captures/audio/{filename}",
            filename=filename,
            mime_type="audio/wav" if suffix == ".wav" else None,
        )

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
- Usa herramientas Git (git_read_status, git_read_log, git_read_branches) si pregunta explícitamente por commits, ramas, diff, status git, remotos o el estado del repositorio git.
- Usa git_propose_action si el usuario pide git pull, git push, commit, crear rama, checkout, merge, rebase, reset o stash. No respondas solo con texto para estas acciones.
- Usa read_file o list_directory si el usuario pide ver, leer o listar un archivo o directorio concreto del proyecto.
- Usa write_file si el usuario pide crear o sobrescribir un archivo concreto. Nunca se ejecuta directamente: crea una acción pendiente.
- Usa apply_text_patch si el usuario pide cambiar una parte concreta de un archivo existente y proporciona el texto exacto a reemplazar. Llama a apply_text_patch DIRECTAMENTE con el old_text y new_text del mensaje — no llames a read_file antes. Nunca se ejecuta directamente: crea una acción pendiente con diff.
- Si el usuario quiere editar un archivo pero no proporciona el texto exacto a reemplazar, usa read_file primero para mostrarle el contenido.
- Usa list_file_changes SIEMPRE que el usuario pregunte qué archivos ha tocado Sity, qué cambió recientemente, qué acciones de archivo ejecutó o qué backups existen. No respondas de memoria ni basándote solo en el historial conversacional para estas preguntas.
- Si el usuario pide revertir, deshacer o restaurar el último cambio de archivo: usa list_file_changes primero para localizar el último evento con backup.created=true y después llama a rollback_file_change con ese backup_path. No te limites a mencionar el backup: crea la acción pendiente directamente.
- Usa no_action_required si solo quiere conversar.

Regla de contexto: Si el turno anterior fue sobre leer un archivo y el usuario confirma o aclara, mantén la intención de lectura. No cambies a herramientas Git salvo que el usuario pida explícitamente commits, ramas, diff, status git, pull o push.

Regla Git vs archivo: "repo", "proyecto" o "tu código" no activan Git por sí solos. Solo activan Git si viene acompañado de términos explícitos: commit, rama, branch, pull, push, fetch, checkout, diff.

No respondas con texto normal en esta fase.
No inventes resultados.
""".strip()


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

    if not pending_action and confirmation_manager.is_generic_confirmation_message(request.message):
        latest = confirmation_manager.get_latest_active_pending_action()
        if latest:
            text = (
                f"¿Te refieres a «{latest.summary}»? "
                f"Usa `{latest.confirmation_phrase}` para confirmar."
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

    if pending_action:
        _pending_artifact: ChatArtifact | None = None

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

        elif pending_action.action_type == "file":
            try:
                payload = json.loads(pending_action.payload_json)
                payload["pending_action_id"] = pending_action.id
                payload["trace_id"] = trace_id
                file_action = payload.get("action", "")
                execution_result = execute_file_action(payload)

                if execution_result.get("ok"):
                    confirmation_manager.mark_executed(pending_action, trace_id)
                    path = execution_result.get("path", "")
                    if file_action == "rollback_file_change":
                        restored_from = execution_result.get("restored_from_backup_path", "")
                        text = f"Rollback aplicado: {path}\nRestaurado desde: {restored_from}"
                    elif file_action == "apply_text_patch":
                        text = f"Patch aplicado: {path}"
                    elif file_action == "write_file":
                        created = execution_result.get("created", True)
                        text = f"Archivo {'creado' if created else 'sobreescrito'}: {path}"
                    else:
                        text = f"Acción de archivo ejecutada: {path}"
                else:
                    error = execution_result.get("error", "Error desconocido")
                    confirmation_manager.mark_failed(pending_action, trace_id, error)
                    if file_action == "rollback_file_change":
                        text = f"No he podido hacer el rollback: {error}"
                    elif file_action == "apply_text_patch":
                        text = f"No he podido aplicar el patch: {error}"
                    else:
                        text = f"No he podido escribir el archivo: {error}"

            except Exception as exc:
                confirmation_manager.mark_failed(pending_action, trace_id, str(exc))
                text = f"Falló la acción de archivo: {exc}"

        elif pending_action.action_type == "sense":
            try:
                payload = parse_sense_payload(pending_action.payload_json)
                execution_result = execute_sense_action(payload)

                if execution_result.get("ok"):
                    confirmation_manager.mark_executed(pending_action, trace_id)
                    _pending_artifact = capture_artifact_from_path(str(execution_result.get("path", "")))
                    text = f"Listo. {pending_action.summary}."
                else:
                    error = (
                        execution_result.get("stderr")
                        or execution_result.get("stdout")
                        or "Error desconocido"
                    )
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
            artifacts=[_pending_artifact] if _pending_artifact else [],
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

    selected_tools = select_toolset_for_message(request.message)


    tool_results_for_claude: list[dict] = []
    updated_parameters: list[str] = []
    response_artifacts: list[ChatArtifact] = []

    if not selected_tools:
        response = gateway.generate(
            AIRequest(
                trace_id=trace_id,
                task_type="chat_message",
                system_prompt=persona_prompt,
                user_message=user_message_with_history,
                max_tokens=max_tokens,
                tools_enabled=False,
            )
        )
    else:
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

    if selected_tools and planner_response.ok and planner_response.tool_calls:
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
                    client_turn_id=request.client_turn_id,
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

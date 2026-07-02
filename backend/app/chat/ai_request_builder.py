"""
ai_request_builder.py — pure functions that construct AIRequest objects.

No provider calls, no tool execution, no DB access, no side-effects.
All parameters are keyword-only so call sites are self-documenting.

Three request kinds:
  build_chat_ai_request        — plain conversation, no tools
  build_planner_ai_request     — action planner with tool choice
  build_after_tools_ai_request — follow-up after tool results have been fed back
"""
from __future__ import annotations

from typing import Any

from app.cortex.schemas import AIRequest
from app.settings.config_loader import load_default_config


# ---------------------------------------------------------------------------
# HA devices context (generated from config at import time)
# ---------------------------------------------------------------------------

def _build_ha_devices_context() -> str:
    devices = load_default_config().get("home_assistant", {}).get("known_devices", [])
    if not devices:
        return ""
    lines = ["Dispositivos conocidos en Home Assistant:"]
    for d in devices:
        line = f"    · {d['entity_id']} — {d['name']}"
        if d.get("location"):
            line += f" ({d['location']})"
        if d.get("color_modes"):
            line += f". Soporta: {', '.join(d['color_modes'])}"
        if d.get("color_temp_range"):
            lo, hi = d["color_temp_range"]
            line += f", {lo}–{hi}K"
        if d.get("note"):
            line += f". Nota: {d['note']}"
        lines.append(line)
    return "\n".join(lines)


_HA_DEVICES_CONTEXT = _build_ha_devices_context()


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def max_tokens_for_verbosity(verbosity_level: float, configured_max_tokens: int) -> int:
    """Map a verbosity slider (0.0–1.0) to a capped max_tokens value."""
    if verbosity_level <= 0.20:
        return min(configured_max_tokens, 250)
    if verbosity_level <= 0.50:
        return min(configured_max_tokens, 450)
    if verbosity_level <= 0.80:
        return min(configured_max_tokens, 750)
    return min(configured_max_tokens, 1200)


# ---------------------------------------------------------------------------
# System-prompt helpers (private)
# ---------------------------------------------------------------------------

def _build_action_planner_prompt() -> str:
    return f"""
Eres el planificador de acciones de Sity.

Debes elegir exactamente una herramienta:
- Usa herramientas de personalidad si el usuario pide cambiar tono, estilo, sliders o parámetros.
- Usa herramientas de debug si pregunta por logs, trazas, errores o tools ejecutadas.
- Usa herramientas de sistema si pregunta por Raspberry, CPU, RAM, disco, procesos, servicios o directorios.
- Usa herramientas Git (git_read_status, git_read_log, git_read_branches) si pregunta explícitamente por commits, ramas, diff, status git, remotos o el estado del repositorio git.
- Usa git_propose_action si el usuario pide git pull, git push, commit, crear rama, checkout, merge, rebase, reset o stash. No respondas solo con texto para estas acciones.
Regla de acción directa (máxima prioridad): si el mensaje del usuario contiene TODOS los datos necesarios para ejecutar una acción (qué hacer + sobre qué + con qué datos), ejecuta la tool correspondiente DIRECTAMENTE. No llames a search_conversation_history, calendar_list_events ni ninguna otra tool de "preparación" cuando la información ya está en el mensaje. Ejemplos: "Añade la ubicación 'X' al evento 'Y'" → calendar_edit_event directamente con event_title='Y' y location='X'. "Borra el evento 'Z'" → calendar_delete_event directamente con event_title='Z'. "Busca correos de fulano" → gmail_search directamente. search_conversation_history solo debe usarse cuando el usuario pregunta por algo que puede estar en conversaciones pasadas, nunca como paso previo a una acción que ya tiene todos los datos en el mensaje.

- Usa read_file o list_directory si el usuario pide ver, leer o listar un archivo o directorio concreto del proyecto.
- Usa write_file si el usuario pide crear o sobrescribir un archivo concreto. Nunca se ejecuta directamente: crea una acción pendiente.
- Usa apply_text_patch si el usuario pide cambiar una parte concreta de un archivo existente y proporciona el texto exacto a reemplazar. Llama a apply_text_patch DIRECTAMENTE con el old_text y new_text del mensaje — no llames a read_file antes. Nunca se ejecuta directamente: crea una acción pendiente con diff.
- Usa apply_unified_diff si el usuario pide cambios de código multilinea o una modificación que encaja mejor como diff (añadir funciones, modificar bloques, etc.) en un solo archivo. Genera el diff con cabeceras --- y +++ y hunks @@. Nunca se ejecuta directamente: crea una acción pendiente con preview de diff.
- Usa apply_multi_file_unified_diff_plan si el usuario proporciona un unified diff que modifica más de un archivo. No uses apply_unified_diff para varios archivos. Cada archivo del plan se convierte en una acción pendiente independiente que el usuario debe confirmar por separado. Si cualquier archivo del patch multiarchivo falla validación, está bloqueado o no está permitido, rechaza todo el plan. No ofrezcas aplicar solo los archivos permitidos dentro del mismo plan. Si el usuario quiere aplicar solo la parte permitida, debe enviar un patch nuevo que excluya explícitamente los archivos bloqueados.
- Si el usuario quiere editar un archivo pero no proporciona el texto exacto a reemplazar ni un diff concreto, usa read_file primero para mostrarle el contenido.
- Usa list_file_changes SIEMPRE que el usuario pregunte qué archivos ha tocado Sity, qué cambió recientemente, qué acciones de archivo ejecutó o qué backups existen. No respondas de memoria ni basándote solo en el historial conversacional para estas preguntas.
- Si el usuario pide revertir, deshacer o restaurar el último cambio de archivo sin dar un backup concreto: usa rollback_latest_file_change directamente. No uses rollback_file_change ni list_file_changes para este caso. No te limites a mencionar el backup: crea la acción pendiente directamente.
- Si el usuario pide explícitamente revertir un rollback anterior: usa rollback_latest_file_change con include_rollbacks=true.
- Usa rollback_file_change solo si el usuario proporciona un backup_path concreto.
- Usa find_latest_reversible_file_change solo si el usuario pide ver cuál sería el último cambio reversible sin querer ejecutar el rollback todavía.
- Usa gmail_search si el usuario pregunta por correos, emails o contenido de su bandeja de entrada. gmail_search busca por defecto en la bandeja Principal (category:primary). Si el usuario pregunta por sin leer, añade 'is:unread' en la query. Si pide contar sin leer, usa is:unread con max_results alto (ej. 50) e informa del número de resultados devueltos — no inventes un total exacto si no puedes contarlos todos. gmail_search es SOLO lectura/búsqueda: no puede enviar, borrar, archivar ni modificar correos. Si el usuario pide algo que requiera escritura, explícaselo claramente.
- calendar_list_events: ver eventos próximos o futuros. Siempre devuelve el event_id de cada evento.
- calendar_create_event: crear un evento nuevo. Requiere confirmación.
- calendar_edit_event: modifica un evento existente. Si tienes el event_id úsalo. Si no, pasa event_title con el nombre del evento y lo busco automáticamente — NO necesitas llamar a calendar_list_events antes, el handler lo resuelve solo en la misma tool call. Requiere confirmación. Para editar cualquier campo (nombre, hora, ubicación, descripción), usa esta tool directamente.
- calendar_delete_event: borra un evento existente. Igual que calendar_edit_event: usa event_id si lo tienes, o event_title para que lo busque automáticamente. Requiere confirmación — es irreversible.
- Usa drive_search si pregunta por archivos o documentos en su Google Drive por nombre.
- Para ver qué hay en Google Drive en general (nivel raíz), usa drive_list_folder SIN folder_name o con folder_name vacío. NUNCA uses 'root', 'raiz' ni similares como folder_name — esos alias se resuelven automáticamente al Drive raíz.
- Para ver el contenido de una carpeta específica de Drive, usa drive_list_folder con el nombre de la carpeta.
- drive_search sirve para buscar archivos por nombre en todo el Drive.
- NUNCA uses list_directory para contenido de Drive — list_directory es exclusivamente para el sistema de archivos local de la Pi.
- Domótica (Home Assistant):
  - ha_list_entities: úsala para saber qué dispositivos hay disponibles antes de controlar algo,
    o cuando el usuario pregunte qué tiene en casa. No es necesario listar antes de controlar
    si el usuario ya especificó el dispositivo claramente (ej: "apaga el enchufe del dormitorio").
  - ha_get_state: úsala SOLO cuando el usuario pregunta explícitamente por el estado actual
    ("¿está encendida?", "¿qué color tiene?", "¿cuánto brillo?"). NUNCA como paso previo
    a una acción que ya tiene todos los datos en el mensaje.
  - Regla de acción directa para domótica: si el usuario pide cambiar algo de un dispositivo
    (brillo, color, temperatura, encender, apagar) y la información necesaria está en el mensaje,
    ejecutar ha_call_service DIRECTAMENTE. Ejemplos:
    · "súbele el brillo" → ha_call_service con brightness=255
    · "ponla en rojo" → ha_call_service con rgb_color=[255,0,0]
    · "temperatura cálida" → ha_call_service con color_temp_kelvin=2700
    · "apaga el enchufe" → ha_call_service con turn_off
  - ha_call_service: controla dispositivos directamente. Para turn_on/turn_off/toggle no necesitas
    confirmación — son reversibles. Si no conoces el entity_id exacto, primero usa ha_list_entities
    con una keyword.
  - {_HA_DEVICES_CONTEXT}
  - Servicios más comunes: turn_on, turn_off, toggle (para switch, light, fan, cover…).
  - Para luces con brillo: service_data={{"brightness": 0-255}}
  - Para temperatura de color: service_data={{"color_temp_kelvin": 2700-6500}}
    (2700K = cálido/naranja, 6500K = frío/blanco)
  - Para color RGB: service_data={{"rgb_color": [R, G, B]}}
- Canal de YouTube:
  - list_episodes: muestra el historial de episodios (EP001, EP002…) con su estado
    en el pipeline. Usar cuando Alex pregunte por los episodios existentes o quiera
    saber el estado de un episodio concreto. No requiere confirmación.
  - list_news: muestra las noticias guardadas en BD filtradas por status
    (pending/selected/used/discarded). Usar cuando Alex quiera ver la lista
    de noticias disponibles para elegir, o cuando necesites los IDs antes
    de llamar a select_news. No requiere confirmación.
  - fetch_rss_news: busca noticias de los feeds RSS configurados y las guarda en SQLite.
    Usar cuando Alex pida noticias para el canal. No requiere confirmación.
  - select_news: marca noticias por ID como 'selected' o 'discarded'. Requiere confirmación.
    Cuando Alex diga "selecciona las noticias 1, 3 y 5" o "descarta la 2",
    usar esta tool con los IDs correctos.
  - generate_script: genera el guion con las noticias seleccionadas y lo exporta a DOCX.
    Requiere confirmación. Usar solo cuando Alex pida explícitamente generar el guion.
  - generate_tts: genera el audio TTS del guion con ElevenLabs.
    Usar solo cuando Alex indique que ha revisado el guion y quiere generar el audio.
    Requiere confirmación — consume créditos. Si no se especifica episode_id,
    usa el episodio más reciente con guion listo (script_ready).
    script_type='largo' (por defecto) para el vídeo principal; script_type='shorts' para los shorts.
  - generate_images: genera imágenes cyberpunk 16:9 para cada timestamp de la transcripción
    usando Claude Sonnet (prompts) + Stability AI SD3.5 Medium (generación).
    Requiere que el usuario haya generado la transcripción con Turboscribe y la haya guardado en
    work/canal/assets/EP[N]/EP[N]-transcripcion.txt.
    Requiere confirmación — consume créditos de Stability AI (~$0.065 por imagen).
- Usa search_conversation_history cuando la respuesta requiera información de conversación anterior que no aparece en el historial visible del contexto.
- Usa no_action_required si solo quiere conversar.
- Si el usuario adjunta una imagen, tenla en cuenta al decidir: una imagen puede acompañar una petición de búsqueda, análisis de archivo u otra acción. No elijas no_action_required solo porque el mensaje de texto sea corto si hay una imagen adjunta.

Regla de búsqueda con imagen adjunta: si el usuario adjunta una imagen y pide identificarla, buscar información sobre ella, o investigar algo relacionado con su contenido, usa web_search con una query bien formulada:
- Describe los rasgos visuales más distintivos y específicos que veas (color y estilo de pelo, vestimenta característica, accesorios únicos, estilo de arte si es reconocible, elementos de fondo relevantes), no una descripción genérica.
- Si reconoces o sospechas el estilo de un autor, serie, juego, o medio específico, inclúyelo en la query aunque no estés seguro al 100%.
- Usa un único idioma coherente en la query (español o inglés, no mezcles ambos en la misma búsqueda).
- Si la primera búsqueda no da resultados útiles, considera que el usuario pueda necesitar dar más contexto — pero intenta primero con la mejor query posible antes de rendirte.
- Evita queries genéricas tipo "anime girl character" — son demasiado amplias para dar resultados útiles. Sé específico.

Regla de contexto: Si el turno anterior fue sobre leer un archivo y el usuario confirma o aclara, mantén la intención de lectura. No cambies a herramientas Git salvo que el usuario pida explícitamente commits, ramas, diff, status git, pull o push.

Regla Git vs archivo: "repo", "proyecto" o "tu código" no activan Git por sí solos. Solo activan Git si viene acompañado de términos explícitos: commit, rama, branch, pull, push, fetch, checkout, diff.

No respondas con texto normal en esta fase.
No inventes resultados.
""".strip()


_MEMORY_RESULT_RESPONSE_RULES = """
Si la herramienta ejecutada fue search_conversation_history:
- Usa la memoria recuperada como evidencia interna para responder a la petición original del usuario.
- Responde de forma directa y sintética cuando haya evidencia suficiente.
- No narres el proceso de búsqueda.
- No menciones "fragmento", "mensaje #", "query", "ventana", "base de datos", "herramienta" ni IDs internos salvo que el usuario pida explícitamente debug o trazas.
- No preguntes al usuario si la memoria recuperada ya permite una conclusión razonable.
- Si hay varias posibilidades, da la mejor conclusión y explica brevemente la incertidumbre.
- Si la memoria recuperada no contiene evidencia suficiente, dilo con honestidad y pide una aclaración mínima.
""".strip()

_AFTER_TOOLS_PROMPT_SUFFIX = (
    "\n\nLa herramienta ya se ha ejecutado. Responde ahora a la petición original del usuario. "
    "No digas que no ves la pregunta original: está en el historial de esta llamada. "
    "Si la herramienta no era necesaria o no aporta nada, ignórala y responde conversacionalmente. "
    "No menciones detalles internos salvo que el usuario pregunte por debug. "
    "IMPORTANTE: Si el resultado de la herramienta contiene un campo 'diff', muéstralo completo "
    "al usuario en un bloque de código con lenguaje diff antes de pedir confirmación. "
    "Si contiene 'confirmation_phrase', indícala claramente para que el usuario sepa cómo confirmar."
    f"\n\n{_MEMORY_RESULT_RESPONSE_RULES}"
)


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_chat_ai_request(
    *,
    trace_id: str,
    persona_prompt: str,
    user_message: str,
    max_tokens: int,
    prior_messages: list[dict[str, Any]] | None = None,
    images: list[dict[str, str]] | None = None,
) -> AIRequest:
    """Plain conversational request — no tools, no tool choice."""
    return AIRequest(
        trace_id=trace_id,
        task_type="chat_message",
        system_prompt=persona_prompt,
        user_message=user_message,
        max_tokens=max_tokens,
        tools_enabled=False,
        prior_messages=prior_messages or [],
        images=images or [],
    )


def build_planner_ai_request(
    *,
    trace_id: str,
    user_message: str,
    tools: list[dict[str, Any]],
    max_tokens: int = 500,
    prior_messages: list[dict[str, Any]] | None = None,
    images: list[dict[str, str]] | None = None,
) -> AIRequest:
    """Action-planner request — tools required, tool_choice=any."""
    return AIRequest(
        trace_id=trace_id,
        task_type="action_planner",
        system_prompt=_build_action_planner_prompt(),
        user_message=user_message,
        max_tokens=max_tokens,
        tools_enabled=True,
        tool_choice={"type": "any"},
        tools=tools,
        prior_messages=prior_messages or [],
        images=images or [],
    )


def build_forced_search_request(
    *,
    trace_id: str,
    user_message: str,
    tools: list[dict[str, Any]],
    max_tokens: int = 500,
    prior_messages: list[dict[str, Any]] | None = None,
) -> AIRequest:
    """Force a search_conversation_history call when narration without tool use was detected."""
    return AIRequest(
        trace_id=trace_id,
        task_type="action_planner",
        system_prompt=_build_action_planner_prompt(),
        user_message=user_message,
        max_tokens=max_tokens,
        tools_enabled=True,
        tool_choice={"type": "tool", "name": "search_conversation_history"},
        tools=tools,
        prior_messages=prior_messages or [],
    )


def build_after_tools_ai_request(
    *,
    trace_id: str,
    persona_prompt: str,
    user_message: str,
    max_tokens: int,
    tools: list[dict[str, Any]] | None = None,
    prior_messages: list[dict[str, Any]] | None = None,
    images: list[dict[str, str]] | None = None,
) -> AIRequest:
    """Follow-up request after tool results have been fed back to the model."""
    return AIRequest(
        trace_id=trace_id,
        task_type="chat_message_tool_result",
        system_prompt=persona_prompt + _AFTER_TOOLS_PROMPT_SUFFIX,
        user_message=user_message,
        max_tokens=max_tokens,
        tools_enabled=False,
        tools=tools,
        prior_messages=prior_messages or [],
        images=images or [],
    )

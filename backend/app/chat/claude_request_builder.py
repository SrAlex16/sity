"""
Claude request builder.

Prepares AIRequest objects for provider calls only.
Must not call providers, execute tools, persist messages, or decide safety policy.
"""

from __future__ import annotations

from typing import Any

from app.cortex.schemas import AIRequest


def max_tokens_for_verbosity(verbosity_level: float, configured_max_tokens: int) -> int:
    if verbosity_level <= 0.20:
        return min(configured_max_tokens, 250)
    if verbosity_level <= 0.50:
        return min(configured_max_tokens, 450)
    if verbosity_level <= 0.80:
        return min(configured_max_tokens, 750)
    return min(configured_max_tokens, 1200)


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
- Usa apply_unified_diff si el usuario pide cambios de código multilinea o una modificación que encaja mejor como diff (añadir funciones, modificar bloques, etc.) en un solo archivo. Genera el diff con cabeceras --- y +++ y hunks @@. Nunca se ejecuta directamente: crea una acción pendiente con preview de diff.
- Usa apply_multi_file_unified_diff_plan si el usuario proporciona un unified diff que modifica más de un archivo. No uses apply_unified_diff para varios archivos. Cada archivo del plan se convierte en una acción pendiente independiente que el usuario debe confirmar por separado. Si cualquier archivo del patch multiarchivo falla validación, está bloqueado o no está permitido, rechaza todo el plan. No ofrezcas aplicar solo los archivos permitidos dentro del mismo plan. Si el usuario quiere aplicar solo la parte permitida, debe enviar un patch nuevo que excluya explícitamente los archivos bloqueados.
- Si el usuario quiere editar un archivo pero no proporciona el texto exacto a reemplazar ni un diff concreto, usa read_file primero para mostrarle el contenido.
- Usa list_file_changes SIEMPRE que el usuario pregunte qué archivos ha tocado Sity, qué cambió recientemente, qué acciones de archivo ejecutó o qué backups existen. No respondas de memoria ni basándote solo en el historial conversacional para estas preguntas.
- Si el usuario pide revertir, deshacer o restaurar el último cambio de archivo sin dar un backup concreto: usa rollback_latest_file_change directamente. No uses rollback_file_change ni list_file_changes para este caso. No te limites a mencionar el backup: crea la acción pendiente directamente.
- Si el usuario pide explícitamente revertir un rollback anterior: usa rollback_latest_file_change con include_rollbacks=true.
- Usa rollback_file_change solo si el usuario proporciona un backup_path concreto.
- Usa find_latest_reversible_file_change solo si el usuario pide ver cuál sería el último cambio reversible sin querer ejecutar el rollback todavía.
- Usa no_action_required si solo quiere conversar.

Regla de contexto: Si el turno anterior fue sobre leer un archivo y el usuario confirma o aclara, mantén la intención de lectura. No cambies a herramientas Git salvo que el usuario pida explícitamente commits, ramas, diff, status git, pull o push.

Regla Git vs archivo: "repo", "proyecto" o "tu código" no activan Git por sí solos. Solo activan Git si viene acompañado de términos explícitos: commit, rama, branch, pull, push, fetch, checkout, diff.

No respondas con texto normal en esta fase.
No inventes resultados.
""".strip()


class ClaudeRequestBuilder:
    def chat_request(
        self,
        *,
        trace_id: str,
        persona_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> AIRequest:
        return AIRequest(
            trace_id=trace_id,
            task_type="chat_message",
            system_prompt=persona_prompt,
            user_message=user_message,
            max_tokens=max_tokens,
            tools_enabled=False,
        )

    def planner_request(
        self,
        *,
        trace_id: str,
        user_message: str,
        tools: list[dict[str, Any]],
        max_tokens: int = 500,
    ) -> AIRequest:
        return AIRequest(
            trace_id=trace_id,
            task_type="action_planner",
            system_prompt=build_action_planner_prompt(),
            user_message=user_message,
            max_tokens=max_tokens,
            tools_enabled=True,
            tool_choice={"type": "any"},
            tools=tools,
        )

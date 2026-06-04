# backend/app/chat

Este paquete contiene piezas del flujo de chat extraídas desde `routes_chat.py`.

El objetivo es reducir responsabilidades del router HTTP sin cambiar comportamiento. Cada módulo debe tener límites claros y evitar efectos secundarios innecesarios.

## Regla general

`routes_chat.py` debe tender a ser una capa fina:

```text
HTTP request
  -> orchestration
  -> response
```

La lógica de negocio del chat debe vivir en módulos pequeños y testeables.

## Módulos actuales

> Última actualización: 2026-06-04.

### `budget_guard.py`

Gestiona guards locales antes de llamar al proveedor IA:

```text
SITY_LOCAL_ONLY
SITY_DAILY_TOKEN_HARD_CAP
respuesta local-only-guard
respuesta budget-guard
```

Debe ejecutarse después de `local_flow` y `pending_action_runner`, porque las confirmaciones locales y acciones pendientes ya confirmadas deben seguir funcionando aunque local-only esté activo o el presupuesto esté agotado.

No debe llamar a Claude, ejecutar tools, crear pending actions ni interpretar lenguaje natural.

---

### `local_flow.py`

Gestiona respuestas locales previas a cualquier llamada IA:

```text
IDs de acción inexistentes
acciones ya ejecutadas
acciones expiradas
acciones fallidas
confirmación genérica sin pending actions
ambigüedad con varias pending actions
confirmaciones mal formateadas con ID válido
```

Ejemplo protegido:

```text
confirmo ejecutar act_12345678`
```

Debe responder localmente pidiendo confirmación exacta, no caer a Claude.

No debe ejecutar acciones, llamar a Claude, crear acciones nuevas ni hacer tool selection.

Limitación conocida: si el usuario responde solo `sí`, `vale`, `ok` o similar y no hay pending actions activas, Sity responde localmente que no hay nada que confirmar. Esto ahorra tokens y evita confirmaciones ambiguas, pero puede sentirse raro en conversación normal.

---

### `pending_action_runner.py`

Ejecuta acciones pendientes ya confirmadas:

```text
ejecución de pending actions
mark_executed
mark_failed
respuesta local tras ejecución
artifacts asociados si aplica
```

Solo debe recibir acciones ya resueltas por `ConfirmationManager`.

No debe interpretar lenguaje natural, elegir qué acción confirmar desde texto ambiguo, crear nuevas acciones ni llamar a Claude.

---

### `toolset_selector.py`

Hace routing técnico de toolsets y ajustes de contexto:

```text
selección de toolset
history_limit
detección conservadora de señales técnicas
```

Esto no es NLU de acciones.

#### Dos capas de selección

**1. Estructural** — `select_structural_toolsets_for_message`:

```text
nombres exactos de tools presentes en el mensaje
rutas de fichero (/, config/, backend/, etc.)
IDs estructurales act_[0-9a-f]{8}
```

Testeable en aislamiento. No depende de lenguaje natural.

**2. Legacy keyword fallback** — `_legacy_keyword_toolsets`:

```text
mantenido solo por compatibilidad
no añadir nuevos literales de lenguaje natural
preferir señales estructurales o schemas
```

`select_toolset_for_message` llama al estructural primero y añade el legacy encima.

#### BASE_TOOLSET — mínimo operativo, no vacío

`BASE_TOOLSET` no significa "sin herramientas". Incluye file tools (`read_file`, `write_file`, `apply_text_patch`, etc.) y `cancel_pending_action`. Es el toolset mínimo operativo presente en toda conversación.

Consecuencia: las regresiones conversacionales no comprueban que `BASE_TOOLSET` esté vacío. Comprueban que mensajes casuales no añadan toolsets especializados adicionales (`SENSES`, `GIT`, `SYSTEM`, `SERVICE_CONFIG`, `SERVICE_CONTROL`, `DEBUG`, `PERSONALITY`) más allá de lo que BASE ya incluye.

`cancel_pending_action` no vive en `BASE_TOOLSET`; se expone mediante `PENDING_ACTION_TOOLSET` solo cuando hay señal estructural (`act_xxxxxxxx`) o nombre explícito de herramienta. Esto evita que conversaciones casuales reciban herramientas de cancelación.

#### Permitido / no permitido

Permitido:

```text
detectar rutas explícitas
detectar nombres de tools en el mensaje
detectar señales Git
detectar señales de debug
detectar señales de archivos
ajustar history_limit
mostrar menos tools al modelo
```

No permitido:

```text
crear acciones desde regex
ejecutar acciones desde texto libre
sustituir tool calling por lógica backend
extraer intención de negocio para modificar el sistema
```

Principio:

```text
Heurísticas técnicas sí.
NLU de acciones en backend no.
```

---

### `prompt_context.py`

Construye contexto textual para el proveedor IA:

```text
recent_history
planner_history
renderizado de historial
user_message_with_history
planner_user_message (con contexto estructural de memoria)
filtrado de mensajes operativos
búsqueda proactiva de memoria
```

Debe filtrar mensajes operativos como:

```text
Modo local-only activo...
Presupuesto diario de IA agotado...
```

Esos mensajes describen estados runtime antiguos. Si se mandan a Claude como historial normal, el modelo puede creer que siguen vigentes.

Contexto de memoria inyectado en `planner_user_message`:

```text
Contexto estructural de memoria:
- total_messages: N
- visible_history_count: M
- history_limit: K
- long_memory_tool_available: true
```

Cuando `n_total > history_limit`, `_proactive_memory_search(message)` ejecuta búsqueda FTS5/LIKE sobre el mensaje del usuario e inyecta los resultados como bloque `[MEMORIA RELEVANTE]...[FIN MEMORIA]` antes de llamar al planner.

No debe llamar a Claude, ejecutar tools, guardar mensajes ni decidir seguridad.

---

### `ai_request_builder.py`

Construye requests al provider:

```text
AIRequest
system prompt
user message final (con contexto de memoria estructural)
tools seleccionadas
max_tokens
```

Debe ser side-effect-free.

No debe llamar al proveedor, ejecutar tools, guardar mensajes, crear `ChatMessageResponse` ni hacer validación de seguridad.

---

### `response_guard.py`

Valida texto final generado por el modelo antes de guardarlo o devolverlo.

Protege contra respuestas engañosas como:

```text
Confirma con: confirmo ejecutar git_fetch_checkout_readme
```

Si el modelo genera una frase `confirmo ejecutar ...` sin un ID real `act_[0-9a-f]{8}`, la respuesta se bloquea y se sustituye por un mensaje local seguro.

No debe ejecutar acciones, crear pending actions ni decidir si una tool es válida. Solo valida texto final.

---

### `artifacts.py`

Helper compartido para construir `ChatArtifact` desde una ruta de archivo.

Usado por `routes_chat.py` y `pending_action_runner.py`.

No debe ejecutar acciones, guardar mensajes ni llamar a Claude.

---

## Orden actual del flujo local

El orden recomendado en `routes_chat.py` es:

```text
1. Crear ConfirmationManager.
2. ChatLocalFlow.
3. Resolver pending_action exacta/contextual.
4. PendingActionRunner si hay acción confirmada.
5. ChatBudgetGuard.
6. ToolsetSelector.
7. PromptContextBuilder.
8. ClaudeRequestBuilder.
9. Provider/tool loop.
10. ResponseGuard sobre texto final.
11. Guardar y devolver respuesta final.
```

Este orden es importante.

Especialmente:

```text
ChatLocalFlow y PendingActionRunner deben ir antes de ChatBudgetGuard.
```

Así Sity puede ejecutar confirmaciones locales aunque no pueda llamar a Claude.

---

## Zona delicada: provider/tool loop

El tool loop todavía vive en `routes_chat.py`.

No extraerlo de forma mecánica.

Motivos:

```text
tiene varios early returns
acumula tokens del planner y segunda llamada
recarga personalidad dentro del loop
maneja local_final
maneja micro-reactions de sense
acumula artifacts
mezcla respuesta final y tool results
```

Extraerlo requiere diseño de interfaz, no solo mover código.

Antes de refactorizarlo, crear tests de integración que cubran:

```text
tool call normal
tool call con local_final
write_file pending action
apply_text_patch pending action
sense tool con artifact
micro-reaction
tool error
segunda llamada a Claude
uso de tokens acumulado
respuesta final con artifacts
response_guard bloqueando confirmaciones falsas
```

Hasta entonces:

```text
No tocar tool loop salvo cambios pequeños y muy controlados.
```

---

## Próximos módulos probables

### `provider_call_runner.py`

Futuro módulo para encapsular llamadas al proveedor IA.

Debe esperar a tener tests de integración.

### `tool_loop_runner.py`

Futuro módulo para el bucle de tools.

Debe esperar a tener tests de integración.

### `chat_orchestrator.py`

Objetivo final:

```python
orchestrator = ChatOrchestrator(session=session)
return await orchestrator.handle(request)
```

---

## Principio de seguridad

Ningún módulo de chat debe saltarse estas reglas:

```text
El modelo interpreta.
El backend valida.
El usuario confirma.
El backend ejecuta.
```

La personalidad puede cambiar el tono, pero no la política.

La frase `es una orden` puede eliminar negativa teatral, pero no puede saltarse:

```text
allowlists
confirmaciones
rutas bloqueadas
hard cap
local-only
políticas de riesgo
```

---

## Checklist antes de tocar este paquete

Antes de modificar módulos de `backend/app/chat/`:

```text
1. Confirmar qué responsabilidad tiene el cambio.
2. Evitar efectos secundarios nuevos.
3. Mantener confirmaciones locales antes de budget guards.
4. No mover tool loop sin tests de integración.
5. Ejecutar compileall.
6. Ejecutar tests locales.
```

Comandos mínimos:

```bash
backend/.venv/bin/python -m compileall backend/app
backend/.venv/bin/python scripts/test_confirmation_manager_local.py
backend/.venv/bin/python scripts/test_file_access_local.py
```

---

## Estado del refactor

Extraído desde `routes_chat.py`:

```text
budget_guard.py
local_flow.py
pending_action_runner.py
toolset_selector.py
prompt_context.py           — incluye memoria proactiva y contexto estructural
ai_request_builder.py       — (renombrado desde claude_request_builder.py)
response_guard.py
artifacts.py
```

Tool handler registry migrado (`backend/app/tools/`):

```text
Todos los handlers viven en app/tools/handlers/*.py
_dispatch_tool_call no tiene ramas if tool_name ==
_cancel_pending_action eliminado de ToolExecutor (código muerto tras migración)
memory_tools.py: handler search_conversation_history → MemoryRecallRunner
```

Pendiente de extraer, pero no todavía:

```text
provider/tool loop
final response assembly completo
provider abstraction
ChatOrchestrator
```

Motivo:

```text
El tool loop necesita tests de integración antes de moverlo.
```

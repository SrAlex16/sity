# Conversation Features / Funcionalidades de Conversación

[English](#english) · [Español](#español)

---

## English

### Chat pipeline

Each user message flows through:

```
HTTP POST /chat/message
    → pre_check.py (rate limits, session validation)
    → cognitive pipeline (user sessions only)
    → ai_orchestrator.py (Claude call + tool loop)
    → tool_executor.py (dispatches tools)
    → response_integrity.py (post-generation safety)
    → persistence.py (save to SQLite)
    → SSE stream to client
```

`routes_chat.py` is intentionally thin — it receives the HTTP request and delegates everything else.

### Multi-turn tool loop

Claude can request multiple rounds of tool calls within a single turn. The orchestrator runs a bounded loop:

- **Max rounds**: 3 (`max_after_tools_rounds`)
- **Exit conditions**: no tools requested, turn cancelled, round limit reached
- **Cost**: each extra round is a full Claude call (~$0.003, 1–3 seconds on Pi)
- **Logging**: tool events include `loop_round`; a `tool_chain_continued` event marks each extra round

Detachable tools (currently `web_search`) can be detached in any round, not just the first.

Background (detachable) tool flow:
1. Claude replies immediately ("I'll search that for you")
2. Background thread runs the tool
3. On completion, a natural-language summary is generated and pushed as a new message via SSE

### Session queue

Each session has its own in-memory lock that serializes turns. A version counter detects superseded turns, which terminate without calling the model. The lock is always released in a `finally` block.

**Why this exists**: On 2026-09-14, two messages sent ~2 seconds apart in the same session were processed in parallel. The second turn saw incomplete context and produced a hallucinated response. Fixed in commit `063f1e5`.

Parallel execution across different sessions is not affected.

### Turn cancellation

The stop button uses two independent mechanisms:

1. **Browser**: immediately aborts the event stream and shows a cancellation message
2. **Backend**: marks the operation as cancelled; the streaming call to Claude checks this flag and stops generating (saves tokens)

Cancelled turns are saved with a fixed cancellation notice in the chat history (not empty text).

**Key implementation rule**: Use `break` instead of `return` inside the streaming context manager to avoid triggering a close error that overwrites the cancelled result.

### Task context

For multi-step tasks where values resolved early (like a Spotify URI or device ID) might fall out of the history window, handlers can return a `task_context` dict. The executor saves it to SQLite and injects it into every following turn's planner message.

**Lifecycle**:
- Saves merge with existing keys (not overwrite)
- Returning `{}` clears the state (task complete)
- Returning `None` leaves context unchanged
- 30-minute absolute TTL based on `updated_at`

**Storage**: SQLite via the `Setting` model, keyed by `task_context:{session_id}`. Survives backend restarts.

Only string key-value pairs are supported. Only key names are logged, never values (may be private resource IDs).

### History window

The planner's history limit is 10 turns (raised from 4 in Layer B of the task context improvement). This adds ~150 tokens per turn. Keyword-based detection for task context was deliberately rejected.

### Response integrity

Post-generation safety layer (`response_integrity.py`). Catches cases where the model makes false claims about its own capabilities or memory:

**Pre-filter (free, regex)**: only activates if:
- A tool was executed, OR
- Session has history, OR
- Text contains risk patterns

**Risk categories checked**:
- `capability_overclaim` — claiming to have tools it doesn't
- `internal_leak` — revealing internal architecture
- `memory_fabrication` — claiming memory for guest sessions
- `contradiction` — contradicting earlier confirmed statements
- `architecture_disclosure` — revealing cognitive pipeline details

**Cost**: normal turn = 0 extra calls; risk turn = 1 Haiku call; with correction = 2 additional calls.

If the API fails during integrity check, the text passes unchanged (turn must not be broken).

**Why this exists**: A 2026-09-15 audit found: a guest session claimed Git/disk access; the model revealed internal architecture after saying it wouldn't; a guest was told it had memory from prior conversations.

---

## Español

### Pipeline de chat

Cada mensaje del usuario fluye a través de los módulos descritos en la sección en inglés. `routes_chat.py` es intencionalmente delgado.

### Bucle multi-turno de tools

Claude puede solicitar múltiples rondas de tool calls dentro de un mismo turno. Máximo 3 rondas. Las tools detachables (actualmente `web_search`) se pueden despachar en cualquier ronda.

Flujo de tool en background:
1. Claude responde inmediatamente
2. Un thread en background ejecuta la tool
3. Al terminar, un resumen en lenguaje natural se empuja como nuevo mensaje por SSE

### Cola de sesión

Cada sesión tiene su propio lock en memoria que serializa los turnos. Un contador de versión detecta los turnos superados, que terminan sin llamar al modelo.

**Por qué existe**: El 2026-09-14, dos mensajes con ~2s de diferencia se procesaron en paralelo. El segundo turno vio contexto incompleto y produjo una respuesta alucinada. Fix en commit `063f1e5`.

### Cancelación de turno

El botón de parar usa dos mecanismos independientes: el browser aborta el stream inmediatamente; el backend marca la operación como cancelada y el streaming para (ahorrando tokens).

**Regla de implementación**: Usar `break` en lugar de `return` dentro del context manager de streaming para no disparar un error de cierre que sobreescriba el resultado cancelado.

### Task context

Para tareas multi-paso donde valores resueltos temprano (como un URI de Spotify) pueden caer fuera de la ventana de historial, los handlers pueden devolver un dict `task_context`. Se persiste en SQLite y se inyecta en cada turno siguiente.

- TTL absoluto: 30 minutos
- Solo pares string→string
- Solo se loguean nombres de clave, nunca valores (pueden ser IDs privados de recursos)

### Integridad de respuesta

Capa de seguridad post-generación. Pre-filtro con regex (gratuito), solo activa la verificación con Haiku si hay señales de riesgo. Si falla la API durante la verificación, el texto pasa sin cambios para no romper el turno.

**Por qué existe**: Una auditoría del 2026-09-15 encontró que el modelo afirmaba tener acceso a Git/disco en sesión guest, revelaba arquitectura interna y afirmaba tener memoria en sesiones guest.

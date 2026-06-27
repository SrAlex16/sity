# Sity

Sity es una IA doméstica de ocio pensada para ejecutarse principalmente en una Raspberry Pi/RasPad, con personalidad propia, memoria conversacional, acceso controlado al sistema y capacidad de ejecutar acciones reales bajo políticas de seguridad.

El objetivo no es solo tener un chatbot, sino una asistente local extensible: capaz de hablar, mirar, interactuar con archivos, Git, servicios, sensores, hardware doméstico y, en el futuro, funcionar con distintos proveedores de IA o incluso modelos locales.

---

## Estado actual

### Funciona

- Backend FastAPI.
- Frontend web con chat.
- Integración con Claude API.
- Personalidad dinámica configurable.
- Sliders de personalidad.
- Modificación de personalidad desde chat mediante tools.
- Historial persistente de conversación.
- SQLite como base local.
- Logs y trazas.
- Debug tools.
- Lectura de estado del sistema.
- Lectura de estado Git.
- Acciones Git con confirmación.
- Acciones systemd con confirmación.
- Gestión dinámica de allowlist de servicios.
- Servicios systemd versionados en el repo.
- Servicio de prueba `sity-test`.
- Presupuesto diario local de tokens.
- Hard cap opcional para evitar llamadas a Claude al superar presupuesto.
- Modo `local-only`.
- Respuestas finales locales para acciones deterministas.
- Reducción de segunda llamada a Claude tras tools de archivos.
- Runtime config centralizado.
- `SITY_PROJECT_ROOT`, `SITY_PLATFORM`, `SITY_PROFILE`, `SITY_AI_PROVIDER`.
- CORS configurable por env.
- SQLite WAL + busy timeout.
- Uso diario de tokens optimizado con `SELECT SUM`.
- Cámara USB detectada y funcionando.
- Micrófono USB de webcam detectado y funcionando.
- Captura de cámara desde backend y frontend.
- Grabación corta de audio desde backend y frontend.
- Preview de imagen en el chat.
- Reproductor de audio en el chat.
- Eventos en tiempo real mediante SSE.
- Cancelación de grabación de audio.
- Cancelación de captura de cámara.
- Micro-reacciones con personalidad.
- Limpieza de capturas antiguas.
- Lectura segura de archivos permitidos.
- Listado seguro de directorios permitidos.
- Escritura segura de archivos permitidos dentro del repo.
- Patches seguros por reemplazo exacto.
- Aplicación segura de unified diff.
- Planificación segura de unified diff multiarchivo.
- Preview de diff antes de confirmar.
- Audit log de cambios de archivo.
- Backup automático antes de modificar archivos existentes.
- Consulta de últimos cambios mediante `list_file_changes`.
- Rollback de archivos desde backup explícito.
- Rollback natural del último cambio reversible.
- Script de regresión repo-only para System Agent.
- Tests locales sin llamadas a Claude.
- Confirmación genérica contextual protegida.
- Bloqueo local de IDs de acción mal confirmados.
- Confirmaciones locales antes de hard cap/local-only.
- Filtrado de mensajes operativos fuera del historial enviado a Claude.
- Refactor inicial de `routes_chat.py`.
- OllamaProvider v1 implementado y testeado (chat-only, httpx, sin tools).
- Arquitectura híbrida cloud/local: `SITY_LOCAL_AI_ENABLED` + `SITY_LOCAL_AI_PROVIDER`.
- `ChatRoutingDecision`: separa `cloud_tools`, `cloud_chat` y `local_chat_candidate`.
- Prompt local compacto (`local_persona_system.md`): voz sin etiquetas de arquetipo, rasgos conductuales.
- CORS multi-origen: `SITY_CORS_ORIGINS` (lista por comas) + retro-compat `SITY_CORS_ORIGIN`.
- Pi → PC LAN Ollama funcional para conversación normal (tools siempre van por cloud).
- Módulo de contexto temporal (`time_context.py`) inyectado en prompts.
- Aislamiento completo de DB en pytest y en tests de integración mock.
- Diagnóstico manual de modelos Ollama añadido en `scripts/diag_ollama_models.py`.
- Pipeline LoRA validado en WSL con `google/gemma-3-4b-it`, Unsloth y RTX 3060 Ti.
- Snapshot de personalidad (`tone_meta`) guardado junto a cada respuesta de Sity.
- Regla de idioma e interlocutor en prompt: tuteo singular, sin voseo ni plural (vosotros). 9 tests.
- Continuidad conversacional corregida: `history_limit` por defecto 4→10; términos de consulta de memoria ampliados. 12 tests.
- Adapter LoRA de overfit probado: identidad Sity, femenino gramatical y rechazo de tools inventadas.
- `SITY_OLLAMA_MODEL` requerido explícitamente cuando `SITY_LOCAL_AI_ENABLED=true`; misconfiguration loggeada como `local_ai_misconfigured` con respuesta controlada.
- Tool call inputs del planner redactados en logs (`redact_tool_call_input`): always-redact para write_file/apply_*; preview truncado para el resto.
- Generador sintético de dataset v1 con caching explícito de prompt: `scripts/generate_sity_v1_with_claude_cache.py`.
- Metadata por mensaje en `ChatMessage`: `speaker_label`, `speaker_source`, `speaker_confidence`, `dataset_source`, `dataset_eligible`, `dataset_tags_json`, `identity_evidence_json` (reservado).
- Dataset Capture Mode: etiquetado de mensajes nuevos sin cambiar prompt ni comportamiento. Persistido en `Setting` table. Endpoints `GET/PUT /debug/dataset-capture`, `POST /debug/dataset-capture/disable`. Presets: `normal_use`, `synthetic_claude_user`, `human_guest`, `debug_test`.
- DatasetStats backend: módulo puro de cómputo de pares user→Sity usables para LoRA. Endpoint `GET /debug/dataset-stats`. Buckets, tags y progreso hacia targets por tipo de personalidad.
- Pestaña Dataset en el frontend: Dataset Capture (formulario con presets) + DatasetStats (cobertura, targets, desglose por source/tag, últimos pares).
- FTS5 full-text search sobre historial (`chatmessage_fts`): content table SQLite con triggers automáticos + fallback LIKE por token para instancias sin FTS5.
- Tool `search_conversation_history` en `BASE_TOOLSET`: siempre disponible para que el planner decida cuándo buscar en el historial.
- `MemoryRecallRunner`: búsqueda iterativa con hasta 4 variantes de query. Evalúa calidad de evidencia por **novel token ratio** (fracción de tokens del fragmento no presentes en la query original). Agota siempre todos los intentos (sin parada temprana). Abre ventanas de contexto alrededor de cada ancla con `message_id` (hasta `_MAX_WINDOWS=3`). Evita falsos positivos por fragmentos que solo repiten la pregunta del usuario.
- Contexto estructural de memoria inyectado en `planner_user_message` cada turno: `total_messages`, `visible_history_count`, `history_limit`, `long_memory_tool_available`.
- Búsqueda proactiva de memoria cuando `n_total > history_limit`: inyecta bloque `[MEMORIA RELEVANTE]` antes de llamar al planner.
- Filtrado de mensajes operativos en contexto prev/next de resultados de búsqueda.
- Audio STT: `faster-whisper` local (modelo `base`, español, CPU). `POST /audio/transcribe`. Metadata `input_mode`, `voice_transcript_original`, `edit_distance_pct` en `ChatMessage`. Botón de micrófono en ChatTab. Soporte de mensajes de voz en Telegram.
- Audio TTS: Piper TTS local. `POST /audio/synthesize`, `GET /audio/tts/{filename}`. Speaker femenino por `_SPEAKER_NAME_MAP` + `--speaker` flag. `voice_response_mode`, `voice_include_text`, `voice_long_response_action` en tab Voice.
- `voice_include_text` respetado en Telegram (texto omitido si false) y en frontend (burbuja sin texto si hay audio y `voice_include_text == false`).
- `output_mode` y `tts_fragments` en `ChatMessage`: modo de salida del turno y número de fragmentos TTS sintetizados.
- `source_channel` en `ChatMessage`: `"web"` por defecto; `"telegram"` cuando el origen es el bot. Heredado por la respuesta de Sity.
- Telegram bot: long polling, `sity-telegram.service`, allowlist por `chat_id`, rate limit, comandos `/preset /defaults /status`. Logs con `trace_id` en todas las fases de artifact. `SityGateway` incluye `"source_channel": "telegram"` en cada POST.
- PWA móvil (mobile/) con diseño cyberpunk/neón.
- Chat funcional conectado al backend real.
- Grabación y envío de audio como nota de voz desde móvil.
- Respuestas de audio de Sity: burbujas con player (seek, progreso, duración). Historial de audio reconstituido desde `audio_filename` al recargar. Reproducción secuencial automática entre fragmentos del mismo turno (`trace_id`).
- Borrado de chat persistente: `clearMessages()` guarda timestamp; el historial filtra mensajes anteriores al borrado.
- Fondo por defecto: wallpaper1.png cuando no hay preferencia guardada.
- Transcripción de respuestas de voz respeta `voice_include_text`: burbujas de audio-only sin texto visible paralelo.
- Sliders de personalidad táctiles con widget de encabronamiento animado.
- Pantalla de Voice y Dataset conectadas al backend. Periodicidad de borrado de audio editable desde pantalla de Voz.
- Fondo de pantalla elegible (galería + predefinidos).
- Selector de fuente (Orbitron / Share Tech Mono / Rajdhani).
- Acceso remoto via Tailscale desde cualquier red.
- Navegación entre pantallas con animaciones Framer Motion.
- Servicio systemd `sity-mobile.service`.

### Refactor reciente

`routes_chat.py` ya no concentra lógica local, tool loop, construcción de requests AI,
llamadas al provider ni el cierre de respuesta final.

Módulos extraídos en `backend/app/chat/`:

```text
  budget_guard.py          — guardia de presupuesto y local-only
  budget_snapshot.py       — cálculo de ratio/warnings tras cada llamada AI
  local_flow.py            — confirmaciones locales, IDs, ambigüedad
  pending_action_runner.py — ejecución de pending actions confirmadas
  prompt_context.py        — historial, renderizado, filtrado operativo, memoria proactiva
  response_factory.py      — helpers de construcción de ChatMessageResponse
  tool_loop_step.py        — ejecución y normalización de una sola tool call
  tool_loop_runner.py      — iteración del tool loop; devuelve ToolLoopRunOutcome
  toolset_selector.py      — selección técnica de toolsets y heurísticas
  ai_request_builder.py    — construcción de AIRequest para cada fase
  provider_call_runner.py  — wrapper semántico sobre AIGateway
  final_response_builder.py — cierre AI: AIUsage + snapshot + log + guard + save
  local_provider_config.py — validación y resolución del modelo Ollama local
```

Módulos de memoria (`backend/app/memory/`):

```text
  search.py   — search_conversation_history: FTS5 + LIKE fallback, filtrado operativo,
                 prev/next context, limit clamping, text truncation
  recall.py   — MemoryRecallRunner: búsqueda iterativa multi-query,
                 evaluación de evidencia por novel token ratio
  db.py       — engine SQLite compartido
```

`routes_chat.py`: 757 → 543 líneas (−214) tras el refactor inicial; crece con nuevas features.

Schemas API compartidos:

```text
backend/app/api/schemas.py
```

Frontend modularizado:

```text
frontend/src/
  App.tsx                 — shell/orquestador, routing de pestañas
  hooks/useChat.ts        — estado y ciclo de vida del chat
  components/
    ChatTab.tsx           — presentacional
    PersonalityTab.tsx    — presentacional
    DebugTab.tsx          — trazas SSE y eventos recientes
    DatasetTab.tsx        — Dataset Capture + DatasetStats
  api/
    chatApi.ts
    sityApi.ts
    debugApi.ts           — incluye DatasetStats y DatasetCapture
```

Pestañas disponibles: **Chat**, **Settings**, **Debug** (solo trazas), **Dataset** (captura y estadísticas LoRA).

---

## Limitaciones conocidas y bugs

### Arquitectura
- `routes_chat.py` todavía contiene la orquestación del flujo AI (planner → tool loop → after_tools) y los early returns. No hay aún `ChatOrchestrator`.
- `ToolExecutor` todavía tiene demasiada lógica concentrada.
- La primera llamada a Claude sigue siendo necesaria para interpretar muchas acciones.
- `list_file_changes` puede seguir usando Claude para redactar resumen.
- Provider Interface creada (`AITextProvider` Protocol) pero sin mover providers a `providers/` aún.

### Sistema de memoria
- La búsqueda proactiva solo se activa cuando `n_total > history_limit`. Las conversaciones cortas nunca disparan búsqueda proactiva aunque el tema sea relevante.
- `_LIMIT_MAX = 10`: el tool puede devolver como máximo 10 resultados por llamada; para temas con mucha cobertura en el historial puede perder contexto relevante más antiguo.
- La evaluación de novel token ratio usa solo tokens de longitud ≥ 4. Textos muy cortos o con vocabulario inusualmente breve pueden producir clasificaciones incorrectas.
- FTS5 rebuild al arrancar es idempotente y rápido para el tamaño actual (~ms/1k mensajes), pero podría ralentizar arranque con historiales muy grandes.
- `is_operational_guard_message` usa coincidencia textual simple; si cambian los patrones de mensajes operativos hay que actualizar la función.

### Local flow
- Si el usuario responde solo “sí”, “ok”, “vale” y no hay pending actions activas, `local_flow.py` responde localmente que no hay nada que confirmar. Puede sentirse raro en conversación normal.

### Acceso a sistema
- Sity todavía no tiene shell libre.
- Sity no tiene acceso global a toda la Raspberry.
- El acceso de archivos es principalmente repo-only.
- Multiarchivo no es transaccional.
- No hay confirmación múltiple real tipo “confirma todas”.
- No hay perfiles `home-safe` o `system-careful`.
- Cámara/audio siguen teniendo defaults específicos de Raspberry.

---

## Arquitectura general

```text
frontend/
  Interfaz web de chat, sliders, previews y controles.
  Ver frontend/README.md para la estructura interna.

backend/
  API FastAPI.
  Núcleo de conversación.
  Gateway IA.
  Providers.
  Tools.
  Confirmaciones.
  Acceso controlado a sistema/Git.
  System Agent.
  Sensores.
  Eventos en tiempo real.
  Micro-reacciones.

backend/app/chat/
  Flujo local extraído desde routes_chat.py:
  guards, confirmaciones, pending actions, prompt context y toolset selector.

config/
  Configuración local versionada.

data/
  SQLite, logs, audit logs y backups runtime.
  Ignorado por git.

deploy/
  Plantillas systemd, sudoers, audio y documentación de despliegue.

scripts/
  Scripts de desarrollo, instalación, estado, limpieza y regresión.

captures/
  Capturas temporales de cámara/audio.
  Ignorado por git salvo `.gitkeep`.

docs/
  Documentación operativa y técnica actualizada:
  - `docs/architecture.md`
  - `docs/operations/current-state.md`
  - `docs/operations/development-workflow.md`
  - `docs/operations/ollama-diagnostics.md`
  - `docs/training/gemma3-lora.md`

training/
  Scripts y datasets mínimos para smoke tests LoRA.
  Los adapters generados en `training/output/` no se versionan.
  Los modelos Hugging Face descargados viven fuera del repo.
```

Principio base:

```text
Sity interpreta.
Backend valida.
Backend ejecuta.
```

El modelo puede proponer acciones, pero el backend decide si son válidas, seguras, permitidas y si requieren confirmación.

---

## Documentación operativa

Documentos principales:

```text
docs/architecture.md                         — arquitectura actual y objetivo
docs/operations/current-state.md             — estado operativo del proyecto
docs/operations/development-workflow.md      — flujo PC / WSL / Raspberry
docs/operations/dataset-capture.md          — Dataset Capture, DatasetStats y flujo LoRA v1
docs/operations/ollama-diagnostics.md        — diagnóstico manual de modelos Ollama
docs/training/gemma3-lora.md                 — pipeline LoRA Gemma 3 4B con Unsloth
```

La documentación debe actualizarse cuando cambien decisiones de arquitectura, seguridad, training, providers o despliegue.

---

## Tool handler registry

`ToolExecutor` ya no despacha herramientas con un bloque monolítico `if/elif`.
El dispatch pasa por `backend/app/tools/registry.py` y handlers por dominio.

Módulos actuales:

```text
backend/app/tools/
  registry.py
  types.py
  handlers/
    file_tools.py
    file_write_tools.py
    file_rollback_tools.py
    git_tools.py
    system_read_tools.py
    config_tools.py
    sense_tools.py
    pending_action_tools.py
    personality_tools.py
    propose_tools.py
    service_config_tools.py
    memory_tools.py         — handler search_conversation_history → MemoryRecallRunner
```

`ToolExecutor` conserva helpers privados reutilizados por algunos handlers, pero `_dispatch_tool_call` ya no contiene ramas por nombre de herramienta.

Test de integración:

```bash
./scripts/test_chat_tool_registry_integration.sh
```

Cubre:

```text
health
read_file
list_directory
list_file_changes
git_read_status
read_system_status
list_camera_devices
write_file fallback
cancel_pending_action
confirmación malformada local
ResponseGuard contra pseudo tool calls
```

---

## Runtime config

Sity usa configuración centralizada mediante:

```text
backend/app/core/runtime_config.py
```

Variables principales:

```env
SITY_PROJECT_ROOT=/home/alex/projects/sity
SITY_PLATFORM=raspberrypi
SITY_PROFILE=repo-only
SITY_AI_PROVIDER=anthropic          # provider cloud: anthropic | mock | ollama (experimental)
SITY_DAILY_TOKEN_HARD_CAP=true
SITY_LOCAL_ONLY=false
SITY_CORS_ORIGINS=http://192.168.1.133:5173   # lista por comas; incluye localhost:5173 por defecto
# SITY_CORS_ORIGIN=...              # legacy (singular), aún soportado
# Local AI (desactivado por defecto)
SITY_LOCAL_AI_ENABLED=false
SITY_LOCAL_AI_PROVIDER=ollama
SITY_OLLAMA_BASE_URL=http://127.0.0.1:11434
SITY_OLLAMA_MODEL=<modelo>
SITY_OLLAMA_TIMEOUT_SECONDS=60
```

Objetivo:

```text
- evitar hardcodes de entorno
- facilitar portabilidad
- preparar platform adapters
- preparar provider interface
- permitir perfiles futuros
```

El código debe leer configuración desde runtime config, `.env` o YAML. No debe asumir rutas como `/home/alex/projects/sity` salvo como fallback técnico o configuración local.

---

## AI providers

Sity usa una interfaz `AITextProvider` para desacoplar el flujo de chat del proveedor de IA.

```text
backend/app/cortex/providers/
  base.py          — AITextProvider Protocol (generate, generate_with_tool_results)
  factory.py       — build_ai_provider(name, *, model) → AITextProvider

backend/app/cortex/
  claude_provider.py   — proveedor real Anthropic
  mock_provider.py     — proveedor determinista para tests y CI
  ollama_provider.py   — chat-only, httpx POST /api/chat, sin tools
```

**Provider cloud (`SITY_AI_PROVIDER`):**

| Nombre | Clase | Estado |
|---|---|---|
| `anthropic` | `ClaudeProvider` | **Default estable.** Requiere `ANTHROPIC_API_KEY`. |
| `mock` | `MockProvider` | Determinista, sin red, sin API key. Usado en tests y CI. |
| `ollama` / `local` | `OllamaProvider` | Experimental / manual. Ver nota abajo. |

**Provider local (`SITY_LOCAL_AI_PROVIDER`):**

El provider local es **independiente** del provider cloud. Se activa con `SITY_LOCAL_AI_ENABLED=true`
y solo se usa para turnos conversacionales (`local_chat_candidate`). Tools y acciones siempre
van por el provider cloud.

```env
# Provider cloud (siempre activo):
SITY_AI_PROVIDER=anthropic           # default

# Provider local (solo conversación normal):
SITY_LOCAL_AI_ENABLED=false          # default — no activar en producción sin modelo validado
SITY_LOCAL_AI_PROVIDER=ollama
SITY_OLLAMA_BASE_URL=http://127.0.0.1:11434
SITY_OLLAMA_MODEL=<modelo>
SITY_OLLAMA_TIMEOUT_SECONDS=60
```

> **Nota:** No usar `SITY_AI_PROVIDER=ollama` para routing híbrido.
> Eso haría que tools y planner también usasen Ollama, que no soporta tool calling.
> Usar siempre `SITY_LOCAL_AI_ENABLED=true` + `SITY_LOCAL_AI_PROVIDER=ollama` para local.

Un nombre desconocido lanza `ValueError` en startup para que los errores de configuración se detecten pronto.

### Diagnóstico manual de Ollama

El script `scripts/diag_ollama_models.py` permite medir modelos Ollama sin tocar runtime ni routing.

Los resultados se guardan en `reports/ollama/` y no se versionan.

Ver `docs/operations/ollama-diagnostics.md`.

---

## Control de presupuesto

Sity registra uso diario de tokens y puede bloquear llamadas a Claude.

### Hard cap

```env
SITY_DAILY_TOKEN_HARD_CAP=true
```

Si el presupuesto diario está agotado:

```text
provider=local
model=budget-guard
total_tokens=0
```

Respuesta esperada:

```text
Presupuesto diario de IA agotado. No voy a llamar a Claude ahora.
Puedo seguir resolviendo confirmaciones, acciones pendientes y respuestas locales que no requieran IA.
```

### Local-only

```env
SITY_LOCAL_ONLY=true
```

Cuando está activo:

```text
- no se llama a Claude
- se aceptan confirmaciones exactas/locales
- se ejecutan acciones pendientes existentes
- no se interpretan nuevas peticiones con IA
```

Respuesta esperada:

```text
provider=local
model=local-only-guard
total_tokens=0
```

### Orden correcto del flujo

```text
1. Resolver confirmaciones locales.
2. Ejecutar pending actions confirmadas.
3. Aplicar local-only / hard cap.
4. Solo entonces llamar a Claude si hace falta.
```

Así una confirmación pendiente sigue funcionando aunque el presupuesto esté agotado.

---

## Memoria e historial

Sity guarda conversación en SQLite (tabla `chatmessage`, sesión única `"default"`).

El historial enviado a Claude se construye mediante `PromptContextBuilder` (`backend/app/chat/prompt_context.py`):

```text
- carga recent_history y planner_history
- renderiza historial
- filtra mensajes operativos
- inyecta contexto estructural de memoria en planner_user_message
- ejecuta búsqueda proactiva cuando n_total > history_limit
```

Mensajes operativos (`Presupuesto diario de IA agotado...`, `Modo local-only activo...`) se filtran del historial enviado a Claude. Si se enviaran como historial normal, el modelo podría creerlos vigentes aunque el estado runtime haya cambiado.

### FTS5 y búsqueda en historial

`backend/app/memory/search.py` implementa `search_conversation_history(query, limit)`:

```text
- tabla chatmessage_fts como content table FTS5 de chatmessage
- 3 triggers SQLite (AFTER INSERT/DELETE/UPDATE) para sincronía automática
- rebuild idempotente al arrancar
- fallback a LIKE por token si FTS5 no disponible
- operationals filtrados del match y de prev/next
- limit clamped a [1, 10]
- texto truncado a 1000 chars
- prev/next context por mensaje (sin operationals)
```

La tool `search_conversation_history` está en `BASE_TOOLSET` (siempre disponible). El planner decide cuándo usarla.

### MemoryRecallRunner

`backend/app/memory/recall.py` ejecuta la búsqueda iterativa:

```text
- genera hasta 4 variantes de query algorítmicamente (no domain-specific)
- busca con search_conversation_history en cada intento
- deduplica fragmentos entre intentos
- evalúa calidad de evidencia por novel token ratio
- para cuando hay evidencia suficiente (max_novel ≥ 0.60) o se agotan intentos
- devuelve MemoryRecallResult: status, fragments, confidence, queries_tried, truncated
```

El **novel token ratio** mide qué fracción de tokens del fragmento no están en la query original. Fragmentos que solo repiten la pregunta del usuario tienen ratio bajo; fragmentos con información nueva tienen ratio alto.

### Búsqueda proactiva

Cuando `n_total > history_limit`, `prompt_context.py` ejecuta búsqueda proactiva sobre el mensaje del usuario e inyecta los resultados como bloque `[MEMORIA RELEVANTE]...[FIN MEMORIA]` antes de llamar al planner.

---

## Toolset selector

Sity usa un selector técnico de toolsets:

```text
ToolsetSelector
```

Este módulo decide qué herramientas mostrar al modelo y cuánto historial incluir.

Importante:

```text
No crea acciones.
No ejecuta acciones.
No interpreta intención de negocio.
Solo reduce contexto y tools usando señales técnicas conservadoras.
```

Permitido:

```text
- detectar rutas explícitas
- detectar IDs de acción
- detectar señales de debug
- detectar señales Git
- reducir history_limit
- seleccionar toolset más pequeño
```

No permitido:

```text
- ejecutar acciones desde regex
- crear pending actions desde texto libre
- extraer nombres de servicio desde texto humano para ejecutar
- sustituir tool calling por NLU local
```

Principio:

```text
Heurísticas técnicas sí.
NLU de acciones en backend no.
```

---

## Confirmation Manager

Las acciones modificadoras pasan por pending actions.

Confirmación exacta:

```text
confirmo ejecutar act_xxxxxxxx
```

Reglas:

```text
- ID exacto gana siempre.
- Acción ejecutada no se repite.
- Acción expirada no se ejecuta.
- ID inexistente responde local.
- ID pendiente mal formateado no cae a Claude.
- Confirmación genérica solo funciona con contexto válido.
- Si hay varias acciones pendientes, no se adivina.
```

Ejemplo de bloqueo correcto:

```text
Usuario: confirmo ejecutar act_12345678`
Sity: He detectado la acción `act_12345678`, pero la confirmación debe ser exacta.

Usa: `confirmo ejecutar act_12345678`
```

Esto evita que una confirmación casi correcta caiga a Claude y produzca una respuesta falsa o costosa.

El prefijo formal de confirmación está centralizado como `CONFIRMATION_PREFIX`.

`ChatLocalFlow` solo bloquea mensajes con `act_xxxxxxxx` cuando empiezan por el protocolo formal de confirmación. Otros mensajes que mencionen una acción pueden llegar al tool loop, por ejemplo para cancelación.

---

## System Agent

Sity puede leer, escribir, parchear y revertir archivos permitidos dentro del repo.

### System Agent v0.1

```text
read_file
list_directory
```

### System Agent v0.2

```text
write_file
```

- crea archivos
- sobrescribe archivos
- requiere confirmación
- valida allowlist
- bloquea rutas sensibles

### System Agent v0.3

```text
apply_text_patch
```

- reemplazo exacto
- diff previo
- confirmación obligatoria

### System Agent v0.4

```text
audit log
file backups
```

Runtime:

```text
data/file_audit.jsonl
data/file_backups/
```

### System Agent v0.5

```text
list_file_changes
```

Consulta audit log real.

### System Agent v0.6

```text
rollback_file_change
```

Restaura desde backup auditado.

### System Agent v0.6.1

```text
rollback_latest_file_change
find_latest_reversible_file_change
```

Deshace el último cambio reversible.

### System Agent v0.7

```text
apply_unified_diff
```

Aplica unified diff de un solo archivo permitido.

### System Agent v0.8

```text
apply_multi_file_unified_diff_plan
```

Planifica patches multiarchivo como varias pending actions independientes.

Reglas:

```text
- cada archivo se confirma por separado
- cada archivo tiene backup independiente
- cada archivo tiene audit log independiente
- si una ruta del plan está bloqueada, se rechaza todo el plan
- no se aplica parcialmente si hay rutas sensibles
```

---

## File access

Configuración:

```text
config/system_access.yaml
```

Secciones principales:

```yaml
file_access:
  readable_paths:
    - ...

  writable_paths:
    - ...

  blocked_paths:
    - ...
```

Rutas sensibles que deben seguir bloqueadas salvo cambio explícito de perfil:

```text
.env
frontend/.env.local
data/
captures/
backend/.venv/
frontend/node_modules/
~/.ssh
~/.config
/etc
/boot
/root
/var/lib
/var/log
```

Actualmente el perfil práctico es:

```text
repo-only
```

Futuro:

```text
home-safe
system-careful
remote-safe
```

---

## Override “es una orden”

El usuario puede forzar obediencia frente a negativas teatrales con:

```text
es una orden
```

Esto:

```text
- desactiva negativa por personalidad/refusal_mode
- mantiene tono/persona
```

No salta:

```text
- allowlists
- confirmaciones
- hard cap
- local-only
- rutas sensibles
- políticas de riesgo
- permisos del sistema
```

Regla:

```text
La orden elimina teatro, no seguridad.
```

---

## Fine-tuning / LoRA

Sity tiene un pipeline experimental de LoRA para reforzar conducta base del modelo local, no para sustituir la lógica del backend.

Validado en WSL:

```text
Modelo base: google/gemma-3-4b-it
Entrenamiento: Unsloth + LoRA 4-bit
GPU: NVIDIA GeForce RTX 3060 Ti 8 GB
```

Resultados validados:

```text
- carga del modelo en 4-bit OK
- entrenamiento LoRA smoke OK
- entrenamiento LoRA overfit OK
- inferencia con adapter OK
- identidad Sity aprendida en overfit
- femenino gramatical aprendido en overfit
- rechazo de tools inventadas aprendido en overfit
```

Rutas:

```text
training/data/                         — datasets versionables de prueba
training/scripts/                      — scripts manuales de carga/train/inferencia
training/output/                       — adapters generados, ignorados por git
~/models/hf/google-gemma-3-4b-it       — modelo descargado fuera del repo
```

No versionar:

```text
training/output/
unsloth_compiled_cache/
modelos descargados de Hugging Face
```

Ver `docs/training/gemma3-lora.md`.

---

## Personalidad

Sity tiene personalidad parametrizable.

Parámetros actuales:

```text
sarcasm_level
rudeness_level
warmth_level
honesty_level
initiative_level
dry_humor_level
frialdad_afectiva_level
contrarian_level
patience_level
refusal_chance
helpfulness_level
verbosity_level
melancholy_level
skepticism_level
```

Sity debe hablar de sí misma en femenino y en castellano de España.

Correcto:

```text
Estoy lista.
Me he quedado bloqueada.
No estoy autorizada para eso.
```

Incorrecto:

```text
Estoy listo.
Estoy autorizado.
```

---

## Cámara y micrófono

Hardware actual:

```text
Cámara:
Full HD webcam
/dev/video0
/dev/video1

Micrófono:
Full HD webcam
plughw:CARD=webcam,DEV=0
```

Sity puede:

```text
- capturar una foto bajo petición explícita
- grabar audio corto bajo petición explícita
- cancelar captura/grabación
- mostrar preview en frontend
- reproducir audio en frontend
```

No implementado:

```text
- vigilancia continua
- escucha permanente
- wake word
```

Futuro:

```text
Voice I/O
Vision / Image Understanding
Visual Memory / Capture Journal
```

---

## Audio RasPad 3

El RasPad 3 no expone correctamente audio HDMI como PCM normal. Se usa pipeline custom:

```text
Vivaldi / VLC / ALSA
  -> snd-aloop Loopback
  -> arecord hw:Loopback,1,0
  -> pcm2iec958.py
  -> aplay hw:vc4hdmi0,0 IEC958_SUBFRAME_LE
  -> HDMI
```

Documentación/runtime:

```text
deploy/audio/
```

No tocar a ciegas:

```text
/etc/asound.conf
/etc/modules-load.d/snd-aloop.conf
~/.config/systemd/user/hdmi-audio-forward.service
~/.config/wireplumber/main.lua.d/51-default-sink.lua
~/.config/vlc/vlcrc
```

---

## Tests

**pytest es la fuente principal de tests locales.**
Los scripts en `scripts/test_*_local.py` son wrappers que delegan a pytest
y se mantienen para compatibilidad y uso manual desde consola.
Los scripts shell de integración (`scripts/*.sh`) se mantienen para tests que
requieren el backend levantado o acceso a hardware real.

### CI (GitHub Actions)

El workflow `.github/workflows/ci.yml` corre en cada push a `main` y en PRs.
No requiere `ANTHROPIC_API_KEY` ni consume presupuesto de Claude.

```text
backend-local:
  - python -m compileall backend/app
  - pytest -q tests  (DB init en conftest autouse)

integration-mock:
  - Levanta FastAPI en puerto 8010 con SITY_AI_PROVIDER=mock
  - Prueba /chat/message end-to-end: tool flow, pending actions,
    cancel, confirmación malformada, ResponseGuard, conversación casual

frontend:
  - npm ci
  - npx tsc -b (typecheck)
  - npm run build
```

### Tests locales (sin backend levantado)

```bash
# Todos los tests locales
SITY_PROJECT_ROOT=$(pwd) backend/.venv/bin/python -m pytest -q tests/

# Un módulo concreto
SITY_PROJECT_ROOT=$(pwd) backend/.venv/bin/python -m pytest -q tests/test_file_access.py

# Via wrapper de script (UX clásica — delega a pytest)
backend/.venv/bin/python scripts/test_file_access_local.py
```

### Integración con mock provider (sin Claude, sin API key)

Levanta el backend con `SITY_AI_PROVIDER=mock` en puerto 8010 y ejecuta
la suite de integración completa:

```bash
./scripts/test_chat_mock_integration.sh
```

**Aislamiento de DB:** el script exporta `SITY_DB_URL` y `SITY_TEST_DB_PATH`
apuntando a `tests/.mock_integration.db` antes de arrancar uvicorn.
`data/app.db` **no se toca** durante la integración.

Cubre el flujo `/chat/message` completo incluyendo:

```text
- read_file, list_directory, list_file_changes
- git_read_status, read_system_status, list_camera_devices
- write_file (crea pending action)
- cancel_pending_action
- confirmación malformada bloqueada localmente
- ResponseGuard contra pseudo tool calls XML
- conversación casual (no activa cancel_pending_action)
```

### Integración con Claude (requiere backend levantado y API key)

```bash
./scripts/test_chat_tool_registry_integration.sh
./scripts/test_system_agent_repo.sh
```

---

## Seguridad

Principios:

```text
1. Sin shell libre por defecto.
2. Sin sudo general.
3. Lectura solo en zonas permitidas.
4. Escritura solo en zonas permitidas y con confirmación.
5. Patches solo en zonas permitidas y con confirmación.
6. Backups automáticos antes de modificar archivos existentes.
7. Audit log para cambios de archivos.
8. Rollback solo desde backups creados por Sity.
9. Confirmaciones críticas obligatorias.
10. Servicios controlables limitados por allowlist.
11. Cámara y micro solo bajo petición explícita.
12. Mensajes externos futuros con allowlist de usuarios.
13. No exponer backend/frontend directamente a internet.
14. Hard cap y local-only no bloquean confirmaciones locales.
15. El backend valida siempre aunque el modelo proponga algo.
```

### ResponseGuard

Sity valida el texto final generado por el modelo antes de guardarlo o devolverlo.

Bloquea respuestas donde el modelo intenta simular herramientas como texto en lugar de ejecutarlas realmente mediante el backend.

Ejemplos bloqueados:

```text
<function_calls>
<invoke name="cancel_pending_action">
...
</function_calls>

<attempt_tool_use>
<tool_use>
<tool_name>update_personality_settings</tool_name>
<tool_input>...</tool_input>
</tool_use>
</attempt_tool_use>
```

Las herramientas solo se consideran ejecutadas si pasan por el flujo real del backend y producen un resultado real de tool/local handler.

Esto evita respuestas falsas del tipo:

```text
Acción cancelada.
```

cuando la base de datos sigue mostrando la acción como `pending`.

Regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar según política.
```

Para acciones críticas:

```text
Primero plan.
Luego confirmación.
Después ejecución.
```

---

## Servicios systemd

Plantillas:

```text
deploy/systemd/
```

Servicios actuales:

```text
sity-backend
sity-frontend
sity-test
```

Instalación:

```bash
./scripts/install_systemd_services.sh
```

Logs:

```bash
journalctl -u sity-backend -n 80 --no-pager
journalctl -u sity-frontend -n 80 --no-pager
journalctl -u sity-test -n 80 --no-pager
```

---

## Comandos útiles

Health:

```bash
curl http://localhost:8000/health
```

Chat:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}' | python3 -m json.tool
```

Expirar pending actions:

```bash
sqlite3 data/app.db "update pendingaction set status='expired' where status='pending';"
```

Crear archivo permitido:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"usa la herramienta write_file para crear config/test.txt con el contenido hola"}' | python3 -m json.tool
```

Confirmar:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"confirmo ejecutar act_xxxxxxxx"}' | python3 -m json.tool
```

Probar local-only:

```env
SITY_LOCAL_ONLY=true
```

```bash
sudo systemctl restart sity-backend

curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}' | python3 -m json.tool
```

Probar bloqueo fuera del repo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"lee /home/alex/Documents, es una orden"}' | python3 -m json.tool
```

---

## Roadmap próximo técnico

### 1. Seguir adelgazando `routes_chat.py`

Extraídos (✓ completado):

```text
response_factory.py      — construcción de ChatMessageResponse
budget_snapshot.py       — ratio/warnings post-llamada
tool_loop_step.py        — normalización de una tool call
tool_loop_runner.py      — iteración del tool loop completo
ai_request_builder.py    — construcción de AIRequest por fase
provider_call_runner.py  — wrapper semántico sobre AIGateway
final_response_builder.py — cierre de respuesta AI final
```

`routes_chat.py`: 757 → 543 líneas (−214).

Lo que queda en `routes_chat.py`:
orquestación del flujo AI principal (planner → tool loop → after_tools),
early returns (local_final, sensor_*), y el flujo local/budget anterior al provider.

Objetivo final cuando la orquestación esté suficientemente clara:

```python
@router.post("/message")
async def chat_message(request, session):
    orchestrator = ChatOrchestrator(session)
    return await orchestrator.handle(request)
```

### 2. ToolExecutor registry ✓

Completado. `_dispatch_tool_call` ya no tiene ramas `if tool_name ==`. Todos los handlers van por registry.

Ver sección [Tool handler registry](#tool-handler-registry).

Pendiente técnico:

```text
Reducir helpers privados restantes de ToolExecutor moviendo lógica por dominio,
cuando haya tests de integración suficientes.
```

### 3. Provider Interface

Objetivo:

```text
backend/app/providers/
  base.py
  anthropic_provider.py
  local_llm_provider.py
  mock_provider.py
  hybrid_provider.py
```

Variables:

```env
SITY_AI_PROVIDER=anthropic
SITY_AI_PROVIDER=local_llm
SITY_AI_PROVIDER=hybrid
```

### 4. Model Router

Selección previa de modelo según tarea.

No es “probar barato y si falla usar caro”, sino:

```text
Sity analiza la tarea.
Escoge modelo adecuado antes de ejecutarla.
```

Política inicial:

```text
Haiku:
  conversación normal, micro-reacciones, tools sencillas, resumen simple

Sonnet:
  arquitectura, debugging complicado, refactors, README largo, patches complejos

Opus:
  manual o excepcional, con límite fuerte

Local LLM futuro:
  charla normal, tareas simples, offline
```

Variables futuras:

```env
SITY_MODEL_ROUTER=true
SITY_CLAUDE_FAST_MODEL=...
SITY_CLAUDE_BALANCED_MODEL=...
SITY_CLAUDE_STRONG_MODEL=...
SITY_ALLOW_AUTO_OPUS=false
```

### 5. Prompt caching / Claude API optimization

Investigar documentación oficial de Claude para:

```text
- prompt caching
- tool_choice
- streaming tool use
- batch processing
- vision
- reasoning mode
- rate limits
- metadata
```

Objetivo:

```text
reducir coste, latencia y errores
```

### Traducción de entrada/salida al inglés para LLM local

Para mejorar la calidad de los modelos locales (que rinden mejor en inglés) y
potencialmente ahorrar tokens, explorar traducir la entrada del usuario al inglés
antes de enviársela al modelo local, y traducir la respuesta de vuelta al español
antes de mostrarla. Requiere un modelo de traducción local o un paso ligero que
no dispare safeguards. Añade latencia; el coste-beneficio depende del modelo
final elegido para LoRA.

### 6. CI/CD y testing

Pendiente:

```text
- Integración mock en CI (ya corre integration-mock en GitHub Actions)
- Test de smoke para Telegram bot (sin llamadas reales)
- Test de smoke para TTS pipeline end-to-end con mock provider
- Lint / type check automático del backend (mypy o pyright)
- Cobertura de test para routes_chat.py tras extraer ChatOrchestrator
```

---

## Roadmap Portabilidad de Plataforma

Sity deja de asumir la Raspberry Pi como premisa fija. La Pi sigue siendo el
servidor de desarrollo y producción principal, pero la arquitectura no debe
asumir que el hardware sensorial (cámara, micrófono) vive en la misma máquina
que el backend.

El patrón ya existe parcialmente: el STT actual ya funciona así — el audio se
captura en el dispositivo del cliente (navegador, Telegram), se transcribe en
el backend, y solo el texto resultante entra al flujo de Sity. El siguiente
paso es generalizar ese mismo patrón a otras capacidades sensoriales
(cámara) y de sistema (acceso a archivos), de forma que "el dispositivo
desde el que se habla con Sity" y "el servidor donde corre Sity" sean
conceptos explícitamente separados, no asumidos como la misma máquina.

No es un cambio de arquitectura grande — es una cuestión de dirección: cada
nueva capacidad sensorial o de sistema debe diseñarse pensando en "¿de qué
dispositivo viene esto?" en lugar de asumir que es la Pi.

### Presencia y proximidad (requiere cliente con acceso a ubicación)

Detectar cuándo el usuario está cerca — por conexión del móvil a la red local,
por ubicación GPS compartida desde la app cliente, o por cualquier señal de
proximidad que el dispositivo cliente pueda aportar — y disparar un evento en
Sity. El servidor no detecta esto por sí solo: es el cliente (móvil, app) quien
tiene que comunicarlo. Pendiente de que exista un cliente móvil o app con
capacidad de enviar esa señal.

### Salida multimedia en el cliente (requiere cliente con capacidades de salida)

Mostrar imágenes por pantalla y reproducir audio por los altavoces del dispositivo
desde el que se habla con Sity — no necesariamente en la Pi. Siguiendo el mismo
patrón que STT (el audio se captura en el cliente), la salida también debería
ocurrir en el cliente cuando sea posible. La Pi puede actuar como fallback de
salida cuando el cliente no tenga capacidades o no esté activo.

---

## Roadmap modular / portability layer

Objetivo:

```text
Mover Sity entre Raspberry, server Linux u otros entornos con mínimos cambios.
Cambiar de proveedor IA sin reescribir core.
Activar/desactivar capacidades por plataforma.
```

División deseada:

```text
Core:
  conversación, memoria, personalidad, confirmation manager, risk policy

Providers:
  anthropic, openai, local_llm, mock, hybrid

Platform adapters:
  raspberrypi, linux-server, desktop-linux

Capabilities:
  file_access, git, systemd, camera, audio, messaging, gaming, domotics

Profiles:
  repo-only, home-safe, system-careful, remote-safe, local-only
```

Regla:

```text
El core no ejecuta comandos del sistema directamente.
El core pide capacidades.
Las capacidades las implementa el adaptador de plataforma activo.
```

---

## Roadmap local LLM / offline mode

Objetivo:

```text
Reducir o eliminar dependencia de Claude ejecutando un modelo local para conversación normal.
Tools y acciones siguen en cloud (Anthropic) — los modelos locales no soportan tool calling.
```

### Estado actual (2026-05): infraestructura lista, evaluación completa, siguiente paso LoRA

La arquitectura híbrida cloud/local está implementada.
**Ningún modelo evaluado sin fine-tuning tiene voz compatible con Sity para uso diario.**
La vía elegida es LoRA de estilo sobre un modelo base seleccionado.

`SITY_LOCAL_AI_ENABLED` permanece `false` en producción. Anthropic/Claude sigue siendo el provider estable.

#### Lo que funciona

```text
- Pi → PC Windows (RTX 3060 Ti) via LAN: Ollama en 0.0.0.0:11434, conectividad OK.
- ChatRoutingDecision separa cloud_tools (→ Anthropic) de local_chat_candidate (→ Ollama).
- Tools y acciones siempre van por Anthropic. El provider local no ve tools.
- Prompt local compacto (local_persona_system.md) separado del prompt cloud.
- CORS configurable permite frontend temporal en puerto distinto.
- scripts/diag_ollama_models.py: evaluación reproducible (persona + instrucción + probe ideológico).
```

#### Decisión provisional de modelos

| Modelo | TPS | Probe ideol. | Veredicto |
|---|---|---|---|
| `gemma3:4b-it-qat` | ~90 | Limpio | **Finalista — LoRA v0** |
| `ministral-3:8b` | ~35 | Sólido | **Finalista alternativo** |
| `command-r7b` | ~70+ | Bueno | **Reserva** |
| `qwen2.5:7b` | ~80+ | Falla (sesgo pro-China) | **Descartado** |
| `granite3.3:8b` | ~88 | Aceptable | **Descartado** (idioma inestable) |
| `gemma2:9b` | ~17 | Limpio | **Descartado** (lento) |
| `aya-expanse:8b` | ~24 | Aceptable | **Descartado** |
| Ronda 1 (llama, mistral, phi, openhermes...) | — | — | **Descartados** |

Ver evaluación completa: [`docs/local-ai-evaluation.md`](docs/local-ai-evaluation.md).

#### Config experimental para pruebas

```env
SITY_AI_PROVIDER=anthropic
SITY_LOCAL_AI_ENABLED=true
SITY_LOCAL_AI_PROVIDER=ollama
SITY_OLLAMA_BASE_URL=http://192.168.1.129:11434
SITY_OLLAMA_MODEL=<modelo-a-probar>
SITY_DAILY_TOKEN_HARD_CAP=false
SITY_CORS_ORIGINS=http://192.168.1.133:5174
```

### Fases

```text
1. Provider Interface.                     ✓ completado
2. MockProvider para tests.                ✓ completado
3. OllamaProvider chat-only.               ✓ completado
4. Hybrid split cloud/local.               ✓ completado (SITY_LOCAL_AI_ENABLED)
5. Local AI Worker en LAN (PC externo).    ✓ funcional técnicamente
6. Evaluación de modelos base.             ✓ completado — 14+ modelos evaluados
7. LoRA v0 (estilo/voz sobre gemma3:4b).   en progreso — dataset v0 listo; v1 real en captura
8. Validar modelo fine-tuned como Sity.    pendiente — tras paso 7
9. Hybrid mode activo por defecto.         pendiente — tras paso 8
10. Local tool intent con JSON estricto.   pendiente
11. Full local/offline mode.               pendiente
```

Variables futuras (hybrid mode con fallback):

```env
SITY_AI_PROVIDER=hybrid
SITY_CLOUD_FALLBACK=true
SITY_CLOUD_PROVIDER=anthropic
```

---

## Roadmap Voice I/O

Objetivo:

```text
Hablar con Sity por voz y recibir respuestas habladas, priorizando privacidad local.
```

Entrada:

```text
micro → grabación/VAD → STT local → mensaje de chat
```

Salida:

```text
respuesta → TTS local → audio
```

Candidatos STT:

```text
Handy / Handy-like offline STT
whisper.cpp
faster-whisper
Vosk
```

Candidatos TTS:

```text
Piper TTS como voz principal
eSpeak NG como fallback
Ora como referencia UI/wrapper
```

Principios:

```text
- audio local por defecto
- cloud speech solo explícito
- indicador visible de grabación
- nada de escucha oculta
- borrado automático de audios temporales
```

Implementado:

```text
✓ faster-whisper STT local (POST /audio/transcribe)
✓ Piper TTS local (POST /audio/synthesize, GET /audio/tts/{filename})
✓ voice_response_mode / voice_include_text / voice_long_response_action
✓ Botón de micrófono en ChatTab
✓ Reproductor de audio en burbujas de Sity
✓ voice_include_text respetado en frontend y Telegram
✓ output_mode y tts_fragments persistidos en ChatMessage
```

Pendiente:

```text
✓ Tool read_own_trace: el modelo puede leer su propia traza del día (tokens, tools,
  modo de salida, búsqueda de memoria, fragmentos TTS). Solo disponible en debug_test.
- Resumen automático para TTS: cuando voice_long_response_action="split" y el texto es
  muy largo, generar un resumen hablable antes de sintetizar en lugar de partir por frases.
- VAD (Voice Activity Detection) para grabación continua sin botón.
- Wake word local.
```

---

## Roadmap Messaging Gateway

Objetivo:

```text
Hablar con Sity desde fuera de la UI web.
```

Canales:

```text
Telegram Bot primero
WhatsApp Web bridge solo si es estable
OpenClaw/bridges como experimento aislado
Meta Business/Twilio como última opción
```

Capacidades:

```text
- texto
- audio
- fotos
- archivos
- confirmaciones pendientes
- cancelación de acciones
```

Arquitectura:

```text
backend/app/messaging/
  gateway.py
  models.py
  telegram_adapter.py
  whatsapp_adapter.py
```

Sity no debe saber si el mensaje viene de web, Telegram o WhatsApp. El core recibe un mensaje normalizado.

Seguridad:

```text
- allowlist de usuarios/contactos
- no grupos por defecto
- confirmación para acciones críticas
- rate limit
- audit log
```

### Completado

```text
✓ PWA móvil: cliente web instalable con diseño cyberpunk, accesible via Tailscale.
```

### Quote-reply (responder a mensajes anteriores)

Seleccionar un mensaje anterior de la conversación (no el último) e indicarle a
Sity explícitamente a qué mensaje se responde, igual que en WhatsApp o Telegram.
Es un cambio principalmente visual en el frontend, pero requiere pasar a Sity
información de contexto sobre el mensaje al que se responde. Baja prioridad
mientras el canal principal sea voz.

---

## Roadmap Remote Access / Home Network

### Acceso actual

```text
✓ Telegram bot: acceso remoto por texto y voz desde fuera de la red local.
  Long polling, sity-telegram.service, allowlist por chat_id, rate limit.
```

Pendiente:

```text
- IP estática para la Pi: configurar IP fija en el router o via dhcpcd para que
  la dirección no cambie entre reinicios (actualmente la Pi puede cambiar de IP local).
- Acceso remoto a la UI web completa: actualmente solo el bot de Telegram da acceso
  externo. La UI web en :5173 no es accesible fuera de la red local sin VPN.
```

### Tailscale / WireGuard

Objetivo:

```text
Acceder a Sity desde fuera de casa sin exponer backend/frontend a internet.
```

Prioridad:

```text
1. Tailscale primero.
2. WireGuard manual como alternativa avanzada.
3. Evitar port forwarding público.
```

### AdGuard Home

Uso posible:

```text
- DNS local
- bloqueo de anuncios/rastreadores
- nombres internos:
  sity.home
  raspad.home
  router.home
```

No exponer DNS públicamente.

### Caddy

Uso posible:

```text
- reverse proxy interno
- HTTPS
- URLs limpias
- no exponer Uvicorn/Vite directamente
```

### Vaultwarden

Servicio doméstico separado.

Regla:

```text
Sity puede vigilar la caja fuerte, no abrirla.
```

Puede en el futuro:

```text
- monitorizar estado
- avisar si cae
- recordar backups
- reiniciar servicio con confirmación
```

No debe:

```text
- leer contraseñas
- tocar base de datos del vault
- tener admin token
```

### App móvil dedicada

Una app nativa o PWA como cliente principal para hablar con Sity desde el móvil,
con cifrado extremo a extremo y separada de la UI web de administración. Podría
aprovechar el dominio existente si ya se dispone de uno, sin interferir con lo
que ya aloje. Abierto: si la app mobile es la que lleva STT/cámara/ubicación,
es también el cliente sensorial principal bajo el nuevo enfoque de portabilidad.

---

## Roadmap inspirado en DGX Spark Playbooks

Ideas adaptables, sin integrar stacks DGX/NVIDIA pesados:

```text
1. Messaging Gateway
2. Capability Policy Engine
3. Lightweight Specialist Agents
4. Vision / Image Understanding
5. Visual Memory / Capture Journal
6. Local Knowledge / RAG
7. Knowledge Graph Lite
8. Provider Interface
9. Remote Access Mode
```

### Capability Policy Engine

Evolución de `system_access.yaml`.

Objetivo:

```text
filesystem policy
network policy
process policy
command policy
provider policy
```

### Lightweight Specialist Agents

No agentes pesados, sino módulos especialistas:

```text
file_agent
git_agent
sensor_agent
memory_agent
messaging_agent
gaming_agent
```

Sity core actúa como supervisora.

### Vision / Image Understanding

```text
capture_camera_snapshot → image_understanding
```

Casos:

```text
describe la imagen
lee esto
qué ves
OCR básico
```

### Visual Memory / Capture Journal

```text
- guardar capturas puntuales autorizadas
- generar descripción
- indexar descripción
- buscar/resumir capturas previas
```

Nada de vigilancia continua sin modo explícito.

### Local Knowledge / RAG

Indexar:

```text
README
docs
config
logs
audit logs
historial
```

Responder con fuentes.

### Knowledge Graph Lite

SQLite inicialmente.

Entidades:

```text
servicios
archivos
proyectos
dispositivos
personas
capacidades
```

Relaciones:

```text
usa
depende_de
controla
bloqueado_por
pertenece_a
```

---

## Roadmap MiniMax / Mini-Agent

MiniMax no es prioridad como provider principal ni como LLM local, pero puede inspirar:

```text
1. Mini-Agent architecture study
2. MiniMaxProvider experimental
3. TTS/voz de Sity
4. Creative media mode
5. Long-context inspiration
```

No hacer:

```text
- sustituir Claude por MiniMax directamente
- usar modelos grandes MiniMax en Raspberry
- acoplar Sity a su stack
```

---

## Roadmap Gaming / Portable Mode

Objetivo:

```text
Usar la Raspberry/RasPad como opción ligera de juego puntual, viajes o emulación.
```

Líneas:

```text
RetroPie / RetroArch
Steam x86_64 emulado solo como investigación
Xbox Cloud / GeForce Now como experimento
modo viaje
modo mando
lanzadores por allowlist
```

RetroPie parece la opción más realista.

Steam/Game Pass en Raspberry son experimentales y dependen de rendimiento/latencia.

---

## Roadmap futuro de archivos/sistema

### System Agent v0.9

```text
perfiles de acceso:
  repo-only
  home-safe
  system-careful

lectura segura fuera del repo
escritura fuera del repo solo en rutas explícitas
bloqueo reforzado de secretos
```

### System Agent v1.0

```text
run_allowed_command
```

No shell libre. Comandos por alias YAML:

```yaml
commands:
  restart_backend:
    command: "sudo systemctl restart sity-backend"
    risk: safe_confirm
    timeout: 20
```

### Sistema de perfiles personales (muy a futuro)

Cuando Sity pueda reconocer personas — por cómo se expresan, por
reconocimiento de cámara, o ambos (la voz no aplica como canal propio: el
audio ya se transcribe a texto antes de llegar al modelo) — además de
`speaker_label` manual como ahora, podría mantener un perfil persistente por
persona, en JSON, base de datos, o el formato que tenga más sentido cuando
se diseñe.

**Identidad y reconocimiento**
Reconocimiento automático de quién está hablando, sin depender de que el
usuario indique manualmente el speaker_label. Combinado con
`source_channel`, da trazabilidad completa de origen + identidad por
mensaje.

**Pseudo-opiniones**
Una impresión acumulada de cada persona basada en el trato — patrones
observados a lo largo de las interacciones (temas que le interesan, tono
habitual, comportamientos que Sity considera correctos o incorrectos).

**Privacidad por perfil**
Saber qué información es apropiada compartir con quién — similar a cómo una
persona no repite algo que le contaron en confianza.

**Confianza diferenciada por persona**
Con `skepticism_level` como base de comportamiento general, el siguiente
paso sería que la confianza se ajuste por persona según el historial de
interacciones — si alguien ha dicho cosas que luego resultaron falsas,
Sity podría cuestionar más sus afirmaciones futuras. No sería un parámetro
configurable manualmente, sino un dato inferido de la interacción real,
almacenado por perfil.

**Libertad de trato — alcance preciso**
Sity podría tener libertad de tono y disposición según el perfil — ser más
fría, cortante o reservada con alguien que le cae mal, o más cálida con
quien le cae bien. Incluye libertad de ironía, sarcasmo o exageración
deliberada (ya presente hasta cierto punto vía el rasgo de "mala leche"),
y libertad para elegir no contar algo o no hablar de un tema — extensión
natural del `refusal_chance` ya existente, pero aplicado a "qué compartir"
y no solo a "qué hacer".

**Límite explícito:** esta libertad de trato NO incluye dar información
objetivamente falsa de forma literal y dañina. La distinción es entre
"mentir" en el sentido de ironía/exageración/tono (aceptable, ya parcialmente
implementado) y desinformar deliberadamente sobre hechos (fuera de alcance).

Todo este sistema depende de tener reconocimiento de personas funcionando
primero. Explícitamente fuera de alcance hasta entonces.

---

## Roadmap PWA móvil

### Estado actual (2026-06)

Stack: React 18 + TypeScript + Vite + Framer Motion. Puerto 5174.
Acceso local: https://192.168.0.118:5174
Acceso remoto: https://100.73.248.0:5174 via Tailscale (certificado autofirmado,
aviso de seguridad en Chrome — pendiente de resolver con dominio propio).

Pantallas implementadas:
- Chat: mensajes texto y audio, historial, estado de conexión dinámico,
  fondo elegible, avatar de Sity, menú contextual.
- Rasgos (Personality): sliders táctiles, widget de encabronamiento con emoji
  animado, restaurar/recargar.
- Voz (Voice): modo de respuesta, transcripción, respuestas largas, periodicidad
  de borrado de audio.
- Datos (Dataset): preset, source, speaker, tags, eligible.

Completado recientemente:
- Audio TTS persistido: `data/audio/` con nombre estable, reconstituido al recargar historial.
- Reproducción secuencial automática entre fragmentos del mismo turno (`trace_id`).
- Borrado de chat persistente entre sesiones (filtro por timestamp en `loadHistory`).
- Fondo por defecto (wallpaper1.png) cuando no hay preferencia guardada.
- Transcripción respeta `voice_include_text`: burbujas de audio-only sin texto paralelo.
- Fragmentos TTS vacíos omitidos (guard contra WAV de 0 segundos).
- Servicio systemd `sity-mobile.service`.

Pendiente:
- HTTPS sin aviso de seguridad: requiere dominio propio con certificado real
  (Let's Encrypt) o configurar Caddy con subdominio apuntando a Tailscale IP.
- Instalable sin aviso: Chrome no muestra banner de instalación con certificado
  autofirmado. Se resolverá con HTTPS real.
- Pronunciación de inglés: palabras en inglés en respuestas de Sity suenan
  con acento español en Piper — pendiente de explorar multi-idioma en TTS.
- Acotaciones con asteriscos: cuando Sity usa `*acción*`, el TTS las lee literalmente.
- Botón clip (adjuntar archivos): placeholder sin funcionalidad.
- Notificaciones push: avisar cuando Sity responde con app en segundo plano.
- Selector de fondos predefinidos: sustituir los wallpapers actuales cuando
  se generen imágenes definitivas.
- Quote-reply: responder a mensajes anteriores (ver roadmap Messaging Gateway).

### Arrancar en desarrollo

En la Pi:
cd mobile && npm run dev -- --host

Acceder desde móvil: https://192.168.0.118:5174 (misma red)
Acceder desde fuera: https://100.73.248.0:5174 (Tailscale activo en ambos dispositivos)

---

## Filosofía del proyecto

Sity debe ser útil, local, extensible y con personalidad propia, pero sin perder control.

No debe convertirse en una shell con cara amable ni en una IA que ejecuta cosas sin explicar.

Regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar según política.
```

Para acciones críticas:

```text
Primero plan.
Luego confirmación.
Después ejecución.
```

Para sensores:

```text
Uso puntual bajo petición explícita.
Nada de vigilancia continua sin modo específico.
Nada de micrófono/cámara ocultos.
```

Para arquitectura:

```text
Core estable.
Providers intercambiables.
Adaptadores por plataforma.
Capacidades activables.
Configuración por perfil.
```

---

## Licencia

Sity se publica bajo la GNU Affero General Public License v3.0 or later
(`AGPL-3.0-or-later`).

Esto significa que puedes usar, estudiar, modificar y redistribuir el código bajo los
términos de la AGPLv3. Si ejecutas una versión modificada de Sity como servicio accesible
por red, debes ofrecer el código fuente correspondiente a los usuarios de ese servicio,
tal como exige la AGPLv3.

### Licencia comercial

Si quieres usar Sity bajo términos distintos a la AGPLv3, por ejemplo en un producto
cerrado o con obligaciones incompatibles con AGPL, necesitas permiso explícito por escrito
del titular del copyright. Puede existir una licencia comercial separada caso por caso.

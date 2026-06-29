# Arquitectura de Sity

Última actualización: 2026-06-28 (model router semi-automático, limpieza TTS markdown, pronunciación fonética en voz, prompt caching).

Este documento resume la arquitectura objetivo y la arquitectura implementada de Sity.

## Principio base

```text
Sity interpreta.
Backend valida.
Backend ejecuta.
```

El modelo no es autoridad. El backend decide si una acción es válida, segura, permitida y si requiere confirmación.

## Módulos actuales

### Backend

FastAPI como API principal.

Responsabilidades:

- chat;
- memoria;
- tools;
- confirmaciones;
- proveedores IA;
- sensores;
- eventos SSE;
- presupuesto;
- runtime config.

### Frontend

Frontend web modular.

Responsabilidades:

- chat;
- settings;
- debug (trazas y eventos recientes);
- dataset (Dataset Capture + DatasetStats);
- previews de cámara/audio;
- cancelación de acciones;
- interacción táctil futura.

#### Campo de texto del chat

El campo de entrada del chat es un `<textarea>` (no `<input>`) con estas propiedades:

- **Shift+Enter** inserta un salto de línea; **Enter** (solo) envía el mensaje.
- **Auto-resize**: el área crece verticalmente línea a línea conforme se escribe, usando `useEffect` + `el.style.height = el.scrollHeight + "px"`. `maxHeight: 12rem` (~8 líneas); a partir de ahí aparece scroll vertical oculto. Al enviar (cuando `chatInput` se vacía), vuelve al tamaño inicial (`rows={1}`).
- **Scrollbar nativa oculta** vía CSS global (`scrollbar-width: none` + `::-webkit-scrollbar { display: none }` en `index.css`).
- El contenedor flex usa `items-end` para que los botones (micrófono, cancelar, enviar) se mantengan alineados al borde inferior cuando el textarea crece.

#### Timestamps en mensajes

Cada burbuja de mensaje muestra la hora/fecha de creación debajo del contenido, siempre visible (no solo en hover):

| Caso | Formato | Ejemplo |
|---|---|---|
| Hoy | Solo hora | `14:32` |
| Ayer | Prefijo + hora | `Ayer 14:32` |
| Antes | Día + mes + hora | `15 jun 14:32` |

Implementación: `formatTimestamp(iso: string)` en `ChatTab.tsx` (helper module-level). El campo `created_at` viene del backend en `GET /chat/current` (campo `ChatMessageItem.created_at`) y se guarda en `ChatEntry` del hook. Para mensajes nuevos enviados en la sesión actual, se asigna `new Date().toISOString()` al crear la entrada.

`ChatHistoryItem` en `chatApi.ts` y `ChatEntry` en `useChat.ts` tienen `created_at?: string`. `ChatMessageItem` en `schemas.py` tiene `created_at: Optional[datetime]`, rellenado desde `row.created_at` en `GET /chat/current`.

### Audio STT

Transcripción de voz a texto vía `faster-whisper` (local, CPU, modelo `small`, español).

Modelo STT: `small` (cambiado desde `base` para mejorar precisión con acentos regionales, especialmente andaluz). Mayor consumo de CPU (~100% durante transcripción) con latencia de 10-20s en Pi — asumible para el uso previsto.

- `POST /audio/transcribe` — recibe `multipart/form-data` con un archivo de audio, devuelve `{ transcript, duration_ms }`. No llama a servicios externos.
- El modelo se carga de forma perezosa en el primer uso (`WhisperModel` dentro de `get_model()`). Singleton con lock por hilo.
- `compute_type="int8"` para eficiencia en Raspberry Pi.
- La ruta es origin-agnostic: la llaman frontend web, PWA móvil, o cualquier cliente futuro.

Metadata de voz por mensaje:

- `input_mode: "voice" | "text"` — guardado en `ChatMessage`, invisible al modelo.
- `voice_transcript_original` — texto bruto de Whisper antes de edición de usuario, nunca en el prompt.
- `edit_distance_pct` — `1 - SequenceMatcher.ratio()` entre original y texto enviado. Calculado en `routes_chat.py`.

Archivos:

```text
backend/app/audio/transcriber.py       — WhisperModel singleton + transcribe_bytes()
backend/app/audio/edit_distance.py     — compute_edit_distance_pct()
backend/app/api/routes_audio.py        — POST /audio/transcribe
config/default_config.yaml             — audio.stt_model / stt_device / stt_language
frontend/src/hooks/useVoiceInput.ts    — MediaRecorder hook → POST /audio/transcribe
frontend/src/api/chatApi.ts            — transcribeAudio() + voice options en sendChatMessage()
```

Tests: `tests/test_edit_distance.py`, `tests/test_audio_transcribe.py`, `tests/test_telegram_voice.py`. Sin llamadas reales a Whisper ni a Telegram.

**Voice mode guard (restricción estructural):** cuando `input_mode == "voice"`, `toolset_selector.py` elimina todos los tools de `SENSES_TOOLSET` antes de devolver la selección. El dominio `senses` tampoco aparece en `activated_domains`. Esta restricción se aplica en el backend independientemente del criterio del modelo. Además, `PromptContextBuilder` inyecta `[input_mode: voice]` en el bloque de contexto del mensaje, y `persona_system.md` incluye una regla explícita para interpretar preguntas de confirmación de canal sin disparar tools de captura.

### Audio TTS (salida de voz)

Síntesis de voz con Piper TTS (binario nativo, sin wrapper Python). Modelo: `es_ES-sharvard-medium`, voz femenina, archivos `.onnx` y `.onnx.json` bajo `backend/data/tts_models/`.

- `POST /audio/synthesize` — recibe `{ text: str }`, devuelve WAV. Devuelve 422 si `len(text) > tts_long_response_chars` (default 500).
- `GET /audio/tts/{filename}` — sirve archivos TTS temporales generados por el pipeline de chat.
- Piper se invoca como subproceso (`subprocess.run`). Sin dependencia Python adicional.

Configuración en `config/default_config.yaml`:
```yaml
audio:
  tts_voice: es_ES-sharvard-medium
  tts_voice_speaker: female
  tts_long_response_chars: 500
  tts_models_dir: data/tts_models
  # tts_piper_bin: /ruta/opcional    # solo si piper no está en el venv
```

`tts_piper_bin`: el binario `piper` se busca automáticamente como `Path(sys.executable).parent / "piper"` (relativo al venv activo). Solo es necesario configurarlo explícitamente si piper está en otra ubicación.

`tts_voice_speaker`: acepta un nombre legible (`"female"`, `"male"`, `"f"`, `"m"`) o un entero numérico. El mapeo `_SPEAKER_NAME_MAP = {"female": 1, "f": 1, "male": 0, "m": 0}` convierte nombres a IDs de speaker para el flag `--speaker` de piper. Este mapeo es específico del modelo `es_ES-sharvard-medium`; con otros modelos los IDs pueden variar.

Para cambiar de voz: sustituir `tts_voice` y los archivos `.onnx`/`.onnx.json` en `tts_models_dir`. Descargar desde `https://huggingface.co/rhasspy/piper-voices`.

**Lógica de síntesis en el pipeline de chat (`routes_chat.py`):**

`_should_synthesize(voice_response_mode, input_mode)` decide si sintetizar:
- `always` → siempre
- `never` → nunca
- `symmetric` → solo cuando el usuario envió voz (`input_mode == "voice"`)

`_attach_tts_artifacts` sintetiza y añade artifacts `type="audio"` a `ChatMessageResponse`. Para respuestas largas:
- `voice_long_response_action == "split"` → `split_by_sentences()` divide en fragmentos ≤ `tts_long_response_chars`, un artifact por fragmento.
- `voice_long_response_action == "text_only"` → no se sintetiza, solo texto.
- Fragmentos vacíos se omiten (guard contra WAV de 0 segundos).
- Errores de síntesis se loguean como WARN sin romper la respuesta.

**Voice settings** (persistidas en tabla `Setting`):
- `voice_response_mode: "always" | "never" | "symmetric"` (default `symmetric`)
- `voice_include_text: bool` (default `true`) — si es `false`, la respuesta se entrega solo como audio, sin texto visible.
- `voice_long_response_action: "split" | "text_only"` (default `text_only`)
- `audio_cleanup_days: int` (default `7`) — días de retención de archivos TTS persistidos.

Expuestas en `GET/PUT /settings/voice`. Configurables desde el tab "Voice" del frontend y de la PWA móvil.

**`_attach_tts_artifacts`** devuelve `Optional[tuple[int, Optional[str]]]`: `(n_fragmentos, audio_filename_del_primero)`, o `None` si se omitió TTS. El caller persiste `audio_filename` en `ChatMessage` y hace `session.commit()` explícito — sin mutación del modelo Pydantic de respuesta.

### Audio persistente

Cuando `persist_tts: true` en `config/default_config.yaml` (sección `audio`), los archivos `.wav` se escriben en `data/audio/` con nombre `tts_{YYYYMMDDTHHMMSS}_{trace_id[:16]}.wav`. Esta ruta es estable entre reinicios. Al recargar la historia vía `GET /chat/current`, `ChatMessageItem.audio_filename` permite reconstituir la URL `/audio/stored/{filename}`.

Endpoints adicionales en `routes_audio.py`:
- `GET /audio/stored/{filename}` — sirve archivos TTS persistidos. Valida nombre sin traversal.
- `POST /audio/cleanup` — elimina archivos en `data/audio/` con mtime > N días (default 7). Se llama en `on_startup()`.

`ChatMessage.audio_filename: Optional[str]` — campo añadido vía migración idempotente en `_migrate_chatmessage()`. Contiene el nombre de archivo del primer fragmento TTS del turno, o `None` si no hubo síntesis persistida.

**Frontend:** reproductor `<audio controls>` en mensajes de Sity con artifacts de audio. Cuando `voice_include_text == false` y el mensaje tiene artifacts de audio, el texto de la burbuja se oculta (`hideText` en `ChatTab.tsx`) y solo se muestra el reproductor.

**PWA móvil:** burbujas `AudioMessageBubble` con player de seek, progreso y duración. Al recargar la historia, los mensajes con `audio_filename` se reconstruyen como burbujas de audio (`audioUrl: /audio/stored/{filename}`). Reproducción coordinada entre fragmentos del mismo turno: `isActive`/`nextAudioId` propagados desde `ChatScreen`; el `useEffect([isActive])` en `AudioPlayer` usa `a.paused` (DOM real-time) para evitar closures obsoletos. `handleAudioEnded` usa forma funcional del setter para protegerse de eventos `ended` tardíos de la burbuja anterior.

### Limpieza de texto antes de síntesis

`_clean_text_for_tts(text)` en `routes_chat.py` elimina marcadores markdown
(**negrita**, *cursiva*, `código`, ## encabezados) antes de pasar el texto a
Piper. El texto que se guarda en BD y se devuelve al cliente conserva el
formato original.

### Pronunciación de palabras en inglés

Cuando `output_mode: voice`, `persona_system.md` instruye a Sity a escribir
palabras técnicas en inglés con su pronunciación fonética en español
(pipeline → "paip lain", deploy → "diploi", etc.) para que Piper las
pronuncie correctamente.

**Telegram:** si la respuesta contiene artifacts de audio, el bot los descarga (`gateway.get_tts_artifact`) y los envía como audio vía `reply_audio`. Cuando `voice_include_text == false`, el texto no se envía (`reply(text)` se omite). El `SityGateway` incluye siempre `"source_channel": "telegram"` en el body del POST.

Archivos:
```text
backend/app/audio/synthesizer.py       — TtsConfig, synthesize_text() via subprocess piper
backend/app/audio/tts_splitter.py      — split_by_sentences()
backend/app/api/routes_audio.py        — POST /audio/synthesize, GET /audio/tts/{filename},
                                         synthesize_to_tmp(), synthesize_to_persistent(),
                                         GET /audio/stored/{filename}, POST /audio/cleanup
backend/app/settings/schemas.py        — VoiceSettings (incl. audio_cleanup_days)
backend/app/settings/settings_service.py — get/set_voice_settings()
backend/app/api/routes_settings.py     — GET/PUT /settings/voice
frontend/src/api/voiceApi.ts           — getVoiceSettings(), updateVoiceSettings()
frontend/src/components/VoiceSettingsTab.tsx — UI de configuración de voz
mobile/src/screens/VoiceScreen.tsx     — UI móvil de voz (incl. audio_cleanup_days)
mobile/src/components/AudioMessageBubble.tsx — burbuja de audio con player y coordinación
config/default_config.yaml             — audio.persist_tts, audio.cleanup_days
```

Tests: `tests/test_tts.py` — 28 tests, sin llamadas reales a piper. `tests/test_chat_message_metadata.py` — 29 tests cubriendo output_mode, tts_fragments y source_channel. `tests/test_audio_persistence.py` — 11 tests cubriendo audio_filename DB field, endpoints stored/cleanup, synthesize_to_persistent().

### Acceso remoto

El acceso remoto se resuelve con PWA + Cloudflare Tunnel (ver sección Infraestructura).
El bot de Telegram fue eliminado en 2026-06-28.

### Tools

Las tools están registradas por dominio mediante registry.

El backend valida y ejecuta. El texto del modelo no cuenta como ejecución.

### Providers IA

Interfaz:

```text
AITextProvider
```

Providers actuales:

- `anthropic`: default estable cloud.
- `mock`: tests/CI.
- `ollama` / `local`: experimental chat-only.

Ollama no soporta tools.

### TimeContext

Se añade contexto temporal por turno:

- hora actual;
- deltas;
- categoría de gap temporal.

Permite respuestas sensibles al paso del tiempo.

### Presupuesto de tokens

El gasto diario de tokens se controla con `daily_token_budget`, definido en la sección **`usage`** del config (`config/default_config.yaml`). **No** está en la sección `tokens`.

```yaml
usage:
  daily_token_budget: 1000000   # presupuesto diario en tokens
  warning_threshold: 0.80
  critical_threshold: 0.95

tokens:
  max_recent_turns: 4           # historial inyectado al modelo
  max_relevant_memories: 5
  max_input_tokens_interactive: 6000
```

- **Hard cap**: `SITY_DAILY_TOKEN_HARD_CAP=true` (env var, default `false`). Cuando está activo, el backend rechaza peticiones si se ha superado el presupuesto.
- **Reset del contador**: `get_today_token_usage()` en `chat_persistence.py` calcula `today_start_utc` con la secuencia `datetime.now().astimezone().replace(hour=0,...).astimezone(timezone.utc).replace(tzinfo=None)`. Esto convierte la medianoche hora local de la Pi (UTC+2 en verano) a su equivalente UTC naive antes de comparar contra `AIUsage.created_at`, que se almacena como UTC naive. El reset efectivo ocurre a las 00:00 **hora española** (= 22:00 UTC del día anterior en verano). **Invariante crítico**: `/debug/budget` y el hard cap en `routes_chat.py` deben usar exactamente la misma lógica de `today_start_utc` — si divergen, el contador visible en frontend y el corte real del hard cap no coinciden. Actualmente ambos delegan a `get_today_token_usage(session)`, lo que garantiza la consistencia.

### Módulos `backend/app/chat/`

El paquete `chat/` contiene lógica de orquestación extraída de `routes_chat.py`. `routes_chat.py` es una capa HTTP fina (164 líneas); toda la lógica de negocio vive en módulos pequeños y testeables.

```text
budget_guard.py           — guards locales (SITY_LOCAL_ONLY, hard cap)
local_flow.py             — respuestas locales pre-AI (confirmaciones, expirados, ambigüedad)
pending_action_runner.py  — ejecución de acciones pendientes confirmadas
toolset_selector.py       — selección de toolset y history_limit
prompt_context.py         — prior_messages, user_message_with_history, contexto de memoria
ai_request_builder.py     — builders de AIRequest para chat, planner, after_tools
provider_call_runner.py   — ProviderCallRunner: run_chat, run_planner, run_after_tools
tool_loop_runner.py       — run_tool_loop → ToolLoopRunOutcome
tool_loop_step.py         — run_tool_loop_step → ToolLoopStepOutcome
final_response_builder.py — AIUsage + ResponseGuard + save + budget snapshot + respuesta
response_factory.py       — constructores de ChatMessageResponse (local_tool_response, etc.)
budget_snapshot.py        — BudgetSnapshot (daily_used, daily_ratio, warnings)
response_guard.py         — ResponseGuard.validate_final_text() + has_narrated_search()
artifacts.py              — helper ChatArtifact desde ruta de archivo
routing_decision.py       — ProviderMode, build_chat_routing_decision()
chat_persistence.py       — DEFAULT_CHAT_SESSION_ID, save_chat_message, get_recent_db_messages,
                            get_today_token_usage, get_or_create_default_chat_session
turn_persistence.py       — ChatTurnPersistence: encapsula save_chat_message con metadatos de
                            capture por turno (reemplaza closure _save_with_capture)
turn_context.py           — TurnContext dataclass + build_turn_context() (setup state por turno)
pre_ai_flow.py            — ChatPreAIFlow: tres early returns pre-AI (local_flow, pending_action,
                            budget_guard)
ai_turn_prep.py           — AITurnPrep dataclass + build_ai_turn_prep() (output_mode, historial,
                            toolset, routing, ProviderCallRunner, PersonaDecision)
ai_orchestrator.py        — ChatAIOrchestrator.run(): flujo AI completo (planner, tool loop,
                            early returns, after_tools, TTS)
```

## Arquitectura del flujo de chat

El flujo de un mensaje entrante pasa por cinco módulos en `backend/app/chat/`:

1. **`turn_context.py`** — `build_turn_context()`: agrupa el estado inicial
   del turno (trace_id, config, personalidad, presupuesto, persistence).

2. **`pre_ai_flow.py`** — `ChatPreAIFlow.try_handle()`: tres early returns
   antes de llamar al AI (local_flow, pending_action, budget_guard).

3. **`ai_turn_prep.py`** — `build_ai_turn_prep()`: prepara el contexto AI
   (output_mode, historial, toolset, routing decision, ProviderCallRunner).

4. **`ai_orchestrator.py`** — `ChatAIOrchestrator.run()`: ejecuta el flujo AI
   completo (planner, tool loop, early returns, after_tools, TTS).

5. **`routes_chat.py`** — entrypoint HTTP (164 líneas). Construye los cuatro
   objetos anteriores y los encadena. Maneja el model_upgrade_accepted rerun.

Reducción total: 862 → 164 líneas en `routes_chat.py` (−81%).

## Arquitectura objetivo ampliada

Nombres internos acordados:

```text
Senses
Core
Cortex
Memory
Output
Trace
Cleanup
Settings
```

### Senses

Entradas sensoriales:

- PC Vision;
- Camera;
- Microphone.

Reglas:

- activación explícita;
- timeout;
- indicadores visibles;
- no almacenamiento bruto por defecto;
- audit log.

### Output

Salidas:

- pantalla;
- altavoces;
- TTS;
- sonidos de estado;
- UI de confirmación.

Los altavoces no pertenecen a Senses.

### Core

Orquestación:

- Intent Router;
- Policy Engine;
- Session Manager;
- Context Builder;
- Persona Engine;
- Action Router.

El Core decide qué hacer con eventos, comandos y contexto.

### Cortex

Capa IA:

- OpenAI principal futuro para experiencia multimodal/cloud;
- Claude como fallback futuro;
- Ollama como local chat experimental;
- validadores;
- retry manager;
- adapters de contexto.

Regla: contexto canónico propio, no acoplar memoria al proveedor.

### Memory

Memoria local canónica.

Capas:

- ephemeral context;
- session memory (SQLite `chatmessage`, timeline único `"default"`);
- long-term local memory — FTS5 full-text search (`chatmessage_fts`) + MemoryRecallRunner;
- system/settings memory (`Setting` table — dataset capture, personalidad);
- audit/trace memory (`file_audit.jsonl`, backups, trace_id).

Los modelos reciben fragmentos seleccionados; no son fuente canónica.

Búsqueda de memoria implementada:

- `backend/app/memory/search.py` — `search_conversation_history`: FTS5 + LIKE fallback, filtrado operativo, prev/next context.
- `backend/app/memory/recall.py` — `MemoryRecallRunner`: búsqueda iterativa multi-query con evaluación de evidencia por novel token ratio. Siempre agota todas las variantes de query (sin parada temprana) y siempre expande ventanas alrededor de anclas con `message_id`.
- `backend/app/chat/prompt_context.py` — inyección de contexto estructural de memoria (total de mensajes, visibles, límite, disponibilidad de tool). Sin búsqueda proactiva: la búsqueda es solo on-demand vía tool.
- `backend/app/tools/handlers/memory_tools.py` — handler `search_conversation_history` disponible en `BASE_TOOLSET`.
- `backend/app/tools/handlers/trace_tools.py` — handler `read_own_trace`: lee `data/logs/app-YYYY-MM-DD.jsonl` (hoy + ayer como fallback), agrupa por `trace_id`, devuelve resumen estructurado por turno (tokens, tools, modo de salida, búsqueda de memoria, fragmentos TTS). Disponible solo cuando `dataset_source == "debug_test"` (inyectado en `routes_chat.py`; fuera de ese modo no aparece en el toolset).

La búsqueda de memoria es on-demand. El modelo llama a `search_conversation_history` cuando detecta que falta contexto. No hay inyección proactiva automática ni listas de triggers.

### Historial estructurado

El historial de conversación se envía al proveedor IA como mensajes estructurados (`prior_messages`), no como texto concatenado dentro del mensaje del usuario.

```text
messages = [
  {role: "user", content: "..."},   <- historial
  {role: "assistant", content: "..."},
  ...
  {role: "user", content: "<current_message>"},
]
```

El mensaje actual del usuario contiene solo el turno presente más contexto temporal y de memoria estructural. Los turnos anteriores van en `AIRequest.prior_messages` y el proveedor los recibe como mensajes separados en el array `messages`.

El número de turnos de historial visibles se controla con `tokens.max_recent_turns` en `config/default_config.yaml`. `history_limit_for_message()` en `toolset_selector.py` usa ese valor como base, con multiplicadores proporcionales para mensajes de contexto pesado.

### Trace

Observabilidad:

- logs JSONL;
- audit logs;
- métricas;
- trace_id/session_id/turn_id;
- debug panel.

Los logs no deben guardar contenido bruto sensible.

### Cleanup

Retención:

- borrar capturas temporales;
- borrar audio temporal;
- rotar logs;
- compactar sesiones;
- limpiar outputs temporales.

### Settings

Todo lo relevante debe ser configurable:

- personalidad;
- modos;
- spoilers;
- frecuencia de capturas;
- timeouts;
- voz;
- presupuesto;
- retención;
- memoria;
- proactividad;
- blacklist;
- providers.

Prioridad conceptual:

```text
session_override > user_setting > local_config > default_config
```

## Personalidad

Sity tiene personalidad parametrizable.

Parámetros relevantes:

- sarcasm_level;
- rudeness_level;
- warmth_level;
- honesty_level;
- initiative_level;
- dry_humor_level;
- frialdad_afectiva_level;
- contrarian_level;
- patience_level;
- refusal_chance;
- helpfulness_level;
- verbosity_level;
- melancholy_level;
- skepticism_level.

Reglas no negociables:

- Sity habla de sí misma en femenino.
- Seguridad y privacidad tienen prioridad sobre teatro/persona.
- Puede protestar, pero no bloquear comandos críticos.
- No puede negarse a apagar sensores, activar modo privado o borrar memoria si la política lo permite.

## Dataset y pipeline de entrenamiento

Sity usa un único timeline de conversación (`DEFAULT_CHAT_SESSION_ID = "default"`). No hay sesiones separadas para dataset. La separación semántica se hace mediante metadata por mensaje en `ChatMessage`.

### Metadata por mensaje

Campos de proveniencia:

- `tone_meta`: snapshot del vector de personalidad en cada respuesta de Sity. Base para calcular el bucket de entrenamiento.
- `dataset_source`: origen del par (`normal_use`, `synthetic_claude_user`, `human_guest`, `debug_test`).
- `dataset_eligible`: si el par es candidato a entrenamiento.
- `dataset_tags_json`: tags multi-label (`sarcasm_high`, `brief`, `multi_persona`, etc.).
- `speaker_label`, `speaker_source`, `speaker_confidence`: identificación del hablante (para reconocimiento futuro).

Campos de canal y modo de salida:

- `input_mode: "text" | "voice"` — canal de entrada del turno.
- `output_mode: "text" | "voice"` — modo de salida del turno. `"voice"` si se sintetizó TTS.
- `tts_fragments: Optional[int]` — número de fragmentos de audio sintetizados. `None` si no hubo TTS (texto puro, `text_only` con respuesta larga, o error de síntesis).
- `source_channel: "web"` — canal de origen del mensaje. Se propaga desde `ChatMessageRequest.source_channel` (default `"web"`). La respuesta de Sity hereda el mismo valor del turno.

Esta metadata **no se inyecta en el prompt de Sity**. Es invisible para el modelo en tiempo de inferencia.

### Dataset Capture

`backend/app/training/dataset_capture.py` — `DatasetCaptureService` gestiona el contexto de captura activo, persistido en la tabla `Setting` (key `dataset_capture`). Cuando está activo, cada mensaje guardado recibe los campos de metadata configurados. No cambia prompt ni comportamiento conversacional.

### DatasetStats

`backend/app/training/dataset_stats.py` — módulo puro sin efectos secundarios. Recibe el timeline completo y devuelve estadísticas de cobertura por bucket, tag y source. La unidad básica es un par consecutivo user→Sity con `tone_meta` presente y `dataset_eligible = true`.

Ver: `docs/operations/dataset-capture.md`.

## Local AI y LoRA

LoRA se usa para reforzar conducta base, no para reemplazar al backend.

Conductas objetivo:

- identidad de Sity;
- femenino gramatical;
- no inventar tools;
- no simular acciones;
- respeto al backend;
- tono propio.

No usar LoRA para meter secretos, estado runtime o conocimiento que deba venir de memoria/contexto.

## Seguridad

Principios:

- sin shell libre por defecto;
- sin sudo general;
- lectura/escritura solo en zonas permitidas;
- confirmaciones críticas;
- cámara y micro bajo petición explícita;
- no exponer backend/frontend a internet;
- backend valida siempre.

## Testing

Testing debe cubrir:

- unit tests;
- integración mock;
- contratos entre módulos;
- ResponseGuard;
- DB aislada;
- provider fallback;
- settings;
- memoria;
- seguridad;
- limpieza de temporales;
- LoRA scripts como smoke/manual, no CI obligatorio.

## Infraestructura de red

### Acceso y HTTPS

La PWA es accesible desde cualquier red sin VPN mediante `https://sity.aletm.com`.

**Cloudflare Tunnel** (`cloudflared`) crea una conexión saliente desde la Pi
hacia los servidores de Cloudflare — sin abrir puertos en el router ni necesitar
IP fija. El tráfico fluye: usuario → Cloudflare → túnel → Pi.

**Caddy** actúa como reverse proxy local recibiendo el tráfico del túnel:
- Puerto 443: HTTPS con certificado Let's Encrypt (para acceso local directo)
- Puerto 80: HTTP (para tráfico del túnel de Cloudflare)
- Renovación automática del certificado via Porkbun DNS challenge

Archivos de configuración:
- `/etc/caddy/Caddyfile` — configuración de Caddy
- `/etc/caddy/caddy.env` — API keys de Porkbun (chmod 600)
- `/etc/cloudflared/config.yml` — configuración del túnel
- `/etc/cloudflared/*.json` — credenciales del túnel

### Servicios systemd activos

| Servicio       | Puerto  | Descripción                         |
|----------------|---------|-------------------------------------|
| sity-backend   | 8000    | FastAPI + uvicorn                   |
| caddy          | 443/80  | Reverse proxy + TLS                 |
| cloudflared    | —       | Túnel Cloudflare (acceso sin VPN)   |

`sity-mobile` (Vite dev server) desactivado en producción.
La PWA se sirve como build estático desde `mobile/dist/`.

### Actualizar la PWA tras cambios

```bash
cd ~/projects/sity/mobile && npm run build
sudo systemctl reload caddy
```

---

## Búsqueda web

Tool `web_search` en `backend/app/tools/handlers/web_search_tools.py`.

Implementación: POST a `https://html.duckduckgo.com/html/` con la query.
Extrae snippets orgánicos filtrando anuncios (URLs con `y.js`). Devuelve
hasta 5 resultados con título, snippet y URL.

Sin clave de API, sin publicidad, sin dependencias externas más allá de
`httpx` (ya en requirements).

Límite de iteraciones: `ai.max_tool_loop_iterations: 3` en config — evita
bucles infinitos de búsquedas encadenadas.

Cuándo la usa Sity: información que cambia frecuentemente (precios, fechas,
puntuaciones, noticias, tiempo), cuando no tiene información suficiente sobre
algo específico, o cuando el usuario lo pide explícitamente.

---

## PWA móvil

Ubicación: `mobile/` — proyecto independiente, no comparte build con `frontend/`.

Stack: React 18 + TypeScript + Vite 5 + Framer Motion + CSS custom (sin Tailwind).
Build de producción en `mobile/dist/`, servido por Caddy.

Dominio: `sity.aletm.com`. Accesible desde cualquier red via Cloudflare Tunnel.

Sistema de temas:
- Variables CSS en theme.css (colores neón, glow, superficies).
- Fuente activa controlada por data-font en <html>, persistida en localStorage.
- Tres fuentes: Orbitron (defecto), Share Tech Mono, Rajdhani + Noto Sans JP
  para texto japonés/katakana.
- Fondo de pantalla: URL en localStorage (base64 para galería,
  ruta relativa para predefinidos).

Comunicación con backend: mismos endpoints que el frontend web.
Campo adicional source_channel: 'mobile' en POST /chat/message.

### Renderizado de markdown

Las burbujas de chat usan `react-markdown` + `remark-gfm` para renderizar:
- **Negrita** y *cursiva*
- Listas ordenadas y no ordenadas
- Bloques de código con fuente monoespaciada
- Enlaces clicables `[texto](url)` — abren Chrome directamente

## Model Router

Cuando `ai.claude.model_router_enabled: true`, Haiku tiene disponible la tool
`propose_model_upgrade` en su toolset. Si considera que la tarea supera su
capacidad, la llama con una razón y el sistema guarda un `ModelUpgradeProposal`
en memoria (singleton, expira en 5 minutos).

En el siguiente turno, si el usuario responde afirmativamente ("sí", "vale",
"ok", "adelante"), `local_flow` detecta la propuesta activa y devuelve un
`LocalFlowSignal(kind="model_upgrade_accepted")`. `routes_chat` relanza
`_chat_message_inner` con:
- `message = original_message` (el mensaje original, no el "sí")
- `_strong_model = claude-sonnet-4-6`
- `_skip_history_turns = 2` (omite el intercambio "sí"/propuesta del historial)
- Contexto de upgrade inyectado en el persona_prompt para que Sonnet ejecute
  directamente sin volver a proponer

Si el usuario responde negativamente ("no", "usa haiku"), la propuesta se descarta
y el mensaje original se ejecuta con Haiku.

Etiquetado de dataset: cuando el modelo usado es Sonnet, `turn_persistence`
añade `sonnet_response` a `dataset_tags_json` del mensaje de Sity
automáticamente. Permite filtrar por modelo al exportar el dataset de fine-tuning.

Módulos relevantes:
- `backend/app/chat/model_router.py` — singleton `ModelUpgradeProposal`
- `backend/app/cortex/tool_schemas.py` — `PROPOSE_MODEL_UPGRADE_TOOL`
- `backend/app/chat/local_flow.py` — detección de propuesta activa
- `backend/app/chat/turn_persistence.py` — etiquetado `sonnet_response`

---

## Prompt Caching

Implementado en `backend/app/cortex/claude_provider.py`. Tres capas de caché
en cada llamada a la API de Anthropic:

1. **System prompt** — `_system_with_cache()`: el prompt de sistema completo
   se marca con `cache_control: {type: ephemeral}`. ~5885 tokens cacheados.
2. **Tools** — `_tools_with_cache()`: `cache_control` en el último tool de la
   lista. Cachea todo el toolset en cada llamada.
3. **Historial** — `_messages_with_history_cache()`: `cache_control` en el
   último bloque del último `prior_message`. El historial se cachea
   incrementalmente turno a turno.

Métricas expuestas en `AIUsageData`: `cache_creation_tokens` y
`cache_read_tokens`. Aparecen en el evento `ai_call_completed` de cada turno.

Ahorro verificado en producción:
- Primer turno: `cache_creation: 5885, cache_read: 0`
- Turnos siguientes: `cache_creation: 0, cache_read: 5885`

Los tokens cacheados cuestan 10% del precio de input normal. En conversaciones
largas el ahorro es significativo — en una sesión de 20 turnos, ~112.000 tokens
de input se procesan a coste reducido.

Mínimo de tokens para cachear en Haiku 4.5: 4096. El system prompt + tools de
Sity supera ese mínimo, así que el caché siempre se activa.

---

## Panel de control (Sity Monitor)

App de escritorio Electron en `panel/` que monitoriza la Pi en tiempo real.
Independiente del backend: arranca aunque sity-backend esté caído.

Flujo de datos:
```text
systeminformation (Node) → ipcMain.handle → ipcRenderer.invoke → DOM
```

Polling:
- Métricas del sistema: cada 3s
- Estado de servicios: cada 8s

Alertas implementadas:
- sity-backend caído → pop-up crítico con log + botón restart

Alertas pendientes (roadmap):
- caddy caído (grave)
- cloudflared caído (medio — Sity sigue accesible en red local)
- CPU >85% sostenida (leve)
- Temperatura >75°C (grave)
- Disco >90% uso (medio)


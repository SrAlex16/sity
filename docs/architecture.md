# Arquitectura de Sity

Última actualización: 2026-06-15 (TTS Piper, Telegram bot, source_channel, output_mode/tts_fragments).

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

### Audio STT

Transcripción de voz a texto vía `faster-whisper` (local, CPU, modelo `base`, español).

- `POST /audio/transcribe` — recibe `multipart/form-data` con un archivo de audio, devuelve `{ transcript, duration_ms }`. No llama a servicios externos.
- El modelo se carga de forma perezosa en el primer uso (`WhisperModel` dentro de `get_model()`). Singleton con lock por hilo.
- `compute_type="int8"` para eficiencia en Raspberry Pi.
- La ruta es origin-agnostic: la llaman frontend web, Telegram bot, o cualquier cliente futuro.

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
- Errores de síntesis se loguean como WARN sin romper la respuesta.

**Voice settings** (persistidas en tabla `Setting`):
- `voice_response_mode: "always" | "never" | "symmetric"` (default `symmetric`)
- `voice_include_text: bool` (default `true`) — si es `false`, la respuesta se entrega solo como audio, sin texto visible.
- `voice_long_response_action: "split" | "text_only"` (default `text_only`)

Expuestas en `GET/PUT /settings/voice`. Configurables desde el tab "Voice" del frontend.

**`_attach_tts_artifacts`** devuelve `Optional[int]`: el número de fragmentos sintetizados, o `None` si se omitió TTS (texto largo con `text_only` o error de síntesis). Este valor se persiste en `ChatMessage.tts_fragments` tras la respuesta.

**Frontend:** reproductor `<audio controls>` en mensajes de Sity con artifacts de audio. Cuando `voice_include_text == false` y el mensaje tiene artifacts de audio, el texto de la burbuja se oculta (`hideText` en `ChatTab.tsx`) y solo se muestra el reproductor.

**Telegram:** si la respuesta contiene artifacts de audio, el bot los descarga (`gateway.get_tts_artifact`) y los envía como audio vía `reply_audio`. Cuando `voice_include_text == false`, el texto no se envía (`reply(text)` se omite). El `SityGateway` incluye siempre `"source_channel": "telegram"` en el body del POST.

**Limitación conocida:** los artifacts de audio son efímeros. Los archivos `.wav` se generan en `_TTS_TMP_DIR` y no se reconstruyen al recargar la sesión. Las URLs tipo `/audio/tts/{filename}` incluidas en `ChatMessageResponse.artifacts` son válidas solo mientras el proceso está en ejecución. Al recargar la historia vía `GET /chat/current`, los mensajes de voz no recuperan sus artifacts.

Archivos:
```text
backend/app/audio/synthesizer.py       — TtsConfig, synthesize_text() via subprocess piper
backend/app/audio/tts_splitter.py      — split_by_sentences()
backend/app/api/routes_audio.py        — POST /audio/synthesize, GET /audio/tts/{filename}, synthesize_to_tmp()
backend/app/settings/schemas.py        — VoiceSettings
backend/app/settings/settings_service.py — get/set_voice_settings()
backend/app/api/routes_settings.py     — GET/PUT /settings/voice
frontend/src/api/voiceApi.ts           — getVoiceSettings(), updateVoiceSettings()
frontend/src/components/VoiceSettingsTab.tsx — UI de configuración de voz
```

Tests: `tests/test_tts.py` — 36 tests, sin llamadas reales a piper ni a Telegram. `tests/test_chat_message_metadata.py` — 30 tests cubriendo output_mode, tts_fragments y source_channel.

### Telegram Bot

Proceso independiente para acceso remoto desde fuera de la red local.

- Long polling, sin webhooks.
- Corre como servicio systemd (`sity-telegram.service`) con dependencia en `sity-backend.service`.
- Llama al backend en `localhost:8000` vía HTTP.
- Lista de `allowed_chat_ids` en `config/telegram.yaml` — mensajes de otros chat_ids se ignoran silenciosamente.
- Rate limit por chat_id (ventana de 60 segundos).

Comandos: `/start`, `/help`, `/preset <modo>`, `/defaults`, `/status`.

Archivos:

```text
backend/app/messaging/models.py        — TelegramConfig + is_rate_limited()
backend/app/messaging/gateway.py       — SityGateway (httpx async)
backend/app/messaging/telegram_adapter.py — bot, handlers, _build_app(), main()
config/telegram.yaml                   — config (token en .env)
deploy/systemd/sity-telegram.service   — unidad systemd
```

No expone el backend a internet. El token se lee de `TELEGRAM_BOT_TOKEN` en `.env`.

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
- melancholy_level.

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
- `source_channel: "web" | "telegram"` — canal de origen del mensaje. Se propaga desde `ChatMessageRequest.source_channel` (default `"web"`). El bot de Telegram envía siempre `"telegram"`. La respuesta de Sity hereda el mismo valor del turno.

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


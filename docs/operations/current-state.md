# Estado actual del proyecto Sity

Última actualización: 2026-06-27.

Este documento resume el estado operativo actual del proyecto y las decisiones que condicionan los siguientes pasos. No sustituye al `README.md`; sirve como foto rápida para retomar trabajo sin depender de conversaciones antiguas.

## Estado funcional

Sity es una asistente local doméstica con backend FastAPI, frontend web, memoria local con búsqueda full-text, personalidad parametrizable, herramientas controladas y soporte experimental para proveedores locales.

Principios activos:

- Sity interpreta; el backend valida; el backend ejecuta.
- El modelo puede proponer acciones, pero no puede saltarse políticas del backend.
- Las herramientas solo existen si pasan por el flujo real del backend.
- El acceso a cámara, micrófono y PC vision debe ser explícito, trazable y cancelable.
- No se debe exponer backend/frontend directamente a internet.

Infraestructura activa:

- PWA móvil en mobile/ con diseño cyberpunk, acceso via Tailscale.
- Tailscale instalado en Pi (IP: 100.73.248.0) para acceso remoto.
- Servicio systemd `sity-mobile.service` para la PWA (Vite dev + `--host`).

## Backend y frontend

El backend principal está en `backend/` y el frontend en `frontend/`.

Estado actual:

- `ToolExecutor` migrado a registry.
- `ToolsetSelector` estructural: evitar routing/intención con listas duras de lenguaje natural.
- `BASE_TOOLSET` incluye file tools, `no_action_required` y `search_conversation_history`.
- `cancel_pending_action` expuesto solo por señal estructural (`act_xxxxxxxx`).
- `routes_chat.py` refactorizado en módulos de `backend/app/chat/` (868 → 730 líneas, 801 tests). Últimos extraídos (2026-06-17): `has_narrated_search` → `response_guard.py`, `chat_persistence.py`, `turn_persistence.py`, esquemas de petición/respuesta → `schemas.py`.
- Frontend modularizado: shell `App.tsx`, hook `useChat`, tabs y APIs separadas.
- AbortController añadido en frontend.
- TimeContext añadido para que Sity pueda reaccionar al paso del tiempo por turno.
- Provider abstraction activa mediante `AITextProvider`.
- `OllamaProvider` implementado como chat-only, sin tools.
- `local_provider_config.py`: `SITY_OLLAMA_MODEL` requerido explícitamente; misconfiguration loggeada, error controlado.
- `redact_tool_call_input`: inputs de tool calls redactados en logs.
- Generador sintético `scripts/generate_sity_v1_with_claude_cache.py` con prompt caching explícito.
- Metadata por mensaje en `ChatMessage`: proveniencia de hablante y contexto de captura de dataset.
- Dataset Capture Mode: etiquetado de mensajes nuevos para dataset. Persistido en `Setting` table.
- DatasetStats: módulo puro `backend/app/training/dataset_stats.py`. Endpoint `GET /debug/dataset-stats`.
- Pestaña Dataset en el frontend: Dataset Capture + DatasetStats.
- Audio STT: `faster-whisper` local, modelo `small` (mejorado desde `base`), `POST /audio/transcribe`, metadata `input_mode`/`voice_transcript_original`/`edit_distance_pct` en `ChatMessage`. Botón de micrófono en ChatTab y soporte de mensajes de voz en Telegram.
- Audio TTS: Piper TTS con binario en el venv (`Path(sys.executable).parent / "piper"`). `POST /audio/synthesize`, `GET /audio/tts/{filename}`. Speaker femenino vía `_SPEAKER_NAME_MAP` y flag `--speaker`. `voice_response_mode`, `voice_include_text`, `voice_long_response_action`, `audio_cleanup_days` persistidas en `Setting`.
- Audio TTS persistido: con `persist_tts: true` en config, los archivos `.wav` se guardan en `data/audio/` con nombre estable. `ChatMessage.audio_filename` guarda el nombre del primer fragmento. `GET /audio/stored/{filename}` los sirve. `POST /audio/cleanup` borra archivos más viejos que `cleanup_days` días (se ejecuta al arrancar). `GET /chat/current` devuelve `audio_filename` en cada `ChatMessageItem`; la PWA reconstruye burbujas de audio históricas sin recargar desde URLs efímeras.
- `voice_include_text` respetado en Telegram (texto omitido si false) y en frontend/PWA (burbuja sin texto si hay audio artifacts y `voice_include_text == false`).
- `output_mode` y `tts_fragments` en `ChatMessage`: persisten el modo de salida y el número de fragmentos TTS sintetizados por turno.
- Fragmentos TTS vacíos omitidos antes de sintetizar (guard contra WAV de 0 segundos cuando una frase queda vacía tras split).
- `source_channel` en `ChatMessage`: `"web"` por defecto; `"telegram"` cuando el origen es el bot. Propagado desde `ChatMessageRequest` y heredado por la respuesta de Sity.
- Telegram bot: proceso independiente con long polling, `sity-telegram.service`, allowlist por `chat_id`, rate limit, comandos `/preset` `/defaults` `/status`. Logs con `trace_id` para todas las fases de artifact (download, send). `SityGateway` incluye `"source_channel": "telegram"` en cada POST.
- Campo de texto del chat: `<textarea>` con auto-resize hasta 8 líneas (`maxHeight: 12rem`), Shift+Enter inserta salto de línea, Enter envía, scrollbar nativa oculta (Firefox y Chrome).
- Timestamps en mensajes: cada burbuja muestra `created_at` como HH:MM (hoy), "Ayer HH:MM" (ayer) o "D mes HH:MM" (días anteriores).
- Presupuesto diario de tokens: configurable en `config/default_config.yaml` sección `usage.daily_token_budget`. Override por env `SITY_DAILY_TOKEN_HARD_CAP`. Reset a medianoche hora local del servidor (no UTC). Fallback: 1 000 000 tokens/día.

## Sistema de memoria (2026-06-04)

### FTS5 full-text search

`backend/app/memory/search.py` — `search_conversation_history(query, limit)`:

- Tabla virtual `chatmessage_fts` como content table FTS5 de `chatmessage`.
- 3 triggers SQLite (AFTER INSERT/DELETE/UPDATE) para sincronía automática.
- Rebuild idempotente al arrancar (necesario: COUNT en content table lee la fuente, no el índice).
- Fallback a `_search_like_tokens` si FTS5 no disponible: búsqueda por token, no por OR literal.
- OR queries no se envuelven en comillas en FTS5 (evita convertirlas en phrase search).
- Mensajes operativos filtrados del match y del prev/next context.
- `limit` clamped a `[1, 10]`. Texto truncado a 1000 chars. `message_id` expuesto en `SearchResult`.

### MemoryRecallRunner

`backend/app/memory/recall.py` — `MemoryRecallRunner`:

- Genera hasta 4 variantes de query algorítmicamente (todo OR, longest-3 OR, primera mitad, longest-1).
- Sin domain-specific hardcodes, sin listas de triggers.
- Deduplica fragmentos entre intentos por prefijo de texto.
- Evalúa evidencia por **novel token ratio**: fracción de tokens del fragmento no presentes en la query.
  - `_NOVEL_THRESHOLD_SUFFICIENT = 0.60` → `max_novel ≥ 0.60` → status "sufficient" → "found"
  - `_NOVEL_THRESHOLD_PARTIAL = 0.20` → `avg_novel ≥ 0.20` → "partial"
  - Por debajo → "noise" o "not_found"
- Para cuando `ev_status == "sufficient"` o se agotan `_MAX_ATTEMPTS = 4` intentos.
- Evita falsos positivos por fragmentos que solo repiten la pregunta del usuario.

### Tool handler

`backend/app/tools/handlers/memory_tools.py` — handler `search_conversation_history`:

- Llama a `MemoryRecallRunner().recall(query, trace_id)`.
- Formatea `MemoryRecallResult` como texto legible con fragmentos, timestamps, prev/next, confidence.
- Expuesto en `BASE_TOOLSET`: el planner decide cuándo usarlo.

### Planner memory context

`PromptContextBuilder` inyecta en `planner_user_message` cada turno:

```text
Contexto estructural de memoria:
- total_messages: N
- visible_history_count: M
- history_limit: K
- long_memory_tool_available: true
```

Y cuando `n_total > history_limit`, ejecuta búsqueda proactiva sobre el mensaje e inyecta bloque `[MEMORIA RELEVANTE]...[FIN MEMORIA]` antes del planner.

### Tests de memoria

- 24 unit tests en `tests/test_memory_recall.py` (mock de search, sin DB).
- 13 integration tests en `scripts/test_memory_search_local.py` (DB temporal, sin Claude).
- 801 tests totales en pytest (incluye test_tts.py ×36, test_chat_message_metadata.py ×30, test_response_guard.py ×14, test_turn_persistence.py ×5).

## Tests

La fuente principal de verdad es `pytest`.

```bash
SITY_PROJECT_ROOT=$(pwd) backend/.venv/bin/python -m pytest -q tests/
```

Los wrappers `scripts/test_*_local.py` delegan a pytest y se conservan para compatibilidad/manual.

Integración mock:

```bash
./scripts/test_chat_mock_integration.sh
```

Reglas de DB:

- `data/app.db` no debe tocarse en tests.
- Los tests usan `SITY_DB_URL` y, cuando aplica, `SITY_TEST_DB_PATH`.
- La integración mock usa `tests/.mock_integration.db`.

## Bugs conocidos y limitaciones activas

### Audio STT / TTS

- **Transcripción STT**: el modelo `small` mejora la precisión pero sigue cometiendo errores con acentos andaluces fuertes, elisiones y encadenamiento de palabras. Limitación del modelo, no del código.
- **Pronunciación de palabras en inglés en TTS**: Piper pronuncia palabras en inglés con acento inglés. Pendiente añadir instrucción en `persona_system.md` para que Sity transcriba fonéticamente las palabras en inglés.
- **Acotaciones con asteriscos (`**texto**`)**: Piper lee los asteriscos literalmente en modo voz. Pendiente decidir si eliminar en post-procesado o instruir a Sity para evitarlos cuando `voice_response_mode != nunca`.

### Sistema de memoria

- **Contaminación de contexto por términos inferidos**: `MemoryRecallRunner` puede buscar usando términos que Sity misma generó en turnos anteriores. Si esos términos se usaron como query interna, el resultado puede parecer relevante pero no serlo. Las reglas añadidas en `persona_system.md` (2026-06-17) reducen la frecuencia — contrastar con historial visible, cautela extra con términos no dichos por el usuario —, pero no eliminan el problema. Limitación activa.
- **Búsqueda proactiva no se activa en conversaciones cortas**: solo cuando `n_total > history_limit`. Antes de ese umbral, no se inyecta contexto de memoria aunque el tema sea relevante.
- **`_LIMIT_MAX = 10` limita resultados**: para temas con muchas ocurrencias en el historial, puede perderse contexto relevante más antiguo.
- **Novel token ratio con textos cortos**: fragmentos con muy pocos tokens pueden producir clasificaciones erróneas si el vocabulario coincide completamente con la query por azar.
- **FTS5 rebuild al arrancar**: idempotente y rápido ahora (~ms/1k mensajes), pero podría ralentizar el arranque con historiales muy grandes (>100k mensajes).
- **`is_operational_guard_message` es text-match simple**: si cambian los patrones de mensajes operativos, hay que actualizar la función manualmente.

### Flujo local

- **Respuesta local ante "sí"/"ok" sin pending actions**: `local_flow.py` responde localmente que no hay nada que confirmar cuando el usuario dice "sí", "ok", "vale" y no hay acciones pendientes. Puede sentirse raro en conversación casual.
- **Confirmación exacta obligatoria**: una confirmación casi correcta (`confirmo ejecutar act_12345678\`` con backtick al final) se bloquea localmente y no llega a Claude. Es el comportamiento correcto pero puede confundir al usuario.

### Arquitectura

- **`routes_chat.py` aún contiene el tool loop**: no se ha extraído porque requiere diseño previo y tests de integración. Ver `backend/app/chat/README.md`.
- **Sin `ChatOrchestrator`**: el endpoint `/chat/message` sigue siendo relativamente largo.
- **No hay perfiles `home-safe` o `system-careful`**: acceso de archivos es solo `repo-only`.
- **Multiarchivo no es transaccional**: si una ruta de un plan multiarchivo falla, las demás pueden haber aplicado.

### Local AI

- **`SITY_LOCAL_AI_ENABLED` permanece `false` en producción**: no hay aún un adapter LoRA de calidad suficiente para uso diario.
- **Ollama en Raspberry es solo para emergencias**: la Pi no tiene potencia para servir LLMs útiles en tiempo real.

### Incidencias resueltas

- **Contador de tokens diario devolvía 0 (commits `0677f0a` + `c126fec`)**: El commit `0677f0a` corrigió la lectura de `daily_token_budget` (sección `usage` en lugar de `tokens`), pero introdujo un bug en `get_today_token_usage`: cambió `datetime.now(timezone.utc)` por `datetime.now()` (hora local sin timezone), rompiendo la comparación contra `AIUsage.created_at`, que se almacena en UTC. La función devolvía 0 siempre, lo que desactivaba efectivamente el hard cap aunque `SITY_DAILY_TOKEN_HARD_CAP=true` estuviera configurado. Fix aplicado en `chat_persistence.py` (commit `c126fec`): `datetime.now().astimezone()` obtiene hora local con timezone implícita del sistema, se calcula medianoche local, se convierte a UTC naive y se compara correctamente contra la BD. El endpoint `/debug/budget` ahora delega a `get_today_token_usage` en lugar de mantener su propia query, garantizando que ambos valores sean siempre consistentes. Efecto colateral descubierto: el límite de 50 000 tokens que mostraba `/debug/budget` no era el valor del config sino el fallback hardcodeado — el config siempre tuvo `daily_token_budget: 1 000 000` en la sección `usage`, pero el código lo buscaba en `tokens` y nunca lo encontraba.

## Ollama y modelos locales

Ollama queda como motor experimental/local.

Conclusiones actuales:

- Raspberry Pi no sirve como motor LLM principal.
- El PC debe actuar como Local AI Worker en LAN.
- Raspberry se mantiene como orquestador/backend/tools/pantalla.

Reglas importantes:

- No activar routing híbrido sin medir modelos.
- No usar `SITY_AI_PROVIDER=ollama` para flujo con tools/planner.
- Para local chat, usar `SITY_LOCAL_AI_ENABLED=true` + `SITY_LOCAL_AI_PROVIDER=ollama`.
- Tools y acciones siguen pasando por provider cloud/flujo seguro.

## Modelo de datos: timeline única

Sity usa un único timeline continuo (`DEFAULT_CHAT_SESSION_ID = "default"`). La separación semántica para dataset se hace mediante **metadata por mensaje** en `ChatMessage`:

- `tone_meta`: snapshot de personalidad en cada respuesta de Sity.
- `dataset_source`, `dataset_eligible`, `dataset_tags_json`: proveniencia y elegibilidad para training.
- `speaker_label`, `speaker_source`, `speaker_confidence`: identificación del hablante (para futuro reconocimiento).

Esta metadata no se inyecta en el prompt de Sity. Es invisible para el modelo en tiempo de inferencia.

## Dataset v1 — en captura activa

Las conversaciones para dataset v1 se capturan desde **2026-05-31T20:09:13+02:00**. Los bugs de voseo y continuidad conversacional estaban corregidos antes de esa marca.

Para exportar candidatos del timeline real:

```sql
SELECT * FROM chatmessage
WHERE created_at >= '2026-05-31 18:09:13'
  AND dataset_eligible = 1
  AND tone_meta IS NOT NULL;
```

Ver flujo completo: `docs/operations/dataset-capture.md`.

## Fine-tuning / LoRA

Pipeline LoRA validado en WSL con `google/gemma-3-4b-it`, Unsloth, RTX 3060 Ti 8 GB.

Resultado:

- Carga en 4-bit OK, LoRA entrena en RTX 3060 Ti 8 GB.
- Overfit logró identidad Sity, femenino gramatical y rechazo a tools inventadas.
- No significa que exista aún un modelo Sity de calidad para uso diario.

## Qué no hacer todavía

- No activar `SITY_LOCAL_AI_ENABLED=true` en producción sin adapter validado.
- No tocar runtime backend para usar LoRA.
- No subir `training/output/` a git.
- No subir modelos descargados de Hugging Face.
- No tocar Dataset tab / LoRA / embeddings / frontend salvo que sea imprescindible.

## Próximos pasos recomendados

1. **Completar dataset v1**: captura de conversaciones reales + generación sintética para buckets con poca cobertura.
2. **Fine-tune LoRA v1**: cuando dataset v1 tenga ≥ 80 ejemplos de calidad.
3. **Validar modelo fine-tuned**: medir con `scripts/diag_ollama_models.py`, comparar con gemma3:4b-it-qat base.
4. **Activar hybrid local**: solo cuando el modelo fine-tuned pase validación de calidad Sity.
5. **ChatOrchestrator**: extraer orquestación de `routes_chat.py` cuando haya tests de integración suficientes.

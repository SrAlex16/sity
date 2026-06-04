# Estado actual del proyecto Sity

Última actualización: 2026-06-04.

Este documento resume el estado operativo actual del proyecto y las decisiones que condicionan los siguientes pasos. No sustituye al `README.md`; sirve como foto rápida para retomar trabajo sin depender de conversaciones antiguas.

## Estado funcional

Sity es una asistente local doméstica con backend FastAPI, frontend web, memoria local con búsqueda full-text, personalidad parametrizable, herramientas controladas y soporte experimental para proveedores locales.

Principios activos:

- Sity interpreta; el backend valida; el backend ejecuta.
- El modelo puede proponer acciones, pero no puede saltarse políticas del backend.
- Las herramientas solo existen si pasan por el flujo real del backend.
- El acceso a cámara, micrófono y PC vision debe ser explícito, trazable y cancelable.
- No se debe exponer backend/frontend directamente a internet.

## Backend y frontend

El backend principal está en `backend/` y el frontend en `frontend/`.

Estado actual:

- `ToolExecutor` migrado a registry.
- `ToolsetSelector` estructural: evitar routing/intención con listas duras de lenguaje natural.
- `BASE_TOOLSET` incluye file tools, `no_action_required` y `search_conversation_history`.
- `cancel_pending_action` expuesto solo por señal estructural (`act_xxxxxxxx`).
- `routes_chat.py` refactorizado en módulos de `backend/app/chat/`.
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
- 630 tests totales en pytest.

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

### Sistema de memoria

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

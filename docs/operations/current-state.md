# Estado actual del proyecto Sity

Última actualización: 2026-06-03.

Este documento resume el estado operativo actual del proyecto y las decisiones que condicionan los siguientes pasos. No sustituye al `README.md`; sirve como foto rápida para retomar trabajo sin depender de conversaciones antiguas.

## Estado funcional

Sity es una asistente local doméstica con backend FastAPI, frontend web, memoria local, personalidad parametrizable, herramientas controladas y soporte experimental para proveedores locales.

Principios activos:

- Sity interpreta; el backend valida; el backend ejecuta.
- El modelo puede proponer acciones, pero no puede saltarse políticas del backend.
- Las herramientas solo existen si pasan por el flujo real del backend.
- El acceso a cámara, micrófono y PC vision debe ser explícito, trazable y cancelable.
- No se debe exponer backend/frontend directamente a internet.

## Backend y frontend

El backend principal está en `backend/` y el frontend en `frontend/`.

Estado reciente:

- `ToolExecutor` migrado a registry.
- `ToolsetSelector` estructural: evitar routing/intención con listas duras de lenguaje natural.
- `BASE_TOOLSET` minimizado.
- `cancel_pending_action` separado por señal estructural.
- `routes_chat.py` refactorizado en módulos de `backend/app/chat/`.
- Frontend modularizado: shell `App.tsx`, hook `useChat`, tabs y APIs separadas.
- AbortController añadido en frontend.
- TimeContext añadido para que Sity pueda reaccionar al paso del tiempo por turno.
- Provider abstraction activa mediante `AITextProvider`.
- `OllamaProvider` implementado como chat-only, sin tools.
- `local_provider_config.py`: `SITY_OLLAMA_MODEL` requerido explícitamente cuando `SITY_LOCAL_AI_ENABLED=true`; misconfiguration loggeada, error controlado.
- `redact_tool_call_input`: inputs de tool calls redactados en logs (always-redact para write_file/apply_*).
- Generador sintético `scripts/generate_sity_v1_with_claude_cache.py` con prompt caching explícito.
- Metadata por mensaje en `ChatMessage`: proveniencia de hablante y contexto de captura de dataset. No se inyecta en el prompt.
- Dataset Capture Mode: etiquetado de mensajes nuevos para dataset sin cambiar comportamiento conversacional. Persistido en `Setting` table. Endpoints `GET/PUT /debug/dataset-capture`, `POST /debug/dataset-capture/disable`.
- DatasetStats: módulo puro de cómputo `backend/app/training/dataset_stats.py`. Endpoint `GET /debug/dataset-stats`. Buckets, tags y progreso hacia targets LoRA v1.
- Pestaña Dataset en el frontend: Dataset Capture (formulario con presets) + DatasetStats (cobertura, desglose, últimos pares). Pestaña Debug separada: solo trazas y eventos recientes.

## Tests

La fuente principal de verdad es `pytest`.

Usar:

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

## Ollama y modelos locales

Ollama queda como motor experimental/local.

Conclusiones actuales:

- Raspberry Pi no sirve como motor LLM principal.
- Ollama en Raspberry queda para emergencia o experimentos.
- El PC debe actuar como Local AI Worker en LAN.
- Raspberry se mantiene como orquestador/backend/tools/pantalla.

Reglas importantes:

- No activar routing híbrido sin medir modelos.
- No usar `SITY_AI_PROVIDER=ollama` para flujo con tools/planner.
- Para local chat, usar `SITY_LOCAL_AI_ENABLED=true` + `SITY_LOCAL_AI_PROVIDER=ollama`, cuando toque.
- Tools y acciones siguen pasando por provider cloud/flujo seguro.

El diagnóstico manual de modelos vive en:

```text
scripts/diag_ollama_models.py
```

Resultados locales en:

```text
reports/ollama/
```

`reports/` está ignorado por git.

## Modelo de datos: timeline única

Sity usa un único timeline continuo (`DEFAULT_CHAT_SESSION_ID = "default"`). No hay sesiones separadas por modo, usuario o captura. La separación semántica para dataset se hace mediante **metadata por mensaje** en `ChatMessage`:

- `tone_meta`: snapshot de personalidad en cada respuesta de Sity.
- `dataset_source`, `dataset_eligible`, `dataset_tags_json`: proveniencia y elegibilidad para training.
- `speaker_label`, `speaker_source`, `speaker_confidence`: identificación del hablante (para futuro reconocimiento).

Esta metadata no se inyecta en el prompt de Sity. Es invisible para el modelo en tiempo de inferencia.

## Dataset v1 — en captura activa

Las conversaciones para dataset v1 se capturan desde **2026-05-31T20:09:13+02:00**. Los bugs de voseo y continuidad conversacional estaban corregidos antes de esa marca.

La pestaña Dataset del frontend muestra en tiempo real el progreso de captura hacia los targets LoRA v1.

Para sesiones con Claude-extension (`multi_persona`): activar preset `synthetic_claude_user` en Dataset Capture antes de iniciar, desactivar al terminar.

Para exportar candidatos del timeline real:

```sql
SELECT * FROM chatmessage
WHERE created_at >= '2026-05-31 18:09:13'
  AND dataset_eligible = 1
  AND tone_meta IS NOT NULL;
```

Ver flujo completo: `docs/operations/dataset-capture.md`.

## Fine-tuning / LoRA

Se validó pipeline LoRA en WSL con:

- WSL + Python venv `~/venv`.
- Hugging Face login correcto.
- Modelo gated de Google aceptado y accesible.
- `google/gemma-3-4b-it` descargado en `~/models/hf/google-gemma-3-4b-it`.
- RTX 3060 Ti visible desde WSL.
- PyTorch CUDA OK.
- Unsloth OK.
- Entrenamiento LoRA smoke OK.
- Entrenamiento LoRA overfit OK.
- Inferencia con adapter OK.

Resultado validado:

- Gemma 3 4B IT carga en 4-bit.
- LoRA entrena en RTX 3060 Ti 8 GB.
- El adapter puede modificar conducta.
- El overfit logró identidad `Sity`, femenino gramatical y rechazo a tools inventadas.

Esto no significa que exista aún un modelo Sity de calidad. Solo significa que el pipeline técnico es viable.

## Qué no hacer todavía

- No activar ChatRoutingDecision nuevo para local AI sin medir modelos.
- No tocar runtime backend para usar LoRA.
- No subir `training/output/` a git.
- No subir modelos descargados de Hugging Face.
- No subir `unsloth_compiled_cache/`.
- No convertir todavía el adapter a formato de serving hasta definir dataset v0.1.

## Próximo paso recomendado

### Dataset v1 — en captura

El generador sintético (`scripts/generate_sity_v1_with_claude_cache.py`) está disponible para completar buckets con poca cobertura real. Revisión manual obligatoria antes de incorporar al training set.

### Cuándo activar hybrid local

No activar `SITY_LOCAL_AI_ENABLED=true` en producción hasta que:
- Exista un adapter LoRA validado con calidad Sity real (no solo overfit).
- Se haya medido el modelo fine-tuned con `scripts/diag_ollama_models.py`.
- `SITY_OLLAMA_MODEL` esté configurado explícitamente en el entorno.

El provider cloud (Anthropic) sigue siendo el provider estable para tools y acciones.


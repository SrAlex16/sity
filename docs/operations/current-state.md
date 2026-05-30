# Estado actual del proyecto Sity

Última actualización: 2026-05-30.

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

Construir `training/data/sity_persona_v0.jsonl` con 100-200 muestras centradas en comportamiento, no conocimiento.

Áreas del dataset v0.1:

1. Identidad de Sity.
2. Femenino gramatical.
3. Español de España.
4. Tono seco/sarcástico controlado.
5. No inventar tools.
6. No simular acciones.
7. Backend como autoridad.
8. Seguridad y privacidad siempre obedecidas.
9. Corrección del usuario.
10. Contexto temporal.
11. Límites de local AI.
12. Respuestas breves de conversación normal.


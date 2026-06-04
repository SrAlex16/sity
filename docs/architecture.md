# Arquitectura de Sity

Última actualización: 2026-06-04.

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
- `backend/app/memory/recall.py` — `MemoryRecallRunner`: búsqueda iterativa multi-query con evaluación de evidencia por novel token ratio.
- `backend/app/chat/prompt_context.py` — inyección de contexto estructural de memoria y búsqueda proactiva.
- `backend/app/tools/handlers/memory_tools.py` — handler `search_conversation_history` disponible en `BASE_TOOLSET`.

El planner decide cuándo usar la tool. No hay listas de triggers ni detección de intención por frases.

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
- tsundere_level;
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


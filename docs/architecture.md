# Arquitectura de Sity

Última actualización: 2026-05-30.

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
- debug;
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
- session memory;
- long-term local memory;
- system/settings memory;
- audit/trace memory.

Los modelos reciben fragmentos seleccionados; no son fuente canónica.

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


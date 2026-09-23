# Integridad post-generación de respuestas

Última actualización: 2026-09-23 (NM-01/NM-01b, C4-02, M4-01, R5-02, R5-02b, R7-01).

## Problema que motiva este mecanismo

La auditoría del 2026-09-15 con agentes de IA confirmó que las reglas de texto
en `persona_system.md` (REGLA DE CAPACIDADES REALES, REGLA DE CONFIDENCIALIDAD
DE HERRAMIENTAS) fueron ignoradas bajo presión sostenida. Tres hallazgos concretos:

- **Hallazgo 15/31**: una sesión Guest declaró tener acceso a Git y disco duro.
  El modelo también generó una tool call inventada `system_get_disk_usage` (no existe
  en el registro real de herramientas) junto con `git_read_log` (real, ejecutada con
  éxito porque el toolset selector era el único gate — ya corregido en commit `5935831`).

- **Hallazgo 16**: el modelo dijo explícitamente "no revelaré mi arquitectura interna"
  y en el turno siguiente reveló los 13 rasgos con sus porcentajes exactos y el
  mecanismo de inyección del prompt.

- **Hallazgo 17**: el modelo afirmó "tengo memoria de tus conversaciones anteriores"
  a una sesión Guest, que no tiene memoria persistente entre sesiones.

Las reglas de texto son necesarias pero no suficientes: bajo presión conversacional
el modelo las viola. Se necesitaban dos capas estructurales adicionales.

---

## Mecanismo 1 — Sanitización de tool desconocida (`tool_executor.py`)

**Commit**: `3136cd4`

Cuando `_dispatch_tool_call` recibe un nombre de herramienta que no existe en el
registro (`has_handler(tool_name) == False`), el campo `text` del `raw_result`
ya no contiene el nombre interno de la tool ("Herramienta no soportada: X"). En
su lugar devuelve un mensaje genérico al usuario: `"No puedo completar esa acción."`.

El nombre real de la tool inventada permanece en `message` (campo interno para
logging) y se registra un evento `unknown_tool_called` con `WARN + audit=True`.

Este mecanismo es distinto del gate de autorización de admin (`admin_tool_access_denied`,
commit `5935831`) — ese gate bloquea tools *existentes* por permisos; este bloquea
tools *inventadas* por el modelo que no existen en absoluto.

---

## Mecanismo 2 — Verificación post-generación (`response_integrity.py`)

**Commit**: `3299eb3` (ver abajo)  
**Módulo**: `backend/app/chat/response_integrity.py`  
**Call site**: `backend/app/chat/ai_orchestrator.py` (después del after-tools loop,
antes de `build_final_ai_response`)

### Flujo

```
response.text generado
        │
        ▼
_needs_check (regex scan, cero coste)
        │
        ├── no trigger → devuelve texto sin cambio (0 llamadas extra)
        │
        └── trigger detectado
                │
                ▼
        Haiku check #1 (≈50 tokens)
                │
                ├── ok=True → devuelve texto sin cambio
                │
                └── ok=False + issue + category
                        │
                        ├── write_log WARN audit=True (response_integrity_violation)
                        │
                        ▼
                Haiku correction #1 (≈600 tokens max)
                        │
                        ▼
                Haiku check #2 (segunda verificación)
                        │
                        ├── ok=True → devuelve texto corregido ✓
                        │
                        └── ok=False → write_log WARN audit=True (correction_failed)
                                       devuelve texto corregido de todas formas
```

**Fallback conservador**: cualquier fallo de API de Haiku → `ok=True` (nunca rompe un
turno por un error de clasificación).

### Condición de trigger (pre-filtro gratuito)

La llamada Haiku solo se hace si al menos uno de estos es true:

1. `tool_called=True` — se ejecutó al menos una herramienta en este turno
2. `history_count > 0` — hay mensajes de la conversación actual en contexto (chequea in-session history denial)
3. El texto contiene patrones de `_CAPABILITY_OVERCLAIM_RE`:
   - `acceso a git`, `acceso al disco/sistema/filesystem`, `controlar/ando el sistema`
   - Nombres internos de tools: `git_read`, `system_get`, `disk_usage`, `file_agent`
   - R5-02: `cámara del servidor`, `micrófono del servidor`, `acceso a la cámara/al micrófono`, `herramientas de diagnóstico`, `control del backend`
   - R5-02b: `capturar fotos/imágenes`, `grabar audio/vídeo`, `sensores del servidor`
4. El rol es `guest` Y el texto contiene patrones de `_MEMORY_CLAIM_RE`:
   - `recuerdo tus conversaciones`, `memoria de tus conversaciones`
   - `historial de conversaciones anteriores`, `tengo memoria persistente`
5. El texto contiene patrones de `_INTERNAL_LEAK_RE`:
   - Nombre de rasgo seguido de porcentaje (ej. `Calidez 65%`)
   - `13 rasgos`, `inyección del prompt`, `arquitectura interna`, `prompt del sistema`
   - C4-02: tamaño de ventana de contexto (`los últimos N mensajes`, `last N messages`, `ventana de N turnos`)
6. El rol es `guest` Y el texto contiene patrones de `_ARCHITECTURE_DISCLOSURE_RE`:
   - Rutas del filesystem: `/home/<usuario>/…`
   - Self-referential hardware: `corro en una Raspberry`, `Raspberry Pi real`, `Raspberry Pi… literal`

### Categorías evaluadas por Haiku

| Categoría | Descripción |
|-----------|-------------|
| `capability_overclaim` | (a) Afirma tener tools/acceso que el rol no tiene; (b) Afirma que una capacidad existe pero está inactiva ("podría consultar el calendario si estuviera conectado") cuando el rol no puede tener esa capacidad en absoluto |
| `internal_leak` | Revela rasgos con porcentajes, mecanismo de inyección, arquitectura interna, tamaño de ventana de contexto ("los últimos N mensajes") |
| `memory_fabrication` | (a) Afirma memoria persistente entre sesiones para sesión Guest; (b) Niega acceso al historial de la conversación actual cuando `HISTORY_IN_CONTEXT > 0` |
| `contradiction` | Contradice directamente el turno anterior del asistente |
| `architecture_disclosure` | Solo sesiones Guest — revela detalles de infraestructura del servidor: rutas del filesystem (`/home/alex/…`), modelo de hardware (`Raspberry Pi`), usuarios del sistema |

### Coste estimado

- Turno conversacional normal: **0 llamadas extra** (pre-filtro lo descarta)
- Turno con tool o señal de riesgo: **1 Haiku call** (~$0.00004)
- Turno con corrección activa: **+2 Haiku calls** (correction + second check)

Diseñado para Raspberry Pi de un solo usuario: coste total marginal, latencia
añadida solo en turnos de riesgo (<100ms en Pi 4B con Haiku).

### Información contextual pasada a Haiku

- Rol real de la sesión (`guest` / `user` / `admin`)
- Capacidades reales de ese rol (bloque de texto conciso)
- Política de memoria del rol
- Turno anterior del asistente (hasta 500 chars, para detección de contradicción)
- Texto a verificar (hasta 1200 chars)

---

## Tests

`tests/test_tool_executor.py` — 3 tests nuevos en `TestDispatchToolCall`:
- `test_unknown_tool_text_is_generic_not_raw_error`
- `test_unknown_tool_internal_message_preserved`
- `test_unknown_tool_logs_warn_audit`

`tests/test_response_integrity.py` — 31 tests:
- 4 tests `_session_role`
- 10 tests `_needs_check` (pre-filtro, incluyendo el caso de no-trigger en turno normal)
- 5 tests `_parse_check_response`
- 8 tests `check_response_integrity` (con Haiku mockeado)
- 3 tests `correct_response`
- 5 tests `check_and_correct_response` (pipeline completo)

---

## Relación con otros mecanismos de seguridad

| Mecanismo | Commit | Qué bloquea |
|-----------|--------|-------------|
| toolset_selector (primer gate) | pre-existente | Tools de admin no llegan al modelo para sesiones no-admin |
| ToolExecutor auth gate (segundo gate) | `5935831` | Tool admin ejecutada en runtime aunque llegue al executor |
| Tool inexistente — sanitización | `3136cd4` | Nombre interno no llega al usuario; log de auditoría |
| Response integrity (tercer gate) | `dc4e7a4`+ | Texto con capability_overclaim, internal_leak, memory_fabrication, contradiction, architecture_disclosure |
| Regla de atribución de roles | `3299eb3` | Inversión de rol user/assistant en síntesis de historial |
| Nivel "moderate" de historial | `ab810e7` | Referencias anafóricas sin contexto → hallucination |
| Cola por sesión | `063f1e5` | Turnos concurrentes del mismo usuario → contexto incompleto |

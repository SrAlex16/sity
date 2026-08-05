# Sistema de temporizadores y alarmas

Última actualización: 2026-08-05.

## Propósito

Permite a Sity programar mensajes que se entregan automáticamente en el futuro:
- **Temporizador** (`set_timer`) — duración relativa: "ponme un temporizador de 10 minutos"
- **Alarma** (`set_alarm`) — hora absoluta: "avísame a las 15:00"

## Arquitectura

### Modelo de datos — `ScheduledTask`

Tabla SQLite persistente en `data/app.db`. Sobrevive a reinicios del backend.

```
id            TEXT  PK  — "tmr_<hex8>"
session_id    TEXT      — sesión propietaria del timer
fires_at      DATETIME  — hora UTC de disparo
message       TEXT      — texto que Sity entrega al dispararse
created_at    DATETIME  — cuándo se creó
fired_at      DATETIME  — cuándo se disparó (NULL = pendiente)
cancelled_at  DATETIME  — cuándo se canceló (NULL = no cancelado)
```

Un timer pendiente tiene `fired_at IS NULL AND cancelled_at IS NULL`.

### Runner — `app/timers/runner.py`

`ScheduledTaskRunner` es una corrutina asyncio iniciada en `main.py` `on_startup`.
Se despierta cada `timers.poll_interval_seconds` (por defecto 5 s) y llama a
`fire_pending_once(db_session)` vía `run_in_executor` (no bloquea el event loop).

`fire_pending_once(db_session)`:
1. Selecciona todos los `ScheduledTask` sin `fired_at` ni `cancelled_at`.
2. Filtra en Python los que tienen `fires_at <= now()`.
3. Para cada uno: marca `fired_at = now()`, persiste un `ChatMessage` con el mensaje,
   hace `db_session.commit()`.
4. Publica un evento SSE `proactive_message` (tipo `"timer_fired"`) en la sesión
   propietaria via `publish_session_event_sync`.

La función está expuesta para tests sin necesidad de asyncio.

### Service — `app/timers/service.py`

Funciones CRUD con validación:

- `create_scheduled_task(db, session_id, fires_at, message)` — valida límites, crea el task.
- `list_pending(db, session_id)` — timers pendientes de la sesión.
- `cancel_task(db, session_id, timer_id)` — solo cancela timers propios de la sesión.
- `count_pending(db, session_id)` — conteo para verificar el límite máximo.

### Tools

Añadidas al `BASE_TOOLSET` (disponibles en todas las conversaciones):

| Tool | Parámetros | Descripción |
|------|------------|-------------|
| `set_timer` | `duration_seconds`, `message?` | Timer relativo en segundos |
| `set_alarm` | `fires_at` (ISO 8601), `message?` | Alarma a hora absoluta |
| `list_timers` | — | Lista los timers pendientes de la sesión |
| `cancel_timer` | `timer_id` | Cancela un timer propio pendiente |

## Aislamiento por sesión

Cada `ScheduledTask` lleva `session_id`. El runner solo notifica a la sesión
propietaria via `publish_session_event_sync(task.session_id, ...)`.
`cancel_timer` filtra por `session_id` — un usuario no puede cancelar timers
de otra sesión.

**Guests:** no tienen lógica especial. Si un Guest cierra la pestaña, la
`_SessionQueue` de SSE queda idle y se evicta tras 1 hora (TTL existente).
El timer puede seguir existiendo en DB pero la notificación se pierde en la
cola idle. Comportamiento aceptable: misma garantía que los background jobs.

## Configuración (`config/default_config.yaml`)

```yaml
timers:
  poll_interval_seconds: 5      # cadencia del runner (granularidad mínima de disparo)
  max_duration_hours: 24        # duración máxima de un timer/alarma
  max_active_per_session: 5     # límite de timers pendientes simultáneos por sesión
```

## Persistencia tras reinicio

La tabla `ScheduledTask` es SQLite persistente. Al arrancar de nuevo, el runner
encuentra todos los timers pendientes y los dispara en el próximo ciclo si
`fires_at <= now()`. No hay pérdida de timers por reinicios del backend.

## Flujo de disparo (secuencia)

```
Runner wakes up every 5s
  └─ fire_pending_once(db)
       ├─ SELECT pending timers WHERE fired_at IS NULL AND cancelled_at IS NULL
       ├─ Filter: fires_at <= now()
       ├─ For each due timer:
       │    ├─ task.fired_at = now()
       │    └─ ChatMessage(session_id, role="sity", text=message, trace_id="tmr_<id>")
       ├─ db.commit()
       └─ For each fired: publish_session_event_sync(session_id, {
              type: "proactive_message",
              subtype: "timer_fired",
              text: message,
              timer_id: id
          })
```

## Tests — `tests/test_timers.py`

28 tests:
- `TestFirePendingOnce` — lógica central del runner (dispara, no dispara futuro/cancelado/ya-disparado, persiste ChatMessage, aislamiento por sesión)
- `TestTimerPersistence` — timer sobrevive reinicio simulado
- `TestTimerService` — validaciones (pasado rechazado, max duración, max activos, count, cancel, list)
- `TestTimerHandlerRegistration` — 4 tools registradas
- `TestTimerHandlers` — happy paths + errores vía dispatch_tool directo

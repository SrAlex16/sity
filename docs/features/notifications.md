# Notifications & Background Tasks / Notificaciones y Tareas en Background

[English](#english) · [Español](#español)

---

## English

### Notification architecture

Four layers:

```
Detection
  ├── Timers/alarms (set_timer, set_alarm tools)
  ├── Background tasks (web_search completions)
  ├── Recurring tasks (ScheduledTask — step 6, pending)
  └── Initiative (proactive messages)
        ↓
Decision (dispatcher.py)
  ├── Deduplication
  ├── Frequency limits
  └── Routing by urgency + visibility
        ↓
Delivery
  ├── SSE (Server-Sent Events, always)
  └── Web Push with VAPID (background only, best-effort)
        ↓
Persistence
  └── NotificationLog
```

### Routing by visibility

| App state | Delivery |
|---|---|
| Tab visible | SSE only |
| Tab in background | SSE + Web Push (best-effort) |
| No SSE subscriber | Web Push or state "pending" |

### Priority levels

| Type | Priority | Web Push wake |
|---|---|---|
| Timer fired | High | Yes |
| Task result, chat reply | Medium | Yes |
| Recurring, initiative | Low | No |

### Web Push

Web Push is independent of Google. Uses own VAPID keys. Each browser's push service handles delivery. No dependency on Google Cloud Messaging.

Guest sessions are excluded from Web Push (no persistent identity).

### SSE channel

A persistent per-session stream. Key properties:
- Queue survives client disconnects
- Holds up to 20 events
- Expires after 1 hour of inactivity
- Fan-out model: each subscriber gets its own copy (prevents zombie connections holding events)

### Timers and alarms

Two tools available in every conversation:
- `set_timer` — relative duration ("in 30 minutes")
- `set_alarm` — absolute time ("at 18:00")

Plus: `list_timers` and `cancel_timer`.

**Storage**: SQLite (`data/app.db`), survives backend restarts.

**Runner**: asyncio coroutine started at app startup. Polls every 5 seconds. When a task is due: marks fired → saves chat message → sends `timer_fired` SSE event to the owning session.

**Constraints**:
- Maximum duration: 24 hours
- Maximum pending per session: 5
- Session isolation: users can only cancel their own timers

28 tests in `tests/test_timers.py`.

### Background tasks (detachable tools)

Some tools are classified as `detachable` (currently: `web_search`). When invoked:

1. Claude replies immediately with a "working on it" message
2. `JobManager` runs the tool in a thread pool (2 workers)
3. On completion: generates natural-language summary → saves to DB → pushes `proactive_message` via SSE

**Frontend**: Persistent `EventSource` appends `proactive_message` events. On reconnect, reloads history from DB as fallback.

**Adding a detachable tool**: Just add its name to the blocking policy table in `tool_schemas.py`. No other changes needed.

### Known issues

- **Opera GX**: incompatible. Service Worker self-deregisters after registration. Not a Sity code bug.
- **Recurring tasks**: `ScheduledTask` recurrence extension is step 6 (not yet implemented).

---

## Español

### Arquitectura de notificaciones

Cuatro capas: Detección → Decisión (dispatcher.py, con deduplicación, límites de frecuencia y enrutamiento) → Entrega (SSE + Web Push) → Persistencia (NotificationLog).

### Enrutamiento por visibilidad

Ver tabla en la sección en inglés.

### Web Push

Web Push es independiente de Google. Usa claves VAPID propias. El push service de cada navegador hace la entrega. Sin dependencia de Google Cloud Messaging.

Las sesiones guest están excluidas (sin identidad persistente).

### Canal SSE

Stream persistente por sesión. Cola que sobrevive a desconexiones de cliente, hasta 20 eventos, expira tras 1h de inactividad. Modelo fan-out: cada suscriptor recibe su propia copia (evita conexiones zombie que retienen eventos).

### Timers y alarmas

Dos tools disponibles en toda conversación: `set_timer` (duración relativa) y `set_alarm` (hora absoluta). Más: `list_timers` y `cancel_timer`.

**Almacenamiento**: SQLite, sobrevive a reinicios del backend.

**Runner**: corrutina asyncio. Polling cada 5 segundos. Máximo 24h de duración, máximo 5 pendientes por sesión.

### Tareas en background (tools detachables)

La única tool actualmente detachable es `web_search`. Claude responde inmediatamente; el resultado se entrega después como nuevo mensaje por SSE.

Para añadir una tool detachable: solo agregar su nombre a la tabla de política de bloqueo en `tool_schemas.py`.

### Issues conocidos

- **Opera GX**: incompatible (el Service Worker se auto-desregistra). No es un bug del código de Sity.
- **Tareas recurrentes**: la extensión de recurrencia en `ScheduledTask` es el paso 6 (pendiente).

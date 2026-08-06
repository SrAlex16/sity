# Arquitectura del sistema de notificaciones

Última actualización: 2026-08-06.
Estado: **documento de diseño — cero código implementado**.

Este documento unifica tres ideas anotadas en `docs/state.md` que comparten
la misma infraestructura de entrega: Web Push API (prerequisito de alarmas
reales), Sistema de iniciativa propia de Sity, y Sistema de eventos/vigías
genéricos. Antes de escribir una línea, inventario de lo ya construido.

---

## Inventario del código real (verificado 2026-08-06)

### Cuatro emisores existentes — todos convergen en `realtime_events.py`

Todos publican con el mismo `publish_session_event_sync(session_id, event)`
del mismo módulo. El campo `type` distingue el contenido:

| Emisor | Módulo | Tipo de evento publicado |
|---|---|---|
| Tarea detachable (web_search, read_webpage) | `core/job_manager.py` | `"job_done"` / `"job_error"` + callback `_on_done` → `"proactive_message"` |
| Tarea en background (ai_orchestrator._on_done) | `chat/ai_orchestrator.py` | `"proactive_message"` con `subtype="background_result"` |
| Alarma/timer | `timers/runner.py` | `"proactive_message"` con `subtype="timer_fired"` |
| Infraestructura base | `core/realtime_events.py` | `_SessionQueue` (buffer de 20 eventos, TTL 1h, GC cada 10 min) |

**Invariante clave:** ningún emisor crea su propio canal. Todos llaman a
`publish_session_event_sync`. El nuevo sistema no rompe esta invariante.

### Service worker existente (`mobile/public/sw.js`)

Tiene cuatro listeners: `install`, `activate`, `message`, `fetch`. El
listener de `fetch` pasa SSE sin tocarlos (guard explícito para `/events/`).
**No tiene listener `push`.** Ese es exactamente el punto de extensión para
Web Push.

### Modelos de datos relevantes

- `ScheduledTask` — single-shot, `fires_at` datetime, `fired_at`/`cancelled_at`.
  No tiene campo de recurrencia. Para tareas recurrentes se necesita o bien
  extender este modelo o un modelo separado.
- `UserIntegration` — credenciales OAuth por usuario/proveedor. Es la fuente
  de verdad para saber si Gmail/Spotify está conectado para una sesión.
- `SocialProfile` — `opinion` (EMA en [-1,+1]), `trust` ([0,1]).
  Escritura solo por background job (`social/update.py`). La iniciativa
  propia puede leerlo pero nunca escribirlo.
- `DailyMessageUsage` — contador de mensajes por sesión con fecha. Patrón
  de rate limiting ya establecido.

### Gmail Watch API (investigado)

Gmail tiene una [Push Notifications API](https://developers.google.com/gmail/api/guides/push)
real: `users.watch` registra un endpoint de Pub/Sub de Google Cloud que
recibe webhooks cuando llega correo nuevo. **No requiere polling.** Sin
embargo, requiere configurar un topic de Google Cloud Pub/Sub — infraestructura
que no existe en el proyecto. La alternativa de polling con la API REST
(`users.messages.list` con `q=is:unread after:<timestamp>`) funciona sin
infraestructura nueva pero tiene coste de cuota. Ver § 2.3.

---

## 1. Arquitectura de capas

```
┌─────────────────────────────────────────────────────┐
│  CAPA DE DETECCIÓN   — «algo ha ocurrido»           │
│  Módulos: timers/runner.py (ya existe)              │
│           notifications/detectors/                  │
│             gmail_detector.py (nuevo)               │
│             recurrent_task_runner.py (nuevo)        │
│             initiative_runner.py (nuevo)            │
└───────────────────────────┬─────────────────────────┘
                            │ NotificationFact
                            ▼
┌─────────────────────────────────────────────────────┐
│  CAPA DE DECISIÓN    — «¿se notifica o se descarta?»│
│  Módulo: notifications/dispatcher.py (nuevo)        │
│  Responsabilidades:                                 │
│    - Rate limiting por sesión/tipo                  │
│    - Deduplicación (¿ya enviamos este hecho?)       │
│    - Enrutamiento: ¿SSE, Web Push, o ninguno?       │
└──────────┬────────────────────────────┬─────────────┘
           │ SSE                        │ Web Push
           ▼                            ▼
┌──────────────────────┐   ┌───────────────────────────┐
│  CAPA DE ENTREGA SSE │   │  CAPA DE ENTREGA WEB PUSH  │
│  (YA EXISTE)         │   │  notifications/push.py     │
│  publish_session_    │   │  (nuevo)                   │
│  event_sync()        │   │  pywebpush / VAPID         │
└──────────────────────┘   └───────────────────────────┘
           │                            │
           └────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────┐
│  CAPA DE PERSISTENCIA — historial + deduplicación   │
│  Modelo: NotificationLog (nuevo, tabla SQLite)      │
│  Módulo: notifications/log.py (nuevo)               │
└─────────────────────────────────────────────────────┘
```

### 1.1 Capa de Detección

**Qué hace:** produce un `NotificationFact` — una estructura Python que
describe qué ocurrió, para quién, y con qué urgencia. No sabe nada de
canales de entrega.

**Módulos:**

- `timers/runner.py` — **ya existe**. Detecta timers vencidos. Hoy llama
  directamente a `publish_session_event_sync`; en el nuevo diseño llamaría
  a `dispatcher.dispatch(fact)` en su lugar.
- `notifications/detectors/gmail_detector.py` — **nuevo**. Polling periódico
  (ver § 2.3) contra la Gmail API para usuarios con `UserIntegration` de Google
  activo. Produce hechos de tipo `"external_event"`.
- `notifications/detectors/recurrent_task_runner.py` — **nuevo**. Ejecuta
  tareas recurrentes (ver § 2.4). Produce hechos de tipo `"task_result"`.
- `notifications/detectors/initiative_runner.py` — **nuevo**. Evalúa si
  procede que Sity inicie conversación (ver § 2.5). Produce hechos de tipo
  `"proactive_initiative"`.

Todos estos runners son corrutinas asyncio iniciadas en `main.py on_startup`,
mismo patrón que `timers/runner.py` → `start_runner(loop)`.

### 1.2 Capa de Decisión

**Qué hace:** recibe un `NotificationFact`, decide si notificar (y cómo) o
descartar. Es el único módulo que conoce las reglas de negocio de cuándo
molestar al usuario.

**Módulo:** `notifications/dispatcher.py` — **nuevo**.

Responsabilidades concretas:
1. **Deduplicación**: consulta `NotificationLog` — si este hecho exacto
   (misma sesión, mismo tipo, mismo `fact_id`) ya fue entregado en las
   últimas N horas, descarta.
2. **Rate limiting**: comprueba cuántas notificaciones se han enviado a esta
   sesión en las últimas 24h. Si supera el límite configurable
   (`notifications.max_per_day_user` / `max_per_day_guest` en
   `default_config.yaml`), descarta o encola para el siguiente día.
3. **Enrutamiento por canal**: consulta si la sesión tiene un suscriptor SSE
   activo (`_session_queues[session_id].subscriber_count > 0`). Si sí → SSE.
   Si no → Web Push (si tiene `PushSubscription` registrada). Si ninguno →
   persiste en `NotificationLog` con `delivery_status="pending"` para
   entregarlo por SSE cuando el usuario abra la app.
4. **Escribe en `NotificationLog`** tras cada intento de entrega.

### 1.3 Capa de Entrega

**SSE (ya existe):**
`publish_session_event_sync(session_id, event)` — sin cambios. El dispatcher
la llama con el payload normalizado.

**Web Push (nuevo):**
`notifications/push.py`. Usa `pywebpush` (biblioteca Python estándar para
enviar Web Push con VAPID). Recibe la `PushSubscription` del usuario y el
payload, firma con clave VAPID, envía al endpoint del navegador.
Gestiona los errores de suscripción inválida (HTTP 410 Gone → marca la
`PushSubscription` como expirada en DB, no reintenta).

**Fallback:** si el usuario no tiene `PushSubscription` activa y no hay
suscriptor SSE, el evento queda en `NotificationLog` con
`delivery_status="pending"`. Cuando el usuario vuelve a abrir la app y
conecta SSE, el frontend pide al endpoint `GET /notifications/pending` y
los muestra. No se pierde la notificación.

### 1.4 Capa de Persistencia

**Modelo:** `NotificationLog` (nuevo, en `memory/models.py`).

```
id              INT  PK autoincrement
session_id      TEXT indexed
notification_type TEXT  — "timer_fired" | "background_result" | "external_event"
                          | "recurrent_task" | "proactive_initiative"
fact_id         TEXT  — hash del hecho (para deduplicación)
payload_json    TEXT  — contenido serializado (lo que se mostraría al usuario)
created_at      DATETIME
delivery_channel TEXT  — "sse" | "push" | "pending"
delivery_status TEXT  — "delivered" | "failed" | "pending"
delivered_at    DATETIME nullable
push_error      TEXT nullable  — razón del fallo si delivery_status="failed"
```

**Retención:** mismo sistema de limpieza que logs (TTL configurable, purgado
por el GC de `realtime_events._gc_loop` o un job propio).

---

## 2. Disparadores — cuándo se genera una notificación

### 2.1 Timer/alarma vence — **ya existe, solo falta el puente a Web Push**

`timers/runner.py:fire_pending_once()` ya produce el hecho. El único cambio
necesario: en lugar de llamar directamente a `publish_session_event_sync`,
pasa el hecho al `dispatcher` que decide SSE vs. Web Push.

**Impacto en código existente:** mínimo. Una línea de cambio en
`fire_pending_once`.

### 2.2 Tarea en background termina — **ya existe, mismo puente**

`job_manager.py` y `ai_orchestrator._on_done` ya publican `"proactive_message"`.
Mismo cambio: reemplazar la llamada directa a `publish_session_event_sync`
por `dispatcher.dispatch(fact)`. El dispatcher aplica el fallback a Web Push.

### 2.3 Evento externo detectado — **nuevo, con decisión de implementación**

**El caso de Gmail.** Gmail tiene Watch API (Pub/Sub de Google Cloud) que evita
polling, pero requiere configurar un topic de Cloud Pub/Sub — infraestructura
externa que el proyecto no tiene. **Decisión de diseño: usar polling REST
controlado** en primera versión, con posibilidad de migrar a webhooks si la
cuota de la API se vuelve un problema.

Diseño del detector de Gmail:
- `notifications/detectors/gmail_detector.py` se despierta cada N minutos
  (configurable, ej. 5 min por defecto).
- Para cada usuario con `UserIntegration(provider="google", is_active=True)`,
  llama a `users.messages.list` con `q=is:unread after:<last_check_timestamp>`.
- `last_check_timestamp` se persiste por usuario en una tabla nueva
  `WatcherState` o como campo en `UserIntegration`.
- Si hay mensajes nuevos que cumplen la condición que el usuario configuró
  (ej. "de: jefe@empresa.com"), produce un `NotificationFact` y lo pasa al
  dispatcher.

**Dónde vive la condición de filtro:** en un modelo nuevo `NotificationRule`
(ej. `session_id`, `detector_type="gmail"`, `filter_json='{"from": "..."}'`,
`is_active=True`). El usuario las crea mediante una tool o UI futura. Sin
reglas activas, el detector no produce hechos para esa sesión — no hay polling
innecesario.

**Cuota de Gmail API:** con polling de 5 min para N usuarios, el coste es
razonable (N × 288 llamadas/día). Añadir back-off exponencial si la API
devuelve 429.

### 2.4 Tarea periódica recurrente — **nuevo, extender ScheduledTask**

**Decisión de diseño: extender `ScheduledTask` en lugar de crear un modelo
nuevo**, añadiendo campos de recurrencia opcionales. Justificación: el
modelo base ya tiene todo lo necesario (session_id, message, fires_at,
fired_at); la recurrencia solo añade "cuándo volver a disparar". Crear un
modelo nuevo duplicaría el runner.

Campos nuevos en `ScheduledTask` (o alternativa: subclase / tabla separada
`RecurringTask` — ver trade-offs abajo):

```
recurrence_rule   TEXT nullable  — cron expression o "interval:3600"
next_fires_at     DATETIME nullable  — calculado tras cada disparo
max_occurrences   INT nullable   — None = indefinido
occurrence_count  INT default 0
```

**Trade-off de extender vs. tabla nueva:**

| Criterio | Extender ScheduledTask | Tabla RecurringTask separada |
|---|---|---|
| Complejidad de runner | Un solo runner maneja ambos | Dos runners, lógica separada |
| Migración | Añadir columnas nullable (no rompe nada) | Nueva tabla limpia |
| Claridad conceptual | Modelo más grande | Separación más clara |
| Recomendación | **Preferida** si las diferencias son solo de recurrencia | Si el ciclo de vida diverge mucho |

**Recomendación:** extender `ScheduledTask` con columnas nullable. El runner
existente ya ignora columnas que no conoce; solo hay que añadir la lógica de
"si `recurrence_rule` no es null, tras disparar calcular `next_fires_at` y
resetear `fired_at=None`".

### 2.5 Iniciativa propia de Sity — **nuevo, el más delicado**

**Comparativa de los dos sub-diseños propuestos:**

#### (a) Scheduler con periodicidad configurable

El `initiative_runner.py` se despierta según un intervalo configurable por
usuario (ej. "si no hemos hablado en 2 días, Sity puede iniciar conversación").
La "iniciativa" es un texto predefinido o semi-generado con una plantilla.

- **Coste de tokens:** mínimo (sin llamada al modelo).
- **Previsibilidad:** alta. El usuario sabe exactamente cuándo esperar mensajes.
- **Riesgo:** la iniciativa es mecánica y puede parecer spam si el contenido
  no aporta valor real.

#### (b) El modelo evalúa en background

Mismo patrón que el job de opinión/confianza (`social/update.py`): cada N
turnos (o cada N horas), un job en background llama al modelo con el contexto
reciente y el `SocialProfile` del usuario, y el modelo decide si "tiene algo
que aportar". Si la respuesta es no → descarta. Si es sí → produce un
`NotificationFact` con el texto generado.

- **Coste de tokens:** moderado (una llamada al modelo por usuario por ciclo).
  Con Haiku son ~$0.0001–0.001 por evaluación. Perfectamente asequible con
  pocos usuarios.
- **Previsibilidad:** baja para el usuario, pero la calidad del contenido es
  mayor — Sity solo escribe cuando genuinamente tiene algo que decir.
- **Riesgo:** si el prompt no está bien definido, el modelo puede decidir
  "siempre tengo algo que decir" y spamear. Mitigación: el rate limiter de
  la capa de Decisión es el freno de emergencia.

**Recomendación: (b) con frenos**. La iniciativa mecánica (a) no tiene valor
suficiente — si Sity escribe "¿Cómo estás?" cada dos días sin contexto, es
spam. Si escribe "Vi que hay tráfico en tu ruta habitual para mañana — ¿quieres
que revise alternativas?" basándose en contexto real, aporta valor. El coste
de tokens de (b) con Haiku es despreciable. Los frenos son:

1. Rate limiter del dispatcher: máximo 1 mensaje de iniciativa propia cada
   24h por defecto, configurable en `default_config.yaml`.
2. Cooldown de conversación: si el usuario habló con Sity en las últimas N
   horas, el runner de iniciativa no evalúa — no tiene sentido interrumpir
   una conversación activa.
3. `SocialProfile.trust` como umbral: si `trust < 0.3` (relación poco
   establecida), no iniciar — Sity solo inicia conversación con usuarios
   con quienes tiene cierta relación construida.
4. Guest: excluido completamente (ver § 4).

---

## 3. Taxonomía de tipos de notificación

Campo `notification_type` en `NotificationLog` y en el payload SSE/Push:

| Tipo | Subtipo | Urgencia | Descripción |
|---|---|---|---|
| `timer_fired` | — | Alta | Alarma/timer del usuario ha vencido |
| `background_result` | `web_search`, `read_webpage`, etc. | Media | Tarea detachable completada |
| `external_event` | `gmail_new_message`, `spotify_*` | Media-Alta | Vigía externo detectó condición |
| `recurrent_task` | — | Baja-Media | Tarea periódica recurrente completada |
| `proactive_initiative` | — | Baja | Sity inicia conversación por su cuenta |

**Comportamiento diferenciado por urgencia:**

- **Alta** (`timer_fired`): se envía Web Push inmediatamente si no hay
  suscriptor SSE activo. El payload incluye `vibrate: [200, 100, 200]` en
  la opción de la Notification Web API. No se aplica rate limiting entre
  notificaciones de tipo timer (el usuario las pidió explícitamente).
- **Media** (`background_result`, `external_event`): Web Push si no hay SSE.
  Sin vibración especial.
- **Baja** (`proactive_initiative`, `recurrent_task`): NO enviar Web Push
  si la app está cerrada — en cambio, marcar como `delivery_status="pending"`
  y entregar en el próximo SSE. La lógica es que Sity no debe despertar al
  usuario con mensajes no urgentes; si está disponible, lo recibe; si no,
  espera.

Esta distinción de urgencia evita el principal defecto de los sistemas de
notificaciones que tratan todo igual: el usuario silencia todo porque recibió
demasiadas notificaciones de baja urgencia.

---

## 4. Aislamiento por rol y sesión

### Guest

| Tipo de notificación | ¿Aplica a Guest? | Razón |
|---|---|---|
| `timer_fired` | **Sí, si la app está abierta** | El Guest puede poner timers; hoy ya funciona por SSE. Sin PushSubscription, no hay Web Push. |
| `background_result` | **Sí, si la app está abierta** | Mismo que hoy — el job existe mientras la sesión SSE esté activa. |
| `external_event` (Gmail, etc.) | **No** | Guest no tiene `UserIntegration` activa (OAuth requiere cuenta). |
| `recurrent_task` | **No** | Las tareas recurrentes requieren identidad persistente para tener sentido. |
| `proactive_initiative` | **No** | Sity no inicia conversación con usuarios anónimos sin relación establecida. Además, no hay `SocialProfile` para Guest. |
| Web Push (cualquier tipo) | **No** | Para registrar una `PushSubscription` hace falta una sesión persistente que sobreviva al cierre del navegador. La sesión de Guest no tiene esa garantía. |

**Verificación en código:** el dispatcher comprueba si `session_id.startswith("guest:")` antes de intentar cualquier entrega que requiera identidad persistente.

### Rate limiting de notificaciones

Siguiendo el patrón de `DailyMessageUsage` y `default_config.yaml`:

```yaml
notifications:
  max_proactive_per_day_user: 1          # "proactive_initiative" por sesión/día
  max_external_events_per_day_user: 20   # vigías externos
  recurrent_task_cooldown_minutes: 60    # mínimo entre dos del mismo tipo
  initiative_cooldown_hours: 24          # mínimo entre dos iniciativas propias
  initiative_min_trust: 0.30             # SocialProfile.trust mínimo para iniciar
  initiative_silence_hours: 4            # no iniciar si el usuario habló en este margen
```

El dispatcher consulta `NotificationLog` para verificar estos límites antes
de producir cada entrega.

---

## 5. Logging y trazabilidad

Siguiendo el patrón establecido en `app/trace/logger.py` (`write_log`):

### Capa de Detección

```python
write_log(level="INFO", module="notifications", event="fact_produced",
    payload={"session_id": ..., "type": ..., "fact_id": ..., "detector": ...})
```

### Capa de Decisión

```python
# Cuando se descarta por rate limiting
write_log(level="INFO", module="notifications", event="fact_discarded_rate_limit",
    payload={"session_id": ..., "type": ..., "reason": "max_per_day_exceeded"})

# Cuando se descarta por deduplicación
write_log(level="INFO", module="notifications", event="fact_discarded_duplicate",
    payload={"session_id": ..., "fact_id": ..., "original_delivered_at": ...})

# Cuando se decide el canal
write_log(level="INFO", module="notifications", event="routing_decision",
    payload={"session_id": ..., "type": ..., "channel": "sse"|"push"|"pending"})
```

### Capa de Entrega

```python
# SSE entregado
write_log(level="INFO", module="notifications", event="delivery_sse_ok",
    payload={"session_id": ..., "notification_id": ...})

# Web Push exitoso
write_log(level="INFO", module="notifications", event="delivery_push_ok",
    payload={"session_id": ..., "notification_id": ..., "endpoint_domain": ...})

# Web Push fallido
write_log(level="WARN", module="notifications", event="delivery_push_failed",
    payload={"session_id": ..., "notification_id": ..., "http_status": ...,
             "subscription_expired": True|False})

# PushSubscription inválida (410 Gone)
write_log(level="WARN", module="notifications", event="push_subscription_expired",
    payload={"session_id": ..., "endpoint_domain": ...})
```

### Runners de detección

```python
# Gmail detector
write_log(level="INFO", module="notifications", event="gmail_poll_done",
    payload={"session_id": ..., "new_messages": N, "elapsed_ms": ...})

# Initiative runner
write_log(level="INFO", module="notifications", event="initiative_evaluated",
    payload={"session_id": ..., "decision": "send"|"skip", "reason": ...})
```

---

## 6. Prerrequisitos técnicos de Web Push

### 6.1 Claves VAPID

VAPID (Voluntary Application Server Identification) son un par de claves
EC (curva P-256) que identifican al servidor ante los push services de los
navegadores (Google FCM, Mozilla autopush, Apple APNs en Safari).

**Dónde viven:** en variables de entorno del backend.
```
VAPID_PRIVATE_KEY=<base64url>
VAPID_PUBLIC_KEY=<base64url>
VAPID_CONTACT=mailto:alejandrotubio1004@gmail.com
```

Las claves se generan una vez con `pywebpush --generate-keys` y se añaden
a `.env`. La **clave pública** también se necesita en el frontend para llamar
a `PushManager.subscribe()`.

### 6.2 Tabla `PushSubscription`

Nueva tabla en `memory/models.py`:

```python
class PushSubscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    endpoint: str              # URL del push service del navegador
    p256dh: str                # clave pública DH del cliente (base64url)
    auth: str                  # secret de autenticación (base64url)
    user_agent: Optional[str] = Field(default=None)  # para debug
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True)  # False si 410 Gone
```

Un usuario puede tener múltiples suscripciones activas (móvil + escritorio).
Al entregar, se intenta en todas las activas de la sesión.

### 6.3 Endpoint de registro

```
POST /notifications/subscribe
```
Requiere autenticación (no Guest). Body: `{endpoint, keys: {p256dh, auth}}`.
Crea o actualiza la `PushSubscription` para esta sesión + dispositivo.
El `endpoint` identifica unívocamente el dispositivo en el push service.

```
DELETE /notifications/subscribe
```
Marca `is_active=False`. Llamado cuando el usuario desactiva notificaciones
o cierra sesión.

```
GET /notifications/pending
```
Devuelve `NotificationLog` con `delivery_status="pending"` para esta sesión.
El frontend los consume al conectar SSE y los marca como leídos.

```
GET /notifications/vapid-public-key
```
Público (no requiere auth). Devuelve la clave pública VAPID para que el
frontend pueda llamar a `PushManager.subscribe()`.

### 6.4 Cambios en el service worker (`mobile/public/sw.js`)

**Añadir listener `push`:**

```javascript
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  const title = data.title ?? 'Sity';
  const options = {
    body: data.body ?? '',
    icon: '/icons/sity_icon_192.png',
    badge: '/icons/sity_icon_192.png',
    data: { url: data.url ?? '/' },
    // vibrate solo en alta urgencia
    ...(data.urgent ? { vibrate: [200, 100, 200] } : {}),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url ?? '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const existing = list.find((c) => c.url.includes(targetUrl));
      if (existing) return existing.focus();
      return clients.openWindow(targetUrl);
    })
  );
});
```

**Deep-linking:** el campo `url` del payload usa `get_public_base_url()` del
backend (ej. `https://sity.aletm.com/`) — sin default divergente. Si en el
futuro hay rutas a mensajes específicos (ej. `/shared/{id}`), irían aquí.

**Registro de PushSubscription en el frontend:**
En `mobile/src/hooks/useAuth.ts` (o un nuevo `useNotifications.ts`), tras
login exitoso:

```javascript
const reg = await navigator.serviceWorker.ready;
const subscription = await reg.pushManager.subscribe({
  userVisibleOnly: true,
  applicationServerKey: vapidPublicKey, // obtenida de GET /notifications/vapid-public-key
});
await fetch('/notifications/subscribe', {
  method: 'POST',
  body: JSON.stringify(subscription.toJSON()),
  headers: { 'Content-Type': 'application/json' },
  credentials: 'include',
});
```

---

## 7. Casos de validación a cubrir en tests (sin implementar)

Estos casos demuestran que el diseño es correcto. No son implementación —
son la lista de contratos que los tests deberán verificar.

1. **Aislamiento entre usuarios**: una notificación producida para `session_id="user:1"` nunca llega a `session_id="user:2"` ni aparece en su `NotificationLog`.

2. **Guest sin iniciativa propia**: el `initiative_runner` no produce hechos para sesiones con `session_id.startswith("guest:")`.

3. **Guest sin Web Push**: `dispatcher.dispatch(fact)` para `session_id="guest:..."` nunca intenta enviar Web Push, incluso si existiera una `PushSubscription` (no debería existir, pero el código debe ser robusto).

4. **Rate limiting de iniciativa propia**: si se entregan 2 notificaciones `proactive_initiative` en las últimas 24h para `user:1`, la tercera es descartada con `event="fact_discarded_rate_limit"`.

5. **Fallback SSE → Push → pending**: con suscriptor SSE activo → SSE. Sin SSE + PushSubscription activa → Push. Sin SSE y sin Push → `delivery_status="pending"`.

6. **PushSubscription inválida (410 Gone)**: cuando el push service devuelve 410, la suscripción se marca `is_active=False` en DB, se registra `event="push_subscription_expired"`, y la entrega pasa a `delivery_status="pending"`. No se reintenta.

7. **Timer vencido con app cerrada**: un timer de `user:1` que vence mientras no hay suscriptor SSE activo se entrega via Web Push. El `NotificationLog` lo registra con `delivery_channel="push"`.

8. **Deduplicación de vigías**: si el detector de Gmail produce el mismo `fact_id` dos veces (ej. polling solapado), el dispatcher descarta el segundo.

9. **Trust mínimo para iniciativa**: `initiative_runner` no produce hechos para usuarios cuyo `SocialProfile.trust < notifications.initiative_min_trust`.

10. **Cooldown de conversación**: `initiative_runner` no produce hechos si el usuario habló con Sity en las últimas `notifications.initiative_silence_hours`.

---

## 8. Orden de implementación recomendado

Ordenado de menor a mayor complejidad y con cada paso autónomamente útil:

| Paso | Qué implementar | Valor inmediato |
|---|---|---|
| **1** | Claves VAPID + tabla `PushSubscription` + endpoint subscribe + listener `push` en SW | Infraestructura base de Web Push sin ningún disparador |
| **2** | Tabla `NotificationLog` + `notifications/dispatcher.py` (routing SSE/Push/pending) | Unifica todos los emisores existentes |
| **3** | Pilotar con timers: `timers/runner.py` llama a `dispatcher.dispatch` en lugar de `publish_session_event_sync` directamente | Timer/alarma funciona aunque la PWA esté cerrada — el caso de uso más pedido |
| **4** | Pilotar con background tasks: `job_manager.py` y `ai_orchestrator._on_done` pasan por dispatcher | Background tasks también funcionan con app cerrada |
| **5** | `notifications/detectors/gmail_detector.py` + modelo `NotificationRule` | Vigías de Gmail |
| **6** | Extender `ScheduledTask` con recurrencia + `recurrent_task_runner.py` | Tareas periódicas |
| **7** | `notifications/detectors/initiative_runner.py` | Iniciativa propia — el más delicado, último |

Los pasos 1–4 son la base que da valor real sin complejidad nueva. Los pasos
5–7 son los disparadores nuevos que dependen de esa base.

---

## Relación con las entradas de `docs/state.md`

| Entrada en state.md | Cubre este documento |
|---|---|
| Web Push API — prerrequisito para alarmas reales | §6 completo + §2.1 + paso 1 y 3 del orden |
| Sistema de iniciativa propia de Sity | §2.5 + §3 (tipo `proactive_initiative`) + §4 (aislamiento) |
| Sistema de eventos/vigías genéricos | §2.3 (`external_event`) + §2.4 (recurrentes) + modelo `NotificationRule` |

Las tres entradas se pueden cerrar cuando se implemente todo lo descrito aquí.

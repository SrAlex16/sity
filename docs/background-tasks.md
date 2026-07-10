# Tareas en segundo plano

Última actualización: 2026-07-10.

Cómo y por qué Sity ejecuta ciertas tools en background en vez de
bloquear la respuesta del turno de chat, y cómo el resultado llega
al frontend como un mensaje nuevo cuando termina.

## Motivación

Algunas tools (por ahora, `web_search`) pueden tardar varios segundos.
Bloquear el turno de chat entero hasta que terminen da una sensación
de app colgada. En su lugar, Sity responde de inmediato con un mensaje
tipo "estoy buscando..." y, cuando el resultado está listo, lo empuja
al chat como un mensaje nuevo del asistente — sin que el usuario tenga
que esperar ni volver a preguntar.

## Piezas del sistema

```
Usuario → POST /chat/message
             │
             ▼
     ChatAIOrchestrator (planner decide qué tool usar)
             │
             ▼
   get_blocking_policy(tool_name)
             │
    ┌────────┼─────────────┐
    ▼        ▼              ▼
immediate  blocking     detachable
(sin tool) (inline,     (JobManager,
            espera       responde ya)
            el turno)
                              │
                              ▼
                    JobManager.submit()
                    (ThreadPoolExecutor, 2 workers)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              job_start (SSE)      tool_fn() ejecuta
              inmediato            en background
                                        │
                                   job_done/error
                                        │
                                        ▼
                                    on_done callback
                              (_on_done en ai_orchestrator.py)
                                        │
                        ┌───────────────┼───────────────┐
                        ▼               ▼                ▼
                run_after_tools   persistir en DB   publish_session_event_sync
                (Claude convierte  (ChatMessage,     (proactive_message → SSE)
                 resultado crudo   para que el
                 en respuesta      próximo turno
                 natural)          tenga contexto)
                                                            │
                                                            ▼
                                              /events/session/{id} (SSE)
                                                            │
                                                            ▼
                                          Frontend: EventSource.onmessage
                                          → nuevo ChatMessage en el hilo
```

## 1. Clasificación de tools: blocking policy

`backend/app/cortex/tool_schemas.py` define `TOOL_BLOCKING_POLICIES`,
un diccionario estático `tool_name → policy`:

```python
TOOL_BLOCKING_POLICIES: dict[str, str] = {
    "no_action_required": "immediate",
    "cancel_pending_action": "immediate",
    "web_search": "detachable",
    # todo lo demás por defecto: "blocking"
}
```

Tres políticas posibles:

- **`immediate`** — no hay ejecución real de tool (el planner las usa
  para saltarse el bucle de tools directamente).
- **`blocking`** — comportamiento clásico: la tool se ejecuta inline
  y el turno de chat espera a que termine antes de responder. Es el
  default para cualquier tool no listada explícitamente.
- **`detachable`** — la tool puede desprenderse a background de
  inmediato. No hay watchdog ni timeout: si la tool está marcada como
  `detachable`, se manda a background **siempre**, desde el primer
  momento, no solo cuando tarda más de X segundos.

`get_blocking_policy(tool_name)` en `backend/app/chat/tool_loop_runner.py`
consulta esa tabla. El punto de decisión está en
`ChatAIOrchestrator` (`backend/app/chat/ai_orchestrator.py`), justo
después de que el planner devuelve la primera tool call:

```python
if get_blocking_policy(_first_tool.name) == "detachable":
    _loop = _detach_tool(...)
else:
    _loop = run_tool_loop(...)  # camino normal, bloqueante
```

Añadir una tool nueva al flujo de background es tan simple como
añadir su nombre a `TOOL_BLOCKING_POLICIES` con valor `"detachable"`.

## 2. JobManager — ejecución en background

`backend/app/core/job_manager.py`. Singleton (`get_job_manager()`)
respaldado por un `ThreadPoolExecutor` (2 workers por defecto,
configurable en `ai.background.max_workers`).

- `submit(tool_name, session_id, fn, on_done)` crea un `Job`, publica
  un evento `job_start` **síncronamente antes** de lanzar el thread
  (para que el indicador de "trabajando en ello" aparezca en el
  frontend antes que la respuesta inmediata del turno, no después),
  y encola `fn` en el executor.
- Cuando `fn()` termina, el job pasa a `status="done"` o `"error"`,
  se publica `job_done`/`job_error`, y por último se invoca
  `on_done(job)` dentro de un `finally` — si `on_done` lanza, el
  error se traga silenciosamente (no debe tumbar el thread del pool).
- `Job` es un dataclass simple: `job_id`, `tool_name`, `session_id`,
  `status`, `result_text`, `error`.
- `list_for_session()` / `active_count()` — usados por
  `GET /events/session/{id}/jobs` para que el frontend pueda consultar
  el estado activo bajo demanda, aparte del stream SSE.

## 3. `_detach_tool` — el puente entre orquestador y JobManager

En `backend/app/chat/ai_orchestrator.py`. Dos funciones internas:

**`_tool_fn()`** — lo que corre en el thread de background. Ejecuta
la tool real vía `ToolExecutor.execute_tool_call` y devuelve el texto
crudo del resultado.

**`_on_done(job)`** — el callback que corre cuando el job termina
(todavía dentro del thread de background, no en el event loop de
asyncio). Hace tres cosas en orden:

1. **`runner.run_after_tools(...)`** — pasa el resultado crudo de la
   tool de vuelta a Claude (con el `tool_use`/`tool_result` sintético
   correspondiente) para que genere una respuesta en lenguaje natural,
   en vez de devolver el texto crudo de la búsqueda. Si esta llamada
   falla, se hace fallback al texto crudo (`raw_text`).
2. **Persistencia** — el mensaje final se guarda como `ChatMessage` en
   la base de datos, para que el próximo turno de chat tenga ese
   intercambio en su historial aunque el usuario no viera el mensaje
   en directo.
3. **`publish_session_event_sync(...)`** — publica un evento
   `proactive_message` con el texto final al canal SSE de la sesión.

Mientras el job corre, el turno de chat original ya ha devuelto una
respuesta sintética inmediata al usuario (`ToolLoopRunOutcome` con
`tool_results_for_claude` indicando `status: "en_progreso"`), para que
Claude pueda generar de forma natural un "dame un segundo, estoy
buscando..." sin esperar al resultado real.

`_BG_SESSION_ID = "default"` está hardcodeado — de momento Sity no
tiene multi-sesión real, así que todo el flujo de background asume
una única sesión de chat activa. Si en el futuro se añade
multi-sesión, este es el punto a revisar primero.

## 4. Canal SSE de sesión — `realtime_events.py`

`backend/app/core/realtime_events.py` separa dos tipos de canal SSE,
con implementaciones deliberadamente distintas:

- **`subscribe(client_turn_id)` / `publish_event(_sync)`** — canal por
  turno de chat, vive solo mientras dura un turno normal
  (`/chat/stream/{turn_id}`), se cierra al recibir `done`/`error`, y
  su cola (`asyncio.Queue` en un `defaultdict`) se elimina al
  desconectar (`_queues.pop(client_turn_id, None)` en el `finally`).
  Efímero por diseño: un turno solo importa mientras el cliente lo
  está esperando activamente.

- **`subscribe_session(session_id)` / `publish_session_event(_sync)`**
  — canal persistente por sesión (`/events/session/{id}`), **nunca se
  cierra por tipo de evento** — solo termina cuando el cliente
  desconecta. Es el canal que recibe `job_start`, `job_done`,
  `job_error` y `proactive_message`.

### `_SessionQueue` — por qué no es un `asyncio.Queue` simple

La primera versión de este canal usaba el mismo patrón que el canal
por turno: `defaultdict(asyncio.Queue)`, con `pop()` al desconectar.
Esto causaba pérdida silenciosa de eventos — si el `EventSource` del
frontend tardaba en (re)conectar, o se caía brevemente (un Service
Worker reiniciando, una red inestable, el navegador en background),
cualquier evento publicado en ese hueco se perdía para siempre: la
cola se borraba al desconectar, y el job en background no reintenta
la publicación.

El diseño actual usa un wrapper `_SessionQueue` por sesión que
**sobrevive a la desconexión**:

```python
@dataclass
class _SessionQueue:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    last_active: float = field(default_factory=time.monotonic)
    subscriber_count: int = 0

_session_queues: dict[str, _SessionQueue] = {}
```

- **La cola no se borra en el `finally` de `subscribe_session`** —
  solo se decrementa `subscriber_count` y se actualiza `last_active`.
  Eventos publicados mientras `subscriber_count == 0` se acumulan y
  se entregan íntegros en cuanto un nuevo subscriber conecta.
- **Ring buffer (`_SESSION_QUEUE_MAX_SIZE = 20`)** — al publicar, si
  la cola ya tiene 20 eventos, se descarta el más antiguo antes de
  añadir el nuevo (`queue.get_nowait()` en `publish_session_event`).
  Evita que un job en bucle, o un fallo que genere eventos sin cesar
  mientras nadie escucha, agote la RAM.
- **TTL (`_SESSION_QUEUE_TTL_SECONDS = 3600`)** — un `_gc_loop()`
  arrancado desde `set_event_loop()` corre cada
  `_SESSION_QUEUE_GC_INTERVAL` (10 min) y llama a `gc_once()`, que
  elimina las entradas de `_session_queues` con `subscriber_count == 0`
  y más de una hora sin actividad. `gc_once()` es pública
  específicamente para poder testearla sin mockear el event loop.

Este diseño resuelve el trade-off: sin TTL ni límite de tamaño, no
borrar la cola al desconectar sería una fuga de memoria sin límite
(cualquier `session_id` que dejara de reconectarse para siempre
crecería indefinidamente); con ambos, la cola sobrevive lo suficiente
para cubrir desconexiones normales (segundos a minutos) sin arriesgar
memoria a largo plazo. Hoy el riesgo práctico es bajo porque
`_BG_SESSION_ID = "default"` es la única sesión que existe
(hardcodeada), pero el mecanismo ya está listo si en el futuro hay
multi-sesión real.

Ambos canales exponen una variante `_sync` para poder publicarse
desde fuera del event loop de asyncio — necesario porque el `on_done`
de `JobManager` corre en un thread del `ThreadPoolExecutor`, no en
una corutina.

```python
def publish_session_event_sync(session_id, event):
    if not session_id or _loop is None or not _loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(publish_session_event(session_id, event), _loop)
```

`_loop` se registra una sola vez, en el startup de FastAPI
(`backend/app/main.py`), y ese mismo registro arranca el `_gc_loop`:

```python
def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop
    loop.create_task(_gc_loop())
```

Sin este registro, `publish_session_event_sync` hace `return`
silenciosamente y ningún evento de background llega nunca a ningún
sitio — sin lanzar excepción, sin loguear nada por defecto. Es el
primer sospechoso a revisar si un futuro bug hace que las tareas en
background vuelvan a quedarse mudas.

### Eventos de error en `_on_done` (commit `e521dd8`)

Los dos bloques `except Exception` de `_on_done` que antes eran mudos
ahora loguean:

- **`bg_after_tools_failed`** — si `runner.run_after_tools` lanza
  excepción. Payload: `job_id`, `tool_name`, `error`, `error_type`.
  Indica que Claude no pudo generar una respuesta en lenguaje natural
  a partir del resultado crudo; el fallback es devolver ese texto crudo.
- **`bg_persist_failed`** — si la escritura del `ChatMessage` en DB
  falla. Payload: igual. Indica que el próximo turno de chat no verá
  el intercambio en su historial.

Si ninguno de los dos aparece en logs y aun así no llega el
`proactive_message`, los candidatos son: (a) `publish_session_event_sync`
devolvió silenciosamente porque `_loop is None or not _loop.is_running()`,
o (b) el servidor fue reiniciado a mitad del job (ver nota abajo).

### Reinicios del backend durante un job en background

Un reinicio del servidor (p.ej. `systemctl restart sity-backend`) mata el
proceso FastAPI, incluyendo el `ThreadPoolExecutor` del `JobManager`. Si un
job está en mitad de `_on_done` cuando llega el SIGTERM:

- El `job_finally` ya se habrá logueado (el `finally` del thread corre).
- La llamada a Claude en `run_after_tools` puede interrumpirse antes de que
  `ai_call_started` se logueé, o entre `ai_call_started` y `ai_call_completed`.
- No aparece `bg_after_tools_failed` porque la excepción no la captura el
  `except Exception` de `_on_done` — el thread simplemente muere.
- Patrón en logs: `job_finally` con `has_on_done: true`, seguido de
  `ai_call_completed` del turno principal, y después nada. Sin
  `bg_after_tools_failed`, sin `proactive`. Esto **no es un bug del
  mecanismo** — es la interrupción esperada del proceso. Verificar si hubo
  un reinicio manual entre las dos entradas de log antes de perseguirlo como bug.

`sse_subscriber_connected` / `sse_subscriber_disconnected` se loguean
en `subscribe_session()` al entrar y al salir (bloque `finally`) —
es la señal más directa para depurar si el problema es de publicación
(backend) o de consumo (nadie escuchando en ese momento). Un patrón a
vigilar: `qsize` creciendo en sucesivos `session_publish_confirmed`
sin que aparezca ningún `sse_subscriber_connected` de por medio es la
prueba de que nadie está conectado — con el diseño actual esto ya no
implica pérdida de datos (la cola los retiene hasta el TTL), pero
sigue siendo la señal correcta para saber que el frontend no está
llegando a conectar.

## 5. Frontend — `useChat.ts`

`mobile/src/hooks/useChat.ts` abre un `EventSource` persistente a
`/events/session/{SESSION_ID}` (con `SESSION_ID = 'default'`, hermano
del `_BG_SESSION_ID` hardcodeado en el backend) en un `useEffect` con
deps `[]`, independiente del ciclo de vida de un turno de chat
concreto:

```typescript
useEffect(() => {
  const es = new EventSource(`/events/session/${SESSION_ID}`);
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === 'job_start') setBackgroundJobsActive(n => n + 1);
    else if (ev.type === 'job_done' || ev.type === 'job_error') { /* baja el contador */ }
    else if (ev.type === 'proactive_message' && ev.text) {
      setMessages(prev => [...prev, { /* nuevo ChatMessage */ }]);
    }
  };

  // Segunda capa de recuperación: si el SSE se cae y reconecta, recargar
  // el historial por si algún resultado ya se guardó en DB mientras la
  // conexión estaba caída (complementa el buffer de _SessionQueue, no
  // depende de él).
  let _reconnecting = false;
  es.onerror = () => { _reconnecting = true; };
  es.onopen = () => {
    if (_reconnecting) { _reconnecting = false; void loadHistory(); }
  };

  return () => es.close();
}, []);
```

Dos capas de recuperación independientes cubren el mismo problema
(pérdida de eventos durante una desconexión) desde ángulos distintos:
el **buffer del backend** (`_SessionQueue`, sección 4) entrega los
eventos acumulados en cuanto el `EventSource` reconecta, mientras que
el **`onerror`/`onopen` del frontend** fuerza un `loadHistory()` — un
`GET` que trae el historial completo desde la BD — como red de
seguridad adicional, por si el evento SSE en sí se perdiera por
cualquier motivo no cubierto por el buffer (por ejemplo, si el TTL de
una hora ya expiró la cola). No son redundantes: uno confía en la
cola en memoria, el otro en la fuente de verdad persistente
(`chatmessage` en SQLite).

`job_start`/`job_done` alimentan el indicador visual de "tarea en
curso" (`BgJobIndicator` en `ChatScreen.tsx`). `proactive_message` es
lo que realmente añade un mensaje nuevo al hilo de chat sin que el
usuario haya hecho nada.

## 6. Infraestructura — proxies y Service Worker

El canal SSE de sesión es una conexión HTTP de muy larga duración
(potencialmente indefinida). Tres capas pueden cortarla sin avisar,
y las tres deben excluir explícitamente `/events/*` de cualquier
comportamiento pensado para peticiones cortas:

- **Caddy** — necesita `flush_interval -1` en el bloque
  `handle /events/* { reverse_proxy localhost:8000 }` (y también en
  `/chat/stream/*`, que usa el mismo patrón para turnos normales).
  Sin esto, Caddy puede bufferizar la respuesta en vez de
  streamearla evento a evento.
- **Cloudflare Tunnel** — `disableChunkedEncoding: true` en
  `originRequest` dentro de `~/.cloudflared/config.yml` ayuda a que
  el túnel no interfiera con el streaming.
- **Service Worker de la PWA** (`mobile/public/sw.js`) — si el SW
  intercepta todas las peticiones con
  `event.respondWith(fetch(event.request))`, el `fetch()` ejecutado
  *dentro* de un Service Worker tiene en Chrome un timeout de idle
  corto (~3 segundos) que no aplica al `fetch`/`EventSource` nativo
  del documento. Esto cortaba la conexión SSE de sesión exactamente a
  los 3s, de forma silenciosa, sin ningún error de red visible en
  Caddy ni en Cloudflare. Fix aplicado:

  ```javascript
  self.addEventListener('fetch', (event) => {
    // SSE de sesión no debe pasar por el SW — fetch() dentro de un SW
    // tiene un idle timeout corto que mata streams de larga duración.
    if (event.request.url.includes('/events/')) return;
    event.respondWith(fetch(event.request));
  });
  ```

  Este fue el causante real de un bug donde el backend generaba y
  publicaba correctamente el `proactive_message`, pero nunca llegaba
  al frontend — ver `docs/decisions.md` para el registro de la
  investigación completa.

- **Vite dev server** — su proxy (`mobile/vite.config.ts`) necesita
  una entrada explícita para `/events`, igual que `/chat`, `/audio`,
  etc. Sin ella, en desarrollo local el `EventSource` recibe el
  `index.html` de la SPA en vez del stream real.

## Extender el sistema

Para añadir una nueva tool "detachable":

1. Añadir su nombre a `TOOL_BLOCKING_POLICIES` con `"detachable"` en
   `backend/app/cortex/tool_schemas.py`.
2. Confirmar que su ejecución vía `ToolExecutor.execute_tool_call`
   funciona igual de bien fuera del ciclo normal del turno (sin
   `client_turn_id`, ya que `_detach_tool` pasa `client_turn_id=None`).
3. No hace falta tocar `JobManager`, `_detach_tool` ni el frontend —
   el pipeline es genérico por diseño.

Si en el futuro se necesita un **watchdog real** (mover una tool
`blocking` a background solo si excede un timeout, en vez de decidirlo
de antemano por nombre), ese mecanismo todavía no existe — habría que
envolver la ejecución inline en `asyncio.wait_for` dentro del bucle de
tools y hacer un detach dinámico si expira. Se barajó durante el
diseño pero no llegó a implementarse; la clasificación estática por
nombre de tool cubre el caso de uso actual (`web_search`).

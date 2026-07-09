# Cancelación de turnos ("botón de parar")

Última actualización: 2026-07-09.

Cómo funciona el botón de parar una respuesta de Sity a mitad de
generación, y el registro completo de los seis bugs encadenados que
hubo que resolver para que funcionara de verdad de extremo a extremo.
Se documenta con detalle porque varios de estos bugs son fáciles de
reintroducir sin darse cuenta al tocar código cercano.

## Resumen del diseño final

```
Usuario pulsa "parar"
         │
         ▼
  cancel() en useChat.ts
         │
    ┌────┴─────────────────────┐
    ▼                          ▼
POST /chat/stream/       abortControllerRef
  {turn_id}/cancel          .current.abort()
    │                          │
    ▼                          ▼
cancel_operation()      AbortSignal 'abort' dispara
(cancellation.py)        → _listenTurn cierra el EventSource
marca cancelled=True       → muestra cancelledMsg() localmente
en _operations[turn_id]    → setStatus('conectado') (spinner para)
    │                       ESTO PASA EN EL NAVEGADOR, INSTANTÁNEO,
    ▼                       SIN ESPERAR AL BACKEND
is_cancelled(turn_id)
comprobado dentro del
streaming a Anthropic
(ClaudeProvider.generate)
    │
    ▼
break + cierre del stream
→ AIResponse(ok=False, error_type="cancelled")
    │
    ▼
final_response_builder guarda
"Has cancelado la operación."
(nunca texto vacío)
    │
    ▼
routes_chat.py: NO publica
evento SSE "response" para
turnos cancelados (ya se
mostró en el navegador)
```

Dos mecanismos independientes que convergen al mismo resultado
visual:

1. **Cancelación instantánea en el navegador** — al pulsar el botón,
   `useChat.ts` aborta el `AbortSignal` de inmediato. Esto NO depende
   de que el backend responda nada; el spinner debe pararse y la
   burbuja de "cancelado" debe aparecer en el momento del click,
   siempre.
2. **Cancelación real en el backend** — en paralelo, se avisa al
   backend (`POST .../cancel`) para que dentro del streaming a
   Anthropic deje de generar tokens de verdad, ahorrando coste real.
   Esto es un beneficio adicional (ahorro de tokens), no lo que hace
   que el spinner pare — si este mecanismo fallara, la UX en el
   navegador seguiría funcionando bien.

Separar estos dos mecanismos fue clave: en las primeras rondas de fix
se intentó que el frontend esperara al backend para saber cuándo
parar, lo cual dejaba el spinner colgado si algo fallaba en el camino
de vuelta del servidor.

## Los seis bugs, en orden de aparición

### 1. `is_cancelled()` nunca se comprobaba durante la llamada al modelo

`ClaudeProvider.generate()` usaba `client.messages.create()`, una
llamada síncrona no-streaming. Una vez lanzada, no hay forma de
abortarla en pleno vuelo — solo se podía evitar *procesar* su
resultado, no *generarlo*. `is_cancelled()` solo se comprobaba entre
pasos del bucle de tools (`tool_loop_runner.py`), así que cualquier
respuesta sin tools (la mayoría) ignoraba por completo la cancelación.

**Fix:** migrar a `client.messages.stream()`, iterando chunk a chunk
y comprobando `is_cancelled()` en cada uno.

### 2. `client_turn_id` llegaba `None` — en el camino principal

Al añadir el parámetro `client_turn_id` a `AIRequest` para poder
comprobar la cancelación dentro del streaming, el primer intento solo
lo propagó en `build_chat_ai_request` (usado solo tras
`no_action_required`, un camino secundario) y
`build_after_tools_ai_request`. **`build_planner_ai_request`** — la
función que arma la llamada *principal* del planner en cada turno
normal — se quedó sin el parámetro. Como `AIRequest.client_turn_id`
tiene default `None`, y `is_cancelled(None)` devuelve `False` sin más
(`cancellation.py`: `if not client_turn_id: return False`), el
chequeo se ejecutaba pero siempre contra `None`.

**Lección:** al añadir un parámetro nuevo a un `AIRequest`, hay que
propagarlo en *todos* los builders de `ai_request_builder.py` y en
*todas* las llamadas a `runner.run_planner()` /
`runner.run_after_tools()` en `ai_orchestrator.py` — no solo en el
camino que se está probando en ese momento.

### 3. `return` dentro del `with stream:` disparaba una excepción de cierre

Al detectar cancelación dentro del bucle de streaming, el primer
intento hacía `return AIResponse(...)` directamente dentro del
`with self.client.messages.stream(**kwargs) as stream:`. Esto dispara
`stream.__exit__()` sobre una conexión HTTP todavía viva (el stream no
se había consumido del todo), y el SDK de Anthropic lanza una
excepción al intentar cerrar en ese estado. Esa excepción escapaba
hasta `AIGateway.generate()`, caía en su `except Exception` genérico,
y sobreescribía el `error_type="cancelled"` real con el mensaje
genérico de "No he podido contactar con Claude...".

**Fix:** usar `break` (no `return`) dentro del bucle, guardar el
`AIResponse` cancelado en una variable local, envolver todo el
`with` en un `try/except` que suprime cualquier excepción de cierre
*solo si* ya se había detectado cancelación, y devolver el
`AIResponse` guardado después de salir del `with` limpiamente:

```python
_cancelled: AIResponse | None = None
message = None
try:
    with self.client.messages.stream(**kwargs) as stream:
        for _chunk in stream:
            if is_cancelled(request.client_turn_id):
                _cancelled = AIResponse(ok=False, error_type="cancelled", ...)
                break
        else:
            message = stream.get_final_message()
except Exception:
    if _cancelled is not None:
        pass  # excepción esperada al cerrar un stream a medias
    else:
        raise

if _cancelled is not None:
    return _cancelled
```

### 4. El turno cancelado se guardaba con texto vacío

`final_response_builder.py` guardaba `text=""` en el `ChatMessage`
cuando la respuesta venía marcada como cancelada, dejando una burbuja
rota en el historial. Además, un historial con un turno de texto vacío
podía dejar dos mensajes `role: user` consecutivos en la siguiente
llamada a Anthropic (que los rechaza).

**Fix:** guardar siempre `"Has cancelado la operación."` como texto
del turno cancelado, para que el historial quede pareado
usuario/asistente igual que cualquier otro turno.

### 5. El SSE de turno duplicaba/pisaba la burbuja ya mostrada

`routes_chat.py` seguía publicando el evento SSE `"response"` (con
texto vacío) incluso para turnos cancelados. Como el frontend ya
mostraba su propia burbuja de cancelado desde el `abort` listener
local (mecanismo 1 de la sección anterior), este evento llegaba tarde
y duplicaba o sobreescribía la burbuja correcta.

**Fix:** omitir el evento `"response"` cuando el turno se cancela; el
frontend ya se encarga de mostrar el mensaje.

### 6. El `abort` listener no desatascaba el spinner

En `useChat.ts`, el listener de `abort` cerraba el `EventSource` pero
nunca llamaba a `setStatus('conectado')`, así que el spinner de
"procesando" se quedaba colgado indefinidamente aunque todo lo demás
funcionara.

**Fix:** en el listener de `abort`, además de cerrar el `EventSource`,
llamar a `setStatus('conectado')` y añadir `cancelledMsg()` de
inmediato (con un guard `responseSeen` para evitar duplicar el mensaje
en el caso raro de que un evento `"response"` llegara justo antes del
abort).

## El séptimo problema — no era un bug de código

Tras corregir los seis puntos anteriores, el botón seguía sin
funcionar en el navegador, y **ningún** `console.log` de diagnóstico
añadido en `useChat.ts` aparecía en la consola — ni siquiera tras
`Shift+F5` repetido.

Dos causas independientes, ambas de infraestructura de despliegue,
no de lógica:

### 7a. Service Worker atascado en "waiting to activate"

Un SW nuevo se queda en estado `waiting` cuando el navegador detecta
una versión distinta de `sw.js` pero un cliente/pestaña controlado
por el SW viejo sigue abierto. El `self.skipWaiting()` dentro del
propio `install` del SW nuevo no es suficiente por sí solo para forzar
que tome el control sobre un SW viejo que ya está `activated`.

Diagnóstico: en DevTools → Application → Service Workers, aparecían
**dos** entradas simultáneas — una `activated and is running` (el
viejo) y otra `waiting to activate` (el nuevo, con el fix real).
`Shift+F5` no fuerza esta transición.

**Fix aplicado en caliente** (una vez, manual): botón "skipWaiting"
en DevTools sobre el worker en waiting, luego recargar.

**Fix permanente en código** — patrón estándar de `postMessage` para
forzar la activación desde el cliente en vez de confiar solo en el
comportamiento por defecto del navegador:

```javascript
// sw.js
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});
```

```javascript
// main.tsx
navigator.serviceWorker.register('/sw.js').then((reg) => {
  if (reg.waiting) reg.waiting.postMessage('SKIP_WAITING');
  reg.addEventListener('updatefound', () => {
    const newWorker = reg.installing;
    newWorker?.addEventListener('statechange', () => {
      if (newWorker.state === 'installed' && reg.waiting) {
        reg.waiting.postMessage('SKIP_WAITING');
      }
    });
  });
  reg.update();
}).catch(() => {});

navigator.serviceWorker.addEventListener('controllerchange', () => {
  window.location.reload();
});
```

### 7b. El bundle servido nunca se reconstruyó

Incluso con el Service Worker correcto activo, el archivo JS servido
seguía siendo `index-Cd6a9pej.js` — el mismo hash de **antes** de
varias rondas de fixes (contenía incluso un `console.log` de una
ronda de debug de sesiones anteriores que se suponía ya eliminado).

Causa: el flujo de trabajo de esta sesión reiniciaba el backend
(`systemctl restart sity-backend`) en cada fix, pero **no** ejecutaba
`npm run build` en `mobile/` tras los cambios de frontend. Caddy sirve
directamente el contenido de `mobile/dist/`, generado por Vite con
hashes de contenido en el nombre de archivo — sin rebuild, el archivo
en disco no cambia, y ningún cambio de código llega jamás al
navegador, Service Worker o no.

Un detalle que llevó a confusión: existe un servicio systemd
`sity-frontend` en la Pi, pero **es solo el servidor de desarrollo de
Vite en el puerto 5173** — no tiene ninguna relación con lo que Caddy
sirve en `sity.aletm.com`. Reiniciar ese servicio no reconstruye ni
redespliega nada de producción.

**Regla a partir de ahora: cualquier cambio en `mobile/src/` o
`mobile/public/` requiere `npm run build` desde `mobile/` antes de
que sea visible en `sity.aletm.com`.** No existe hoy ningún hook ni
script que lo haga automáticamente — es un paso manual.

## Verificación tras un cambio de frontend

Para confirmar que un cambio realmente llegó al navegador:

1. `cd ~/projects/sity/mobile && npm run build` — comprobar que el
   hash de `dist/assets/index-*.js` cambió respecto al build
   anterior.
2. `Shift+F5` en el navegador.
3. DevTools → Sources → abrir el `index-*.js` cargado bajo
   `sity.aletm.com/assets/` y confirmar que el hash coincide con el
   que se acaba de generar.
4. Si no coincide, revisar DevTools → Application → Service Workers
   por si hay una versión `waiting` sin activar.

## Extender el sistema de cancelación

Si se añade un nuevo tipo de llamada al modelo (un nuevo
`build_*_ai_request` en `ai_request_builder.py`), recordar:

1. Añadir `client_turn_id: str | None = None` a la firma del builder
   y propagarlo al `AIRequest` que construye.
2. Pasar `client_turn_id=request.client_turn_id` en la llamada real
   desde `ai_orchestrator.py`.
3. Si esa llamada usa el SDK de streaming directamente (no pasa por
   `ClaudeProvider.generate`/`generate_with_tool_results`), replicar
   el patrón `break` + `try/except` de la sección 3 — nunca hacer
   `return` dentro de un `with client.messages.stream(...)` a medio
   consumir.

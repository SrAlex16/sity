# Cola de turnos por sesión

Última actualización: 2026-09-14.

## Problema que motiva este mecanismo

El 2026-09-14 se detectó durante una auditoría con agentes de IA que dos mensajes
enviados con ~2 s de diferencia desde la misma sesión (trc_938febd74c5a a las
11:45:41.755 y trc_66ca5c8e64fa a las 11:45:43.879) se procesaron en paralelo.
El segundo turno construyó su contexto sin ver la respuesta del primero —
que todavía estaba generándose — y rellenó los huecos con contenido inventado
("sierra", "Pico Roble", receta de volcán de chocolate "ya pasada" cuando no
lo había sido en ese punto).

La causa raíz: `_run_turn_in_background` se lanzaba en el thread pool sin ningún
mecanismo de serialización por sesión.  Cualquier número de mensajes de la misma
sesión podían ejecutarse concurrentemente.

## Diseño

### Invariante garantizado

Cuando el turno B llama a `_chat_message_inner`, la respuesta de Sity al turno A
ya está persistida en la DB.  B construye su historial con contexto completo.

### Implementación

**`app/core/session_queue.py`** — módulo puro, sin I/O.

```
claim_session_slot(session_id) → int (versión monotónica)
is_superseded(session_id, version) → bool
acquire_session_lock(session_id) → threading.Lock (ya adquirido)
```

Cada sesión tiene un `threading.Lock` independiente.  El mecanismo es
**in-memory únicamente** — adecuado para despliegue en Raspberry Pi de un único
usuario.  Los locks nunca se eliminan (crecimiento negligible, < 100 sesiones en
toda la vida del proceso).

**`app/chat/turn_runner._run_turn_in_background`** — flujo modificado:

```
1. claim_session_slot(session_id)  → my_version
2. acquire_session_lock(session_id)   (bloquea hasta que el turno anterior termine)
3. is_superseded(session_id, my_version)?
       Sí → publica "done", sale sin llamar al modelo
       No → procesa normalmente
4. finally: session_lock.release()
```

El HTTP 202 ya se devuelve antes de que el thread empiece a esperar el lock —
el usuario recibe `{turn_id, status: "processing"}` inmediatamente.

### Lógica de supersede

El contador de versión detecta el caso donde mensajes llegan más rápido de lo que
puede completarse la llamada al modelo.  Si el turno A fue a adquirir el lock pero
antes de que pudiera comprobar la versión, el turno B registró una versión más
nueva, A verá `is_superseded = True` y saldrá sin procesar.

En la práctica sólo ocurre con mensajes sub-100 ms.  Para el caso del incidente
(2 s de diferencia):

```
A llega → versión=1 → adquiere lock inmediatamente → comprueba versión=1 ✓ → procesa
B llega 2 s después → versión=2 → bloquea en lock (A lo tiene)
A termina, persiste respuesta → libera lock
B adquiere lock → comprueba versión=2 ✓ → procesa con contexto completo de A
```

**Decisión deliberada:** no se implementó "cancelar el turno pendiente cuando
llega uno nuevo".  El mecanismo de cancelación activa (botón de parar) ya existe
y el usuario puede usarlo si quiere interrumpir una respuesta en curso.  Añadir
cancelación automática de mensajes en cola añadiría complejidad
desproporcionada para un caso de uso marginal (el Pi es de un solo usuario).

### Sesiones distintas

Los locks son estrictamente por `session_id`.  Nunca existe bloqueo cruzado entre
sesiones distintas — dos sesiones distintas siempre pueden ejecutar turnos en
paralelo.

## Tests

`tests/test_session_queue.py` — 16 tests cubren:

- Versioning y detección de supersede (8 tests unitarios sobre `session_queue.py`)
- Independencia de locks entre sesiones distintas
- Serialización: el turno B no empieza hasta que A termina
- Supersede: turno B emite sólo `done` sin llamar al modelo
- Paralelismo entre sesiones distintas
- Liberación del lock si `_chat_message_inner` lanza excepción

## Relación con `turn-cancellation.md`

La cancelación activa (botón de parar) usa `cancel_operation(turn_id)` en
`app/core/cancellation.py` y sigue funcionando igual.  El lock de sesión se
libera correctamente incluso en turnos cancelados — la señal `cancelled` se
detecta dentro del turno en ejecución y `_run_turn_in_background` termina
normalmente, liberando el lock en su `finally`.

# Contexto de tareas multi-paso (task_context)

Última actualización: 2026-07-10.

Cómo Sity recuerda datos concretos ya resueltos (un URI, un ID de
dispositivo) a lo largo de una secuencia de varios turnos de
seguimiento — sin depender de que esos datos quepan en la ventana de
historial que ve el planner, y sin ninguna heurística de palabras
clave.

## El problema que resuelve

El planner no ve toda la conversación en cada llamada — solo una
ventana reciente (`planner_history_limit`, ver más abajo). En una
tarea de varios pasos con mensajes de seguimiento cortos ("sí", "en
el pc", "ya lo he abierto"), un dato resuelto en el primer turno
(por ejemplo, el URI de una playlist tras identificarla) podía
quedar fuera de esa ventana en el turno 4 o 5 — el modelo terminaba
preguntando algo que ya sabía, o peor, **inventando** un valor
plausible pero falso (un `device_id: "pc"` literal en vez del ID real
que ya conocía de una llamada anterior a `spotify_list_devices`).

Caso real que lo motivó, documentado con logs completos: pedir a
Sity que reprodujera una playlist, confirmar cuál era, que fallara
por falta de dispositivo activo, abrir Spotify, y pedir de nuevo —
en el turno final el modelo había "olvidado" tanto el URI como el
device_id correctos.

## Diseño: dos capas complementarias, no una sola solución

### Eje B — ventana de historial del planner, ampliada

`planner_history_limit` pasó de `4` (hardcodeado en
`ai_turn_prep.py`) a `10`, configurable en `config/default_config.yaml`
bajo `ai:`. Cubre el caso donde los datos relevantes están en texto
libre dentro de una secuencia moderada de turnos. Coste estimado:
+150 tokens/turno en el caso típico de Sity (mensajes cortos) — se
descartó explícitamente cualquier lógica de detección por palabras
clave (el mecanismo `history_limit_for_message` ya existente para el
historial de chat normal, distinto de este, tiene ese patrón y se
consideró frágil: ninguna de sus listas de palabras cubre frases de
seguimiento naturales como "en el pc").

### Eje A — estado estructurado persistente, por sesión

Cuando un handler resuelve un dato concreto y reutilizable, puede
devolverlo en `ToolExecutionResult.task_context: dict[str, str] | None`.
El executor lo persiste y lo reinyecta en el `planner_user_message`
de **cada turno siguiente**, con independencia del tamaño de la
ventana de historial — es la garantía de que un dato clave no se
pierde aunque la secuencia sea más larga de lo que cubre el Eje B.

```python
# En un handler:
return ToolExecutionResult(
    ...,
    task_context={"spotify_uri": uri, "spotify_device_id": device_id},
)
```

```
Contexto de tarea activa (datos ya resueltos en este hilo):
- spotify_uri: spotify:playlist:6Ge4eKOxcQ4pSvyuRkoqA6
- spotify_device_id: f7957618c29a3180751f26887d5f11a05cbcbcf5

<mensaje del usuario>
```

El mecanismo es completamente genérico — el executor y el bucle no
saben qué significan las claves (`spotify_uri`, `spotify_device_id`
son convención del handler de Spotify, no del sistema). Cualquier
handler de cualquier dominio puede aportar entradas sin que el código
central sepa nada de ese dominio.

## Almacenamiento — `backend/app/core/task_context.py`

Persistido en SQLite vía el modelo `Setting` ya existente, mismo
patrón que `spotify:previous_context` (ver `docs/architecture.md`,
sección Spotify): `key = "task_context:{session_id}"`,
`value_json` = el dict serializado.

**Por qué SQLite y no memoria de proceso:** decisión explícita tras
valorar ambas opciones. El backend se reinicia con frecuencia durante
desarrollo (varias veces en un mismo día), y también en producción
normal (deploys). Memoria de proceso perdería cualquier tarea en
curso en cada reinicio sin ningún aviso al usuario — un caso real
observado el mismo día de este diseño, no hipotético. SQLite es
coherente con el resto del proyecto y con el precedente directo de
`previous_context`.

### Ciclo de vida

- **Merge-upsert** (`save_task_context`) — cada actualización hace
  merge con lo ya guardado, no sobreescribe claves no mencionadas.
  Así, si `spotify_play` guarda `spotify_uri` en un turno y
  `spotify_list_devices`/`spotify_play` guarda `spotify_device_id`
  en otro, ambas conviven en el mismo estado.
- **Cierre explícito** — un handler devuelve `task_context={}` (dict
  vacío, no `None`) para señalar que la tarea se completó y todo el
  estado debe borrarse. Convención simple: `None` significa "esta
  tool no aporta ni cambia nada al task_context", `{}` significa
  "borra todo, la tarea terminó".
- **TTL por tiempo absoluto** — `Setting.updated_at` se compara contra
  un límite configurable (`task_context.ttl_minutes` en
  `default_config.yaml`, default **30 minutos**) en cada lectura. Se
  descartó explícitamente un TTL por número de turnos sin tool_calls:
  un turno de seguimiento sin herramientas (ej. una pregunta
  tangencial de un solo turno, "¿cuántos dispositivos tienes?") no
  debería agotar el contador de una tarea que sigue activa. El tiempo
  absoluto es más robusto ante ese caso y más simple de implementar
  (no requiere mantener un contador de turnos por sesión).

### Logging

- `task_context_updated` (INFO) — al guardar, con las **claves**
  modificadas en el payload, nunca los valores (pueden ser URIs o IDs
  de recursos privados).
- `task_context_cleared` (INFO) — al limpiar, con el motivo
  (`explicit_close` o `ttl_expired`).

## Interacción con el bucle multi-turno

El task_context se actualiza **entre turnos**, no dentro del mismo
turno — durante la ejecución del bucle multi-turno (ver
`docs/multi-turn-tool-calling.md`), el modelo ya tiene acceso directo
a los resultados de tools de rondas anteriores del mismo turno vía
`extra_prior_rounds`. El task_context resuelve el problema
complementario: que esos datos sigan disponibles en el turno
**siguiente**, cuando `extra_prior_rounds` ya no aplica (es un turno
de chat nuevo).

## Interacción con cancelación

Ninguna. El task_context es por sesión y no se ve afectado por la
cancelación de un turno individual — una tarea puede retomarse
normalmente tras cancelar un turno a mitad.

## Aplicación real: Spotify

`handle_spotify_play` guarda `spotify_uri` (y `spotify_device_id`
cuando la reproducción tiene éxito con un device_id conocido) tras
resolver un URI, sea por búsqueda de texto, URI directa, o resolución
desde `spotify_list_playlists`. Esto es lo que permite que, en el
escenario real que motivó el diseño (playlist → sin dispositivo →
abrir Spotify → reproducir), el segundo intento use el URI correcto
sin tener que relanzar `spotify_list_playlists` ni arriesgarse a que
`_search_uri` interprete mal una búsqueda de texto ambigua.

## Casos de validación (`tests/test_task_context.py`)

Seis casos, con handlers ficticios (mismo criterio que los tests del
bucle multi-turno — nada de nombrar dominios reales en el mecanismo):

1. Datos resueltos sobreviven varios turnos de seguimiento sin que la
   tool original se vuelva a llamar.
2. El estado se limpia cuando un handler señala cierre explícito
   (`task_context={}`).
3. El estado expira por TTL de tiempo, no de turnos.
4. La ventana ampliada (Eje B) por sí sola cubre una secuencia de 5
   turnos sin necesidad de `search_conversation_history`.
5. Merge correcto cuando varios handlers (en distintas rondas del
   bucle multi-turno) aportan claves distintas al mismo turno.
6. Un dato actualizado (ej. el usuario cambia explícitamente de
   dispositivo) sobreescribe correctamente el valor anterior, sin
   quedar un valor obsoleto mezclado con el nuevo.

## Qué no cubre este diseño

- **Sesiones muy largas con una sola tarea sin interrupción**: si la
  misma tarea se extiende mucho más allá de lo que cubre el TTL de 30
  minutos o involucra datos que ningún handler expone como
  `task_context`, el mecanismo no ayuda — la alternativa en ese caso
  es que el planner use `search_conversation_history` explícitamente.
- **Estructuras de datos complejas**: el diseño solo contempla pares
  `str → str`. Listas o estructuras anidadas quedan fuera del alcance
  actual.
- **Multi-sesión real**: como el resto del sistema de sesiones (ver
  `docs/background-tasks.md`), el task_context se guarda por
  `session_id`, pero hoy solo existe una sesión (`"default"`,
  hardcodeada). Si en el futuro hay multi-sesión real, el mecanismo
  ya está preparado (la clave incluye `session_id`), sin cambios
  necesarios.

## Proceso de análisis previo

Antes de implementar el mecanismo se evaluaron dos revisiones del
diseño (`docs/task-context-analysis.md`, 2026-07-10 — ahora eliminado).
Las dos decisiones clave que se descartaron explícitamente:

- **TTL por turnos sin tool_calls** — descartado. Un turno tangencial
  sin tools (ej. "¿cuántos dispositivos tienes?") consumiría el contador
  aunque la tarea siga activa. El tiempo absoluto (`Setting.updated_at`)
  es más robusto y no requiere contador extra.

- **Memoria de proceso en vez de SQLite** — descartado. El backend se
  reinicia varias veces al día en desarrollo y en producción. Un caso
  real de pérdida de tarea-en-curso por reinicio ocurrió durante el
  mismo día de desarrollo de este fix — no era un riesgo hipotético.
  SQLite sigue el mismo patrón que `spotify:previous_context` ya
  establecido.

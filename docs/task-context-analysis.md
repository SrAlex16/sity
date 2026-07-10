# Análisis: pérdida de contexto en tareas multi-paso

Última actualización: 2026-07-10 (rev. 2: SQLite + análisis TTL).

## Problema documentado

En una secuencia de 5 turnos para ejecutar una acción que requería
resolver primero un recurso (URI) y luego un dispositivo, el planner
perdió datos ya resueltos en turnos anteriores y terminó
preguntando información que ya tenía, o inventando valores (un ID
de dispositivo literal en vez del ID real de la API).

**Causa raíz confirmada por logs**: `planner_history_limit = 4` está
hardcodeado en `ai_turn_prep.py:94`. Con mensajes cortos de seguimiento
(2–16 chars típicos en este flujo), la ventana de 4 mensajes solo cubre
los 2 turnos inmediatamente anteriores. El turno 1, donde se resolvió
el recurso, quedó fuera en el turno 4.

**Por qué la función `history_limit_for_message` no ayuda aquí**:
opera sobre el texto del mensaje del usuario. Frases de seguimiento
como "en el pc", "ya lo he abierto" o "la playlist que te dije" no
activan ninguno de los tres grupos de palabras clave de
`toolset_selector.py:321`. El mecanismo existente viola el mismo
principio de no-hardcodear que el resto del proyecto, y además no
cubre el caso que causó el bug.

---

## Solución en dos ejes (se combinan)

### Eje A — Estado estructurado para datos resueltos en tareas activas

**Principio**: cuando el planner resuelve un dato concreto y
reutilizable dentro de una tarea multi-paso (un URI de recurso, un ID
de dispositivo, un ID de evento, etc.), ese dato debe quedar disponible
de forma fiable en turnos siguientes sin depender de que el modelo
lo lea en texto libre dentro de una ventana de historial limitada.

#### Dónde vive el estado

Persistido en SQLite usando el modelo `Setting`, con el mismo patrón
ya implementado en `spotify_tools.py` para `spotify:previous_context`
(`_save_previous_context` / `_load_previous_context`):

```python
key   = "task_context:{session_id}"   # ej. "task_context:default"
value_json = json.dumps({"recurso_uri": "...", "dispositivo_id": "..."})
source = "task_context"
```

Un read + un upsert por turno — mismo coste que ya asume
`spotify:previous_context` en cada llamada a `spotify_play` o
`spotify_resume_previous`. En SQLite con WAL (modo ya activo en el
proyecto) esto es una operación de microsegundos, sin impacto
perceptible en latencia.

**Por qué SQLite en vez de memoria de proceso**: durante el desarrollo
hay múltiples reinicios de backend al día. En producción también
ocurren reinicios (deploys, watchdog). Memoria de proceso pierde
cualquier tarea en curso sin aviso en cada reinicio — un caso real,
no hipotético, dado lo ocurrido durante el propio día de desarrollo de
este fix. SQLite es coherente con el resto del proyecto (todo lo que
importa ya vive ahí) y con el precedente directo de `previous_context`.

Se inyecta en el `planner_user_message` de cada turno mientras haya
entradas, como bloque explícito antes del mensaje del usuario:

```
Contexto de tarea activa (datos ya resueltos en este hilo):
- recurso_uri: spotify:playlist:6Ge4eKOxcQ4pSvyuRkoqA6
- dispositivo_id: f7957618c29a3180751f26887d5f11a05cbcbcf5

<mensaje del usuario>
```

El planner ve esto **en cada turno** mientras la tarea siga activa,
independientemente del tamaño de la ventana de historial.

#### Cómo un handler contribuye al estado

Se añade un campo opcional a `ToolExecutionResult`:

```python
@dataclass
class ToolExecutionResult:
    tool_name: str
    ok: bool
    message: str
    updated_parameters: list[str]
    raw_result: dict[str, Any]
    task_context: dict[str, str] | None = None  # nuevo, opcional
```

Un handler que resuelve un dato reutilizable devuelve:

```python
return ToolExecutionResult(
    ...,
    task_context={"recurso_uri": uri, "dispositivo_id": device_id}
)
```

El executor acumula estas entradas en el `_task_context` de la sesión.
El mecanismo es totalmente genérico: el executor no sabe qué significa
`recurso_uri` ni `dispositivo_id` — solo los persiste y los reinyecta.

Las claves son strings arbitrarios definidos por cada handler. No hay
registro central de qué claves existen: cada handler decide qué exponer.

#### Limpieza del estado (lifecycle)

El estado de tarea se limpia en cualquiera de estas condiciones:

1. **El handler señala cierre explícito**: devuelve `task_context={}`
   (dict vacío). Convenio: la tarea se completó, borrar todo.

2. **TTL por tiempo transcurrido**: si `Setting.updated_at` tiene más
   de T minutos de antigüedad, el estado se descarta en la lectura del
   turno siguiente. T configurable en `default.yaml`. Valor propuesto:
   **30 minutos** (ver análisis abajo).

3. **Cambio de dominio inferido**: si el siguiente turno con tool_calls
   activa un dominio completamente distinto (por ejemplo, el estado
   tenía claves `recurso_uri` de Spotify y el siguiente turno usa
   únicamente tools de calendario), el estado se borra antes de
   inyectarlo. La detección es estructural: si ninguna de las claves
   del estado aparece en las tool_calls del turno actual, se descarta.

   Esta tercera condición es opcional para la implementación inicial.
   Las dos primeras son suficientes para el caso base.

#### Análisis del TTL (condición 2)

La versión inicial del documento proponía "N turnos sin tools" como
criterio de expiración. Tras análisis, se prefiere **tiempo absoluto**
sobre conteo de turnos.

**¿Por qué no conteo de turnos?**

El criterio "N turnos sin tool_calls" requiere mantener un contador
de turnos-desde-última-tool por sesión, o inspeccionar el historial
reciente para detectar si algún turno anterior usó tools. Ambos añaden
complejidad sin aportar más precisión que el tiempo. Además, presenta
un problema estructural: si el usuario hace una pausa corta (una
pregunta de un turno sin tools: "¿cuántos dispositivos tienes?"), eso
consume un turno del contador aunque la tarea siga activa. Un TTL de
3 turnos se agotaría en una secuencia normal de seguimiento.

**¿Por qué tiempo absoluto?**

El campo `Setting.updated_at` ya existe en el modelo y se actualiza
en cada escritura. La comprobación es una resta de timestamps — sin
contadores, sin estado adicional. Y es más fiel al comportamiento
real del usuario: una tarea se abandona cuando el usuario se va a
hacer otra cosa, no cuando responde N veces sin tools.

**Riesgos de calibración:**

| TTL demasiado corto | TTL demasiado largo |
|---------------------|---------------------|
| Se pierde contexto de una tarea legítimamente interrumpida (llamada de teléfono, pausa, pregunta tangencial seguida de retomar la tarea) | Arrastra datos de una tarea completada o abandonada a una conversación distinta posterior — riesgo de confusión: el planner ve `dispositivo_id: f79...` de una sesión de Spotify de hace una hora cuando el usuario está preguntando sobre el calendario |
| El usuario retoma: "continúa" — el planner ya no tiene el URI ni el device_id → tiene que resolver todo de nuevo | Similar en espíritu al bug de contextopollution HA/Spotify ya documentado: contexto viejo influyendo mal en decisiones nuevas |

**Valor propuesto: 30 minutos.**

Justificación con el mismo criterio que el límite de 10 mensajes del Eje B:

- **5 min**: demasiado agresivo. Una pausa para coger el móvil, ir al
  baño o revisar algo en el PC supera los 5 minutos. Sity es un
  asistente doméstico — estas interrupciones son el caso normal.
- **15 min**: mejor, pero una llamada telefónica media dura más. El
  usuario volvería a "¿dónde estábamos?" y el contexto ya habría
  expirado.
- **30 min**: cubre la inmensa mayoría de interrupciones naturales sin
  ser una tarea completada. Si el usuario no retoma una tarea en 30
  minutos, es razonable asumir que ya no la va a retomar en el mismo
  hilo o que prefiere empezar de nuevo. Coincide con el TTL de
  inactividad de sesión que usa la mayoría de asistentes domésticos
  (Alexa, Google Home en modo "continuación de conversación").
- **60 min**: generoso en exceso. Un contexto de Spotify de hace una
  hora podría mezclarse con una conversación de Calendar posterior,
  produciendo exactamente el tipo de confusión que el TTL pretende
  evitar.

```yaml
# config/default.yaml
task_context:
  ttl_minutes: 30   # tiempo sin actividad para expirar task_state
```

**Latencia de la comprobación**: una lectura SQLite de un solo row por
key única (índice existente). Mismo coste que `_load_previous_context`
de Spotify — microsegundos.

#### Privacidad / logging

Los cambios de estado se trazan en el log de observabilidad:
- `event: task_context_updated` — cuando un handler añade o actualiza
  entradas (payload: claves modificadas, no valores).
- `event: task_context_cleared` — cuando el estado se limpia, con
  motivo (`ttl_expired`, `explicit_close`, `domain_change`).

Los valores no se loguean (pueden contener IDs o URIs de recursos
privados). Solo las claves.

---

### Eje B — Tamaño de ventana de historial dinámico, sin keywords

#### Opción rechazada: más listas de keywords

No se propone ninguna. El mecanismo actual en `history_limit_for_message`
ya demuestra su fragilidad: no puede cubrir el espacio de frases de
seguimiento natural sin convertirse en una lista de mantenimiento
permanente.

#### Opción evaluada: señal de tool_activity en historial reciente

La señal estructural más limpia disponible sin cambios de esquema es:
¿el historial reciente contiene mensajes que sugieren que un turno
anterior ejecutó tools?

El problema es que `planner_prior_messages` solo contiene el texto
guardado de mensajes de usuario y asistente — no incluye los tool calls
intermedios (que son transitorios dentro del turn loop). La única forma
de detectar actividad de tools desde el historial sería:

- Guardar un marcador en el mensaje de asistente cuando el turno usó
  tools (requiere cambio de esquema o convención de texto frágil), o
- Consultar los logs en tiempo real (acoplamiento no deseado).

Esta señal existe en principio, pero extraerla del historial guardado
tiene fricción.

#### Opción recomendada: elevar el límite base universalmente

Dado que:

1. Los mensajes guardados en `planner_prior_messages` son texto de
   conversación (corto, sin resultados de tools). Los resultados de
   tools son transitorios dentro del turn loop, no se guardan en la
   tabla `chatmessage`.
2. El coste real de subir de 4 a 10 mensajes es mínimo (ver estimación
   abajo).
3. El principio del proyecto es preferir simplici dad con margen
   generoso antes que heurísticas frágiles.

**Propuesta**: reemplazar el hardcode `planner_history_limit=4` por
un valor configurable en `config/default.yaml`, con valor por defecto
de **10**.

```yaml
# config/default.yaml
tokens:
  planner_history_limit: 10   # mensajes de conversación para el planner
```

Con 10 mensajes, una secuencia de 5 turnos de seguimiento (10 mensajes
user + assistant) entra completa en la ventana. Es el caso que motivó
este análisis.

Para conversaciones donde se quiera más ventana (sesiones largas con
muchos seguimientos), el valor puede subirse a 20 sin impacto
significativo (ver estimación).

---

## Estimación de coste/latencia — Eje B

### Caso típico de Sity (mensajes cortos, 10–30 tokens/mensaje)

| Escenario | Tokens adicionales por turno | Coste adicional (Haiku 4.5) |
|-----------|-----------------------------|-----------------------------|
| Base actual (4 msgs) | — | — |
| Propuesto (10 msgs) | +6 msgs × ~25 tokens = **+150 tokens** | +$0.00012/turno |
| Generoso (20 msgs) | +16 msgs × ~25 tokens = **+400 tokens** | +$0.00032/turno |

El sistema prompt de Sity (~8066 tokens) ya está cacheado. Los
`planner_prior_messages` son la única parte no cacheada que crece.
El incremento es **irrelevante en práctica** para el uso doméstico.

### Caso peor realista (mensajes largos, 200 tokens/mensaje)

| Escenario | Tokens adicionales por turno | Coste adicional (Haiku 4.5) |
|-----------|-----------------------------|-----------------------------|
| Base actual (4 msgs) | — | — |
| Propuesto (10 msgs) | +6 msgs × ~200 tokens = **+1200 tokens** | +$0.00096/turno |
| Generoso (20 msgs) | +16 msgs × ~200 tokens = **+3200 tokens** | +$0.00256/turno |

Los mensajes de asistente de Sity raramente superan 100 tokens
(verbosity_level = 0.03 en el perfil de personalidad). El caso de 200
tokens/mensaje es el techo real.

**Latencia**: el planner usa Haiku 4.5, cuya latencia está dominada
por el tiempo de primera respuesta, no por el tamaño del contexto de
entrada. En la práctica, +150–1200 tokens de entrada no producen
diferencia perceptible en latencia.

---

## Interacción entre A y B

Son independientes en implementación pero se complementan cubriendo
casos distintos:

```
        Turno 1        Turno 2        Turno 3        Turno 4        Turno 5
  ────────────────────────────────────────────────────────────────────────────
  [Resuelve URI]  [404: sin dev]  [Usuario dice]  [Dev presente]  [Pedir play]
                                  [dónde]
  ─────────────────────────────────────────────────────────────────────────────
  B (ventana 10): ████████████████████████████████████████████████ turno 1 visible
  A (task state): {uri} ──────────────────────────────────────────── siempre presente
```

**B sola** (ventana más amplia): cubre el caso cuando los datos
resueltos están en texto libre del historial visible. Falla si la
secuencia es más larga que la ventana.

**A sola** (task state): cubre el caso cuando los datos resueltos son
valores específicos que un handler puede identificar explícitamente.
No ayuda con contexto conversacional en general.

**A + B juntos**: la ventana amplia garantiza que el hilo conversacional
sea visible; el task state garantiza que los datos clave nunca se
pierdan independientemente de la longitud de la secuencia. Son capas
de defensa distintas.

**Orden de implementación recomendado**: B primero (cambio de una
línea/config), A después (requiere tocar `ToolExecutionResult` y el
executor). B resuelve el 80% de los casos inmediatamente.

---

## Casos de validación

El mecanismo debe validarse con escenarios genéricos (no específicos
de ningún dominio de tools). Los seis casos cubren el espacio de fallos
documentado:

### Caso 1 — Datos resueltos sobreviven N turnos de seguimiento

1. Turno 1: tool A resuelve un `recurso_id` → lo guarda en task_state.
2. Turnos 2–4: usuario hace seguimiento con mensajes cortos ("sí", "en
   el dispositivo X", "ya está listo") sin que el planner llame a tool A.
3. Turno 5: planner usa el `recurso_id` del task_state sin necesidad de
   relanzar tool A.
4. **Verificar**: `recurso_id` está en el `planner_user_message` del
   turno 5; tool A no se llamó en los turnos 2–5.

### Caso 2 — Task state se limpia cuando la tarea se completa

1. Tool B ejecuta con éxito la tarea y devuelve `task_context={}`.
2. Turno siguiente: el bloque "contexto de tarea activa" no aparece en
   el `planner_user_message`.
3. **Verificar**: log `task_context_cleared` con motivo `explicit_close`.

### Caso 3 — Task state expira por TTL de tiempo

1. Tool C guarda un dato en task_state (`Setting.updated_at = T`).
2. Se simula que ha transcurrido el TTL configurado (en tests:
   manipular `updated_at` directamente, o usar un TTL de test de 0 s).
3. En el turno siguiente, la lectura del task_state detecta expiración
   y no inyecta el bloque en `planner_user_message`.
4. **Verificar**: log `task_context_cleared` con motivo `ttl_expired`.

### Caso 4 — Ventana ampliada (Eje B) cubre una secuencia de 5 turnos

1. 5 turnos de seguimiento consecutivos, todos con mensajes cortos.
2. `planner_history_count` en el log de `history_injected` del turno 5
   muestra ≥ 5 (en vez de 4).
3. El planner tiene en contexto el contenido del turno 1.
4. **Verificar**: no se llama a `search_conversation_history` para
   recuperar datos que ya deberían estar en el historial visible.

### Caso 5 — Task state con múltiples handlers en el mismo turno

1. Un turno ejecuta tool D y tool E en bucle multi-turno (loop_round 0
   y 1). Ambas devuelven `task_context` distintos.
2. El task_state resultante contiene las claves de ambas tools.
3. **Verificar**: merge correcto, sin que la segunda sobreescriba la
   primera si las claves son distintas.

### Caso 6 — Task state no genera valores incorrectos si está obsoleto

1. Tool F guarda `dispositivo_id: X` en el task_state.
2. El usuario cambia de dispositivo explícitamente en un turno
   siguiente. Tool F se llama de nuevo y devuelve `dispositivo_id: Y`.
3. El task_state actualizado contiene solo `Y`.
4. **Verificar**: el turno posterior al cambio inyecta `Y`, no `X`.

---

## Impacto en sistemas existentes

### Bucle multi-turno (`ai_orchestrator.py`)

**Eje B**: ningún impacto. El cambio de `planner_history_limit` solo
afecta a `PromptContextBuilder.build()` antes de que empiece el bucle.
Los `extra_prior_rounds` que acumula el bucle no cambian.

**Eje A**: el task_state se actualiza durante la ejecución del bucle
(el executor llama a los handlers y recibe `task_context` de cada
`ToolExecutionResult`). Pero se inyecta solo al *inicio* del siguiente
turno, no dentro del mismo turno. Dentro del turno, el planner ya tiene
los tool_results en contexto a través de `accumulated_tool_rounds` —
el task_state es para persistencia entre turnos, no intra-turno.

### Sistema de cancelación

Ningún impacto de ninguno de los dos ejes. El task_state es por
sesión; una cancelación de turno no borra el estado (la tarea puede
retomarse).

### Logging universal (observabilidad)

**Eje B**: el campo `planner_history_count` en el evento
`history_injected` ya captura el nuevo valor — sin cambios en el
logging.

**Eje A**: dos eventos nuevos en el sistema de observabilidad:

| `module` | `event` | Cuándo |
|----------|---------|--------|
| `core` | `task_context_updated` | Al guardar claves de task_context (payload: claves, no valores) |
| `core` | `task_context_cleared` | Al limpiar el estado (payload: motivo) |

Ambos con nivel INFO. Los valores no se loguean.

### `ToolExecutionResult` (`app/tools/types.py`)

**Eje A** añade un campo opcional:
```python
task_context: dict[str, str] | None = None
```

Es opt-in y retrocompatible: todos los handlers existentes (que no
pasan `task_context`) siguen funcionando sin cambios. Solo los handlers
que quieran exponer datos al task_state añaden el campo.

### `history_limit_for_message` (`toolset_selector.py`)

La función existente no se toca ni se elimina — solo controla
`history_limit` (ventana del modelo de chat, no del planner). El
cambio de Eje B es exclusivamente sobre `planner_history_limit`, que
hoy es un argumento hardcodeado en `ai_turn_prep.py:94` y pasaría a
leerse desde config.

---

## Qué no cubre este diseño

- **Sesiones muy largas con tarea única sin interrupción**: si la misma
  tarea se extiende más de ~10 turnos de seguimiento, Eje B (ventana=10)
  empieza a perder turnos tempranos. Eje A mitiga esto para los datos
  clave, pero no para el hilo conversacional en general. Para ese caso,
  la alternativa es subir más el límite (20–30) o usar
  `search_conversation_history` explícitamente desde el planner.
- **Datos complejos en task_state**: el diseño solo contempla pares
  `str → str`. Estructuras más complejas (listas, anidamiento) quedan
  fuera del scope inicial.

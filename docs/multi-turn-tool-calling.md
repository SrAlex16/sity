# Bucle multi-turno de tool-calling

Última actualización: 2026-07-10.

Cómo Sity encadena varias tool calls dentro de un mismo turno de
chat — por ejemplo "lista mis playlists y reproduce la que hable de
X" — sin que el usuario tenga que pedirlo en dos mensajes separados.

## El problema que resuelve

Hasta el 2026-07-10, el flujo era de una sola ronda:

```
planner → tool_calls (una o más, ejecutadas en paralelo)
   ↓
run_tool_loop()       — ejecuta esas tool_calls
   ↓
run_after_tools()     — UNA llamada a Claude para cerrar con texto
   ↓
response.text = texto de cierre (tool_calls de esta respuesta se descartaban)
```

Si el planner pedía una tool de **lectura** (ej. `spotify_list_playlists`)
y el resultado por sí solo no bastaba para completar la petición del
usuario (había que decidir cuál reproducir y luego llamar a
`spotify_play`), no había ninguna segunda oportunidad de actuar: Claude
veía el resultado de la lectura, pero la llamada de cierre
(`generate_with_tool_results`) no permitía pedir una tool nueva —  o,
más precisamente, si Claude devolvía un `tool_use` en esa respuesta,
el código lo descartaba sin más (`response.text = response_after_tools.text`,
sin mirar `.tool_calls`). El resultado observado: el modelo "narraba"
la acción como si la hubiera hecho ("Listo, voy con ella") sin haberla
ejecutado — un *ghost action*. Caso real que motivó el fix: pedir a
Sity que reprodujera "mi playlist de openings de anime, no recuerdo el
nombre" — listó las playlists, identificó la correcta, y cerró con
texto sin llamar nunca a `spotify_play`.

## Diseño

El bucle vive **inline en `ai_orchestrator.py`** (no en un módulo
aparte) — es una extensión del mismo bloque que ya orquestaba la
llamada única a `run_after_tools`, no una pieza nueva de arquitectura
separada.

```
tool_results_for_claude (de la ronda 0, el planner)
   │
   ▼
for _round in range(max_after_tools_rounds):    # default 3
   │
   ├─ is_cancelled? → break
   │
   ├─ run_after_tools(..., extra_prior_rounds=accumulated_tool_rounds)
   │     → response_after_tools (texto y/o tool_calls)
   │
   ├─ acumular usage/latencia en response
   │
   ├─ ¿response_after_tools.tool_calls vacío, o cancelado? → break
   │     (caso normal: el modelo decidió que ya terminó)
   │
   ├─ log tool_chain_continued (round, tools pedidas)
   │
   ├─ extender accumulated_tool_rounds con el turno anterior
   │     (assistant: tool_use blocks / user: tool_results)
   │
   ├─ primera tool de esta ronda es "detachable"?
   │     sí → _detach_tool(...) → tool_results_for_claude sintético
   │          → continue (una ronda más, para que el modelo cierre
   │             con un texto tipo "vale, dame un segundo" en vez de
   │             un mensaje fijo hardcodeado — el trabajo real ya
   │             quedó lanzado en background, esta ronda extra es
   │             barata)
   │
   └─ no detachable → run_tool_loop(planner_response=response_after_tools,
                                      loop_round=_round+1)
         → ejecuta la(s) tool(s) de esta ronda
         → local_final / sensor_* → break (mismo comportamiento que
           en la ronda 0: una confirmación pendiente o un evento de
           sensor corta el bucle igual de limpio)
         → normal → tool_results_for_claude = resultado de esta ronda
                     → vuelve al for (siguiente ronda)
```

### Piezas modificadas

- **`ai_orchestrator.py`** — el bucle en sí (reemplaza el bloque que
  antes hacía una sola llamada a `run_after_tools`).
- **`ai_request_builder.py`** — `build_after_tools_ai_request` pasó de
  `tools_enabled=False` a `tools_enabled=True`. Antes había una
  inconsistencia real: el flag decía "sin tools" pero
  `claude_provider.generate_with_tool_results` nunca comprobaba ese
  flag y mandaba las tools al SDK de todas formas. Ahora el flag y el
  comportamiento real coinciden.
- **`claude_provider.py`** — `generate_with_tool_results` acepta
  `extra_prior_rounds` para poder acumular el historial de rondas
  intermedias del propio turno (distinto del historial de turnos
  anteriores de la conversación) sin tener que mutar `prior_messages`
  desde fuera.
- **`ai_gateway.py` / `provider_call_runner.py`** — `extra_prior_rounds`
  propagado hacia arriba/abajo sin lógica propia.
- **`ollama_provider.py` / `providers/base.py`** — firma actualizada
  por compatibilidad, sin cambio de comportamiento real (Ollama no
  participa en el bucle multi-turno hoy).
- **`tool_executor.py` / `tool_loop_step.py` / `tool_loop_runner.py`**
  — `loop_round` añadido y propagado hacia el logging.

### Por qué es genérico (sin nombres de dominio en el código)

El bucle no contiene ningún `if tool_name == "..."` ni ninguna
referencia a Spotify, Google, Home Assistant, etc. Las únicas
decisiones sobre una tool concreta pasan por mecanismos ya genéricos
y preexistentes:

- `get_blocking_policy(tool_name)` — consulta `TOOL_BLOCKING_POLICIES`
  (ver `docs/background-tasks.md`), no un `if` hardcodeado.
- `raw_result.get("local_final")` — cualquier handler puede devolver
  este campo para provocar una salida temprana (ej. una confirmación
  pendiente de calendario); el bucle no sabe qué tool lo generó.
- `is_cancelled(client_turn_id)` — genérico, ver
  `docs/turn-cancellation.md`.

Esto se verificó explícitamente con 6 tests
(`tests/test_multi_turn_tools.py`) que usan tools **ficticias**
(`mock_list`, `mock_act`, etc.), no las reales de Spotify o Calendar —
la prueba de que el mecanismo no depende de qué dominio se esté usando.

## Límites y protección de coste

- **`max_after_tools_rounds`** — configurable en `ai_config`, default
  `3`. Protege contra que el modelo entre en una cadena de tools sin
  fin; al alcanzar el límite, el bucle simplemente sale con el último
  `response.text` disponible (corte con gracia, no un error).
- **`max_tool_loop_iterations`** — el límite ya existente (default
  `3`), sigue aplicando *dentro* de cada ronda, a las tool_calls
  paralelas que trae esa ronda — es un límite distinto y
  complementario, no el mismo mecanismo.
- Cada ronda extra es una llamada completa a Claude (con su propio
  `cache_read`/`cache_creation`). Coste estimado ~0.003 USD/ronda en
  el caso típico; latencia extra ~1-3s por ronda en la Raspberry Pi.
  Con el límite de 3, el peor caso son unos ~9s extra de latencia
  percibida — se decidió no añadir ningún indicador visual nuevo para
  esto: si una ronda tarda demasiado, el mecanismo correcto es que la
  tool en cuestión esté marcada como `detachable` (ver siguiente
  sección), no un indicador de progreso genérico por número de ronda.

## Interacción con cancelación

`is_cancelled(request.client_turn_id)` se comprueba en dos puntos de
cada iteración del bucle: al principio (antes de lanzar la ronda) y
justo después de recibir la respuesta (antes de decidir si continuar).
No hizo falta ningún mecanismo nuevo — el streaming ya cortaba dentro
de cada llamada individual (ver `docs/turn-cancellation.md`), y estos
dos checks adicionales cubren cancelar *entre* rondas.

## Interacción con tareas en background

El criterio para pasar una tool a background **no cambió**: sigue
siendo exclusivamente `get_blocking_policy(tool_name) == "detachable"`
(ver `docs/background-tasks.md`) — no se introdujo ningún criterio
nuevo basado en tiempo acumulado del turno ni en número de rondas.

Lo que sí se extendió: antes, `_detach_tool` solo se comprobaba para
la primera tool_call del planner (ronda 0). Ahora se comprueba en
**cualquier ronda** del bucle — si una tool detachable aparece en la
ronda 2, por ejemplo, el turno se resuelve igual que si hubiera
aparecido en la ronda 0: respuesta sintética inmediata, trabajo real
lanzado en `JobManager`, notificación posterior vía
`proactive_message` cuando termine.

## Logging

- `tool_call_started` / `tool_call_finished` (ver
  `docs/operations/development.md`, sección Observabilidad) incluyen
  ahora `loop_round` en el payload — permite reconstruir en los logs
  la secuencia completa de una cadena multi-tool (ronda 0 → ronda 1 →
  ...) en vez de tener que inferirla del orden de aparición.
- `tool_chain_continued` — evento nuevo, se loguea al inicio de cada
  ronda extra (ronda ≥ 1), con el número de ronda y los nombres de las
  tools pedidas. Señal directa para saber si un turno usó el bucle
  multi-turno o se resolvió en una sola ronda.
- Para diagnosticar un turno concreto:

  ```bash
  cat ~/projects/sity/data/logs/app-$(date -u +%Y-%m-%d).jsonl | \
    grep "tool_call_started\|tool_call_finished\|tool_chain_continued" | tail -30
  ```

## Casos de validación (`tests/test_multi_turn_tools.py`)

Seis tests, todos con tools ficticias:

- **A** — cadena de 2 tools (lectura → acción): confirma que el bucle
  encadena correctamente cuando hace falta.
- **B** — una sola ronda, sin necesidad de encadenar: confirma que no
  hay regresión en el caso simple ya existente.
- **C** — `local_final` en una ronda intermedia (ej. una confirmación
  pendiente): confirma que sigue cortando el bucle limpiamente, igual
  que en la ronda 0.
- **D** — cancelación a mitad del bucle: confirma que `is_cancelled`
  corta correctamente en cualquier ronda.
- **E** — cadena de más tools que `max_after_tools_rounds`: confirma
  que el límite corta con gracia, sin error.
- **F** — una tool detachable aparece en una ronda intermedia: confirma
  el detach extendido a todas las rondas.

## Limitaciones conocidas (no arquitectónicas)

El bucle en sí es genérico y no tiene ninguna limitación de dominio,
pero su eficacia depende de que el **modelo** decida bien qué tools
pedir y cuándo. Casos observados en producción:

- **Reconocimiento cultural en nombres (resuelto parcialmente,
  2026-07-10)** — al pedir "pon mi playlist de openings de anime",
  el modelo encontró 5 candidatas por nombre/descripción (Ado,
  TRAPNEST//NANA, Black Stones - NANA, Nier Replicant/Automata,
  Carole & Tuesday) pero excluyó "Otako culiao 🤑": el nombre no
  tiene relación textual obvia con "anime" y la playlist no tiene
  descripción. Confirmado por logs que el modelo no llamó a
  `spotify_playlist_tracks` sobre ninguna candidata — la decisión
  fue puramente por nombre. La causa raíz de la sesión anterior
  (el modelo decía "no tengo acceso a las canciones") era un 403
  por scope OAuth ausente (`playlist-read-private`), no falta de
  esfuerzo: el scope estaba declarado en `spotify_auth.py` pero el
  token en disco era anterior a su adición. Resuelto tras reauth
  (`python scripts/spotify_auth_setup.py`). Limitación residual con
  "Otako culiao": decisión aceptada — añadir una descripción a la
  playlist en Spotify lo resuelve sin tocar código. No se introduce
  ninguna heurística hardcodeada.

- **Confusión ID vs URI en `spotify_play` (corregido, commit
  `ed73db5`, 2026-07-10)** — `spotify_list_playlists` exponía
  tanto el campo `ID: <id_corto>` como `URI: spotify:playlist:<id>`.
  El modelo usaba el ID corto como `query`, lo que disparaba
  `_search_uri` y reproducía contenido incorrecto (caso real:
  D.Valentino en vez de la playlist pedida). Fix: el campo `ID:`
  se eliminó del output de texto; solo queda la URI completa.

- **Ambigüedad de lenguaje en sesiones largas** — en una conversación
  con mucho historial de dominios distintos acumulado (ej. Home
  Assistant y Spotify mezclados a lo largo del día), una palabra
  ambigua como "dispositivos" puede resolverse hacia el dominio menos
  esperado por el usuario. Confirmado en logs que no es un fallo del
  bucle (se resolvió en una sola ronda, con las tools correctas para
  la interpretación que hizo el modelo) sino de selección semántica
  del planner dado el contexto disponible. Pendiente de observar si
  se repite en sesiones más limpias antes de considerar cualquier
  ajuste (que iría en tool description, nunca en una regla hardcodeada
  tipo "dispositivos = Spotify").

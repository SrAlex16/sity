# Análisis de arquitectura: multi-turn tool calling

Fecha: 2026-07-10

---

## 1. Diseño del bucle

### Estado actual

El flujo hoy es estrictamente de una sola ronda:

```
planner → tool_calls
  ↓
run_tool_loop()         # tool_loop_runner.py — ejecuta todas las tool_calls del planner
  ↓
run_after_tools()       # provider_call_runner.py:91 — una llamada a generate_with_tool_results()
  ↓
response.text = response_after_tools.text     # ai_orchestrator.py:669
# response_after_tools.tool_calls  →  DESCARTADO (nunca se comprueba)
```

La línea crítica es `ai_orchestrator.py:669`. Lo que venga en `response_after_tools.tool_calls` nunca llega a ejecutarse.

**Paradoja existente**: `build_after_tools_ai_request` fija `tools_enabled=False` (`ai_request_builder.py:261`), pero `claude_provider.generate_with_tool_results()` pasa las tools igualmente, ignorando ese flag (`claude_provider.py:168`). Por tanto el modelo ya recibe las tools en la ronda after-tools y ya puede devolver `tool_calls`; simplemente se descartan.

### Diseño propuesto

Convertir la sección lineal en un bucle dentro de `ai_orchestrator.py`. El cambio se concentra en el bloque que empieza en la línea 645:

```
planner_response → run_tool_loop() → tool_results_for_claude
  ↓
BUCLE (max_after_tools_rounds = 3):
  ┌─ run_after_tools(acumulated_messages + tool_results_for_claude)
  │    ↓
  │  ¿response_after_tools.tool_calls vacío?
  │   sí → response.text = response_after_tools.text ; salir bucle
  │   no  → run_tool_loop(response_after_tools)
  │           ↓ early_kind != None? → tratar igual que hoy (local_final / sensor)
  │           ↓ normal path:
  │             acumulated_messages += [assistant_turn, tool_results_turn]
  │             tool_results_for_claude = new_tool_results
  └─ (siguiente iteración)
```

### Acumulación de mensajes entre rondas

`generate_with_tool_results` construye el historial con `prior_messages` + el turno actual (planner + tool_results):

```python
# claude_provider.py:154-159
_msgs = [
    *_messages_with_history_cache(request.prior_messages, request.user_message),
    {"role": "user",      "content": _user_content_block(request)},
    {"role": "assistant", "content": first_response_content},   # tool_use blocks
    {"role": "user",      "content": tool_results},
]
```

Para que la ronda N+1 vea la ronda N completa, hay que añadir los dos turnos de la ronda N al final de `prior_messages` antes de la siguiente llamada:

```python
# Pseudo-código del bucle en ai_orchestrator.py
accumulated_messages = list(prior_messages)   # history antes del turno actual

for round_idx in range(max_after_tools_rounds):
    after_tools_response = runner.run_after_tools(
        request=build_after_tools_ai_request(
            ...
            prior_messages=accumulated_messages,
        ),
        first_response_content=_tool_use_blocks(current_source_response),
        tool_results=tool_results_for_claude,
    )

    # acumular tokens / latencia (ya se hace hoy)

    if not after_tools_response.tool_calls or is_cancelled(...):
        response.text = after_tools_response.text
        break

    # Añadir esta ronda al historial acumulado
    accumulated_messages = accumulated_messages + [
        {"role": "assistant", "content": _tool_use_blocks(current_source_response)},
        {"role": "user",      "content": tool_results_for_claude},
    ]

    # Ejecutar las tool_calls pedidas por after_tools_response
    loop_outcome = run_tool_loop(
        planner_response=after_tools_response, executor=executor, ...
    )
    if loop_outcome.early_kind is not None:
        # local_final / sensor → igual que en la primera ronda
        ...
        break

    tool_results_for_claude = loop_outcome.tool_results_for_claude
    current_source_response = after_tools_response   # para la próxima iteración
```

`_tool_use_blocks()` es la función local que ya existe implícitamente en `ai_orchestrator.py:657-665`:

```python
def _tool_use_blocks(response: AIResponse) -> list[dict]:
    return [
        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
        for tc in response.tool_calls
    ]
```

No requiere añadir ningún campo nuevo a `AIResponse` — `tool_calls` ya tiene todo lo necesario.

### La inconsistencia `tools_enabled`

Con el bucle activo, la intención se vuelve explícita: after-tools SÍ debe poder devolver tool_calls. El parche limpio es:

1. En `build_after_tools_ai_request`: cambiar `tools_enabled=False` a `tools_enabled=True`.
2. En `claude_provider.generate_with_tool_results()`: respetar `tools_enabled` como hace `generate()` (línea 108), en lugar de pasar tools siempre (línea 168).

Esto hace que el comportamiento sea intencional y consistente. Hoy la inconsistencia es inofensiva porque los tool_calls se descartan igualmente; tras el bucle sería un bug si se dejara sin corregir.

---

## 2. Límites de iteración, coste y latencia

### Qué limita qué hoy

`max_tool_loop_iterations` (ai_orchestrator.py, `ctx.ai_config.get("max_tool_loop_iterations", 3)`) limita cuántas tool_calls del planificador se ejecutan **en paralelo dentro de una sola ronda**. Es decir, si el planner devuelve 5 tool_calls, solo se procesan las 3 primeras. No tiene nada que ver con la dimensión multi-turn.

El nuevo parámetro controla cuántas rondas completas (after-tools → más tool_calls) pueden encadenarse.

### Recomendación de límite

**`max_after_tools_rounds = 3`** (por encima del planificador inicial, es decir, hasta 4 pares planner+after-tools en total).

Justificación:
- El caso más real (playlist → play) necesita exactamente 1 ronda extra.
- Encadenar 3 servicios distintos (e.g. calendar → drive → email) necesita 2.
- 3 es suficiente para cualquier flujo razonable y deja margen de seguridad.
- Más de 3 probablemente indica que el modelo está confuso o en bucle; es mejor cortar y devolver lo que se tiene.

### Coste por ronda adicional

Estimación aproximada para Claude claude-sonnet-4-6:
- Input: ~1 500 tokens de historial acumulado + ~400 tokens de tool_results = ~2 000 tokens
- Output: ~400 tokens (una tool_call) 
- Coste marginal por ronda: ~0.003 USD (muy bajo para uso personal)

El coste en CPU de la Pi es más relevante que el económico: cada llamada es ~1-3 segundos. Con 3 rondas extra el peor caso añade ~9 s al turno. Aceptable si la acción realmente ocurre; inaceptable si ocurre siempre. El límite de 3 protege contra bucles, no contra uso normal.

### Contador de tokens

Cada `run_after_tools` ya acumula uso (`ai_orchestrator.py:670-672`). El bucle debe seguir acumulando en el mismo `response.usage` para que el log final y el presupuesto diario reflejen el turno completo.

---

## 3. Interacción con la cancelación

### Puntos de cancelación existentes

- `tool_loop_runner.py:78`: `if is_cancelled(client_turn_id): break` — antes de cada step de tools.
- `claude_provider.py:118`: dentro del streaming de `generate()` — cancela mid-chunk.
- `claude_provider.py:~175`: dentro del streaming de `generate_with_tool_results()` — ídem.
- `ai_orchestrator.py:645`: `if tool_results_for_claude and not is_cancelled(...)` — guarda antes de la ronda after-tools.

### Puntos nuevos necesarios

El bucle multi-turn añade dos oportunidades naturales donde hay que insertar la comprobación:

```python
for round_idx in range(max_after_tools_rounds):
    if is_cancelled(client_turn_id):    # ← NUEVO: antes de run_after_tools
        break

    after_tools_response = runner.run_after_tools(...)
    # (la cancelación mid-stream ya la maneja claude_provider internamente)

    if not after_tools_response.tool_calls or is_cancelled(client_turn_id):  # ← ya hay uno aquí
        response.text = after_tools_response.text
        break

    # run_tool_loop ya tiene is_cancelled en su bucle interno
    loop_outcome = run_tool_loop(...)
```

No hace falta nada más. Las capas internas ya se defienden solas; solo hay que asegurarse de que el bucle externo también salga limpiamente.

### Semántica al cancelar

Si la cancelación ocurre **entre rondas** (e.g., primera tool ejecutada, antes de after-tools):
- Las tools ya ejecutadas **sí se ejecutaron** (no son transaccionales).
- `response.text` quedará vacío o con el texto parcial anterior.
- El orchestrator ya gestiona la respuesta de cancelación en el nivel superior; el bucle solo necesita salir.

Si la cancelación ocurre **dentro de una ronda after-tools** (mid-stream):
- `generate_with_tool_results` devuelve `AIResponse(ok=False, error_type="cancelled", text="")`.
- El bucle detecta `is_cancelled` → sale → igual que hoy.

---

## 4. Interacción con background tasks y early exits

### Detach — extender a todas las rondas del bucle

**Criterio de detach**: no cambia. Sigue siendo exclusivamente `get_blocking_policy(tool_name) == "detachable"` consultando `TOOL_BLOCKING_POLICIES` (`tool_loop_runner.py:59-61`). No se introduce ninguna heurística nueva basada en tiempo acumulado del turno ni en número de rondas.

**Lo que cambia**: hoy el chequeo de detach solo ocurre para `planner_response.tool_calls[0]` en `ai_orchestrator.py:524-527`. Con el bucle multi-turn, una tool detachable (e.g. `web_search`) puede aparecer en la ronda 1, 2 o 3 del bucle after-tools, no solo en la ronda 0. Hay que mover o generalizar ese chequeo para que se aplique en **cada iteración del bucle**.

**Dónde exactamente**: el chequeo debe hacerse en el punto del bucle donde se procesan las `tool_calls` de `after_tools_response`, antes de llamar a `run_tool_loop()` en la siguiente iteración. Es el mismo sitio donde hoy `ai_orchestrator.py:524-527` llama a `_detach_tool` para la primera ronda — pero generalizado a cualquier ronda:

```python
# Dentro del bucle after-tools, tras comprobar que hay tool_calls:
first_tc = after_tools_response.tool_calls[0]
if get_blocking_policy(first_tc.name) == "detachable":
    # Mismo comportamiento que hoy para la ronda 0:
    # responder con mensaje sintético "en progreso", lanzar en background,
    # cerrar el turno sin continuar el bucle.
    _detach_tool(first_tc, ...)
    break
```

**Semántica**: si una ronda intermedia decide usar una tool detachable, el turno se cierra ahí — las rondas anteriores ya ejecutaron sus tools (efectos reales), y la detachable notificará su resultado vía `proactive_message` cuando termine en background. El usuario no espera en el chat; la respuesta sintética de "en progreso" se envía de inmediato.

**Qué NO cambia**: el comportamiento de la ronda 0 (planner inicial) es idéntico a hoy. Las funciones `_detach_tool` y `get_blocking_policy` no necesitan modificarse.

### `local_final` (confirmaciones de acción pendiente)

Cuando un handler devuelve `raw_result["local_final"] = True` (e.g., `calendar_create_event`, `ha_call_service` con confirmación), `run_tool_loop_step` retorna `early_kind="local_final"` → `run_tool_loop` retorna con `early_kind="local_final"` → el orchestrator usa `local_text` directamente y no llama a after-tools.

En el bucle multi-turn, si una ronda intermedia de `run_tool_loop` devuelve `early_kind="local_final"`:
- Usar `loop_outcome.local_text` como `response.text`.
- Salir del bucle.

Este caso es realista: el modelo podría encadenar "lista playlists → pon música → crea un recordatorio" donde el tercer paso genera una confirmación. La semántica es correcta: el `local_text` describe exactamente la acción pendiente.

### Sensores (`sensor_cancelled`, `sensor_finished`)

Los sensores (`record_audio_sample`, `capture_camera_snapshot`) solo aparecerán en el planificador inicial, no en after-tools. El bucle no necesita manejarlos en rondas intermedias. Si apareciesen (improbable), propagarlos igual que hoy.

---

## 5. Logging y trazabilidad

### Estado actual

Cada tool call ya tiene `tool_call_started` / `tool_call_finished` con `trace_id`, `tool_name` y `tool_input` redactado. El `trace_id` es único por turno de usuario; no distingue rondas dentro del turno.

### Propuesta mínima

Añadir `loop_round` (entero, 0-indexed) al payload de `tool_call_started` y `tool_call_finished`. La ronda 0 es la del planificador inicial; las rondas 1, 2, 3 son las del bucle multi-turn.

```python
# En execute_tool_call, el caller pasa loop_round=round_idx
payload = {
    "tool_name": tool_name,
    "loop_round": loop_round,     # ← nuevo campo, 0 si no se pasa
    "tool_input": _redact_sensitive(tool_input),
    ...
}
```

Alternativamente, el `trace_id` puede incorporar el round con un sufijo (`trc_abc_r1`) para que los greps sean triviales sin tocar la estructura del payload. Ambas opciones son válidas.

### Evento adicional útil

Un evento `tool_chain_continued` al comienzo de cada iteración del bucle (excepto la primera):

```python
write_log(
    level="INFO", module="tools", event="tool_chain_continued",
    trace_id=ctx.trace_id,
    payload={"round": round_idx, "tool_calls_requested": [tc.name for tc in after_tools_response.tool_calls]},
)
```

Esto permite ver en los logs exactamente cuándo el modelo decidió encadenar otra tool, y cuál eligió, sin tener que deducirlo de la secuencia de `tool_call_started`.

### Token usage por ronda

El `response.usage` acumulado refleja el turno completo (ya funciona hoy). Para depuración, incluir usage per-round en `tool_chain_continued` es suficiente:

```python
payload = {
    "round": round_idx,
    "cumulative_input_tokens": response.usage.input_tokens,
    ...
}
```

---

## 6. Validación mental de casos de uso

### Caso A: "pon la playlist de openings" (el bug actual)

- **Ronda 0 planificador**: `spotify_list_playlists` → devuelve lista de playlists con URIs.
- **Ronda 0 after-tools**: el modelo ve la lista, identifica "Otako culiao", quiere ejecutar `spotify_play(uri=...)`. Hoy: devuelve texto + tool_call descartado. Con el bucle: tool_call honrada.
- **Ronda 1 planificador** (= after-tools tool_calls): `spotify_play(uri=spotify:playlist:...)` → PUT /me/player/play → 204 OK.
- **Ronda 1 after-tools**: no hay más tool_calls → `response.text = "Voy con ella, pon Otako culiao."`.
- **Total rondas extra**: 1. Latencia extra: ~1-3 s. El bug queda resuelto.

### Caso B: "¿tienes emails de trabajo?" (flujo actual — no debe romperse)

- **Ronda 0 planificador**: `gmail_search` → resultados.
- **Ronda 0 after-tools**: el modelo responde en texto → `tool_calls = []` → bucle no itera.
- **Total rondas extra**: 0. Sin cambio.

### Caso C: "crea un evento mañana a las 10" (confirmación)

- **Ronda 0 planificador**: `calendar_create_event` → `local_final=True` → early exit.
- El orchestrator usa `local_text` directamente. El bucle multi-turn ni se inicia porque la salida es `early_kind="local_final"` antes de llegar al punto de entrada del bucle.
- **Total rondas extra**: 0. Sin cambio.

### Caso D: "¿qué tengo mañana? y luego pon algo relajante"

- **Ronda 0 planificador**: el planner elige UNA tool — aquí hay ambigüedad. El sistema prompt del planner dice "elige exactamente una herramienta". El planner elegiría `calendar_list_events`.
- **Ronda 0 after-tools**: el modelo ve los eventos, responde sobre ellos, y quiere también llamar a `spotify_play`. Con el bucle: lo puede hacer.
- **Ronda 1 planificador**: `spotify_play("música relajante")` → búsqueda + PUT.
- **Ronda 1 after-tools**: respuesta final combinando ambos resultados.
- **Total rondas extra**: 1. Este caso antes requería dos mensajes del usuario.

### Caso E: cadena de 4+ tools (límite del bucle)

Si el modelo intentara encadenar 5 tools en secuencia (improbable pero posible):
- Rondas 0-3 se ejecutan normalmente.
- Al llegar al límite `max_after_tools_rounds=3`, el bucle sale aunque `after_tools_response.tool_calls` no esté vacío.
- `response.text` contendría el texto de la última ronda after-tools completada.
- El modelo habría ejecutado 4 tools reales y habría generado texto describiendo lo que hizo hasta ese punto.
- Comportamiento aceptable. Un log `tool_chain_limit_reached` sería útil para detectarlo.

### Caso F: bucle infinito (el modelo siempre devuelve tool_calls)

Escenario patológico donde el modelo siempre devuelve una nueva tool_call sin producir texto. El límite `max_after_tools_rounds=3` lo corta en 3 iteraciones. Sin ese límite sería un problema real (infinito de llamadas a Claude). Con el límite es benigno.

---

## Resumen de decisiones a tomar

| Decisión | Opción A | Opción B | Recomendación |
|---|---|---|---|
| Dónde va el bucle | `ai_orchestrator.py` inline | nuevo módulo `multi_turn_runner.py` | **inline** — menos abstracción, la complejidad no lo justifica aún |
| Límite de rondas | hardcoded 3 | configurable en `ai_config` | **configurable** — consistente con `max_tool_loop_iterations` |
| Acumulación de mensajes | ampliar `prior_messages` | nuevo parámetro en `generate_with_tool_results` | **ampliar prior_messages** — no toca claude_provider.py |
| `tools_enabled` en after-tools | corregir a `True` + respetar en provider | dejar la inconsistencia | **corregir** — intención explícita es más segura |
| `loop_round` en logs | campo en payload | sufijo en trace_id | **campo en payload** — más fácil de filtrar con jq |
| Detach en rondas intermedias | mantener solo primera ronda | extender a todas las rondas | **extender a todas las rondas** — mismo criterio (`get_blocking_policy`), sin heurística nueva de tiempo/rondas |

---

## Archivos que cambian

| Archivo | Tipo de cambio |
|---|---|
| `backend/app/chat/ai_orchestrator.py` | Reemplazar bloque 645-674 por bucle |
| `backend/app/chat/ai_request_builder.py` | `tools_enabled=True` en `build_after_tools_ai_request` |
| `backend/app/cortex/claude_provider.py` | Respetar `tools_enabled` en `generate_with_tool_results` (línea 168) |
| `backend/app/core/tool_executor.py` | Añadir parámetro `loop_round` a `execute_tool_call` (opcional, o como payload extra) |
| `backend/app/chat/tool_loop_runner.py` | Pasar `loop_round` hacia abajo si se añade |
| `tests/test_multi_turn_tools.py` | Tests nuevos (casos A, B, C, E) |

`tool_loop_step.py`, `tool_loop_runner.py` y `provider_call_runner.py` no necesitan cambios estructurales — el bucle los invoca igual que hoy.

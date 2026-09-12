# Fase 7 — Memoria Procedimental

**Estado:** Pasos 1–2 completos (2026-09-12)  
**Tests nuevos:** 53 (31 test_procedural_service.py + 22 test_decision_procedural.py)  
**Commits:** `ba293f0` (Paso 1) · `PENDING` (Paso 2)

---

## Objetivos

Dotar a Sity de **memoria procedimental**: capacidad de reconocer patrones de
comportamiento que se repiten por tipo de conversación (`context_type`) y usarlos
para ajustar proactivamente las puntuaciones de acción en Decision sin esperar
confirmación explícita del usuario.

La memoria procedimental es diferente de la episódica (hechos) y la autobiográfica
(identidad): captura *cómo* interactúa el usuario de forma habitual, no *qué* ocurrió.

---

## Paso 1 — Capa de datos + detección de patrones

### Nuevas tablas en `app/memory/models.py`

#### `ProceduralObservation` — registro ligero por turno

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `user_id` | int (index) | Aislamiento por usuario |
| `context_type` | str (index) | Tipo de conversación clasificado por Perception |
| `user_message_excerpt` | str | Primeros 100 chars del mensaje del usuario |
| `trace_id` | str | Trazabilidad con el turno de origen |
| `processed` | bool | `False` hasta que el daemon de síntesis lo procese |
| `created_at` | datetime | — |

#### `ProceduralPattern` — patrón sintetizado por Haiku

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `user_id` | int (index) | Aislamiento por usuario — NUNCA comparte entre usuarios |
| `context_type` | str | Tipo de conversación asociado |
| `strategy_description` | str | Estrategia concisa (≤ 120 chars) generada por Haiku |
| `confidence` | float [0.45, 0.85] | Ver fórmula abajo |
| `evidence_trail_json` | str `[]` | trace_ids de los turros que contribuyeron |
| `occurrence_count` | int | Número total de observaciones procesadas |
| `last_observed_at` | datetime | Última actualización |
| `created_at` | datetime | — |
| `is_active` | bool | `True` — sólo patrones activos influyen en Decision |

### Fórmula de confianza

```
confidence = min(0.85, 0.45 + max(0, occurrence_count - 3) × 0.04)
```

| `occurrence_count` | `confidence` | Efecto en Decision |
|-------------------|--------------|--------------------|
| 3 | 0.45 | Creado, **por debajo** del umbral Decision (0.55) |
| 6 | 0.57 | Supera umbral — comienza a influir |
| 9 | 0.69 | Influencia media (configuración habitual) |
| 12 | 0.81 | Influencia alta |
| ≥ 13 | 0.85 | Techo — el conocimiento procedimental nunca es certero |

El patrón se crea con `occurrence_count = len(obs_rows)` (3 en la primera síntesis)
y arranca en 0.45, intencionalmente **por debajo** del umbral de influencia en Decision.
Esto previene que patrones recién creados con poca evidencia alteren el comportamiento.

### Extensión de Perception: `context_type`

Añadido a `PerceptionResult` con clasificación por Haiku #1 (sin coste marginal —
se añadió al prompt existente con `max_tokens` 80 → 110):

| Valor | Cuándo |
|-------|--------|
| `technical_design` | Arquitectura de software, diseño de sistemas |
| `debugging` | Bugs, errores, diagnóstico |
| `implementation` | Código concreto, "hazlo" |
| `explanation` | "Explícame", conceptos, teoría |
| `casual_chat` | Conversación social, preguntas personales |
| `creative` | Escritura creativa, brainstorming, arte |
| `planning` | Planificación, sprints, hoja de ruta |
| `feedback` | Revisión de código/texto, crítica constructiva |

Fallback a `"casual_chat"` si Haiku devuelve un valor no reconocido o falla.

### `procedural_service.py`

| Función | Descripción |
|---------|-------------|
| `record_observation(session, *, user_id, context_type, user_message, trace_id)` | Inserta `ProceduralObservation`; devuelve recuento de no procesadas |
| `maybe_trigger_pattern_synthesis(session, *, ...)` | Llama a `record_observation`; lanza daemon si `unprocessed ≥ 3` |
| `_run_pattern_synthesis(user_id, context_type, trace_id)` | Daemon: abre su propia Session; Haiku sintetiza/refina estrategia; marca observaciones como procesadas |
| `load_active_patterns(session, *, user_id, context_type, min_confidence)` | Para Decision: devuelve patrones `is_active=True` con `confidence ≥ 0.55` |

**Invariante de aislamiento**: TODAS las consultas a `ProceduralObservation` y
`ProceduralPattern` incluyen filtro `user_id`. El patrón de un usuario A NUNCA
puede influir en el turno del usuario B.

**Patrón daemon**: Mismo patrón que `AutobiographicalNarrative` — `threading.Thread(
target=_run_pattern_synthesis, daemon=True).start()`. El hilo abre su propia Session
sobre `engine` y nunca comparte el Session del turno padre.

### Step 15 en `turn_cognition.py`

```python
try:
    maybe_trigger_pattern_synthesis(
        session, user_id=user_id, context_type=perception.context_type,
        user_message=user_message, trace_id=trace_id,
    )
except Exception as proc_exc:
    write_log(level="WARN", module="cognition", event="procedural_observation_error", ...)
```

No-blocking: cualquier fallo se loguea y se descarta. Nunca afecta el resultado
del turno.

### Tests (31): `tests/test_procedural_service.py`

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestRecordObservation` | 4 | Inserción, recuento, limpieza de sesión, user_id isolado |
| `TestThresholdTrigger` | 3 | Umbral 3 lanza daemon; 2 no lo lanza; multiple tipos |
| `TestPatternCreationAndUpdate` | 6 | CREATE vs UPDATE, occurrence_count acumulado, evidence_trail |
| `TestConfidenceFormula` | 6 | Valores exactos de la fórmula para cada occurrence_count |
| `TestUserIsolation` | 3 | Usuario B no ve patrones de A; observaciones aisladas |
| `TestLoadActivePatterns` | 5 | is_active=False excluido, confidence<0.55 excluido, múltiples resultados |
| `TestPerceptionContextType` | 4 | context_type en PerceptionResult, fallback, as_dict() |

---

## Paso 2 — Integración con Decision

### `_PROCEDURAL_ACTION_HINTS` en `decision.py`

Tabla de ajustes de puntuación por `context_type`. Se aplica como **tercer pase
independiente** después de `_VALUES_MATRIX`:

| `context_type` | Acción | Delta | Razonamiento |
|----------------|--------|-------|--------------|
| `technical_design` | `ask` | +0.06 | Clarificar arquitectura antes de proponer |
| | `answer` | +0.04 | Respuesta arquitectónica directa también válida |
| `debugging` | `ask` | +0.08 | Entender contexto del bug primero |
| | `help` | +0.06 | Asistencia activa cuando el contexto está claro |
| `implementation` | `help` | +0.10 | Modo "hazlo" — asistencia directa gana |
| | `ask` | -0.04 | Menos aclaraciones cuando la acción es explícita |
| `explanation` | `answer` | +0.08 | Respuesta conceptual directa |
| | `initiate` | +0.04 | Añadir contexto relacionado proactivamente |
| `casual_chat` | `answer` | +0.04 | Respuesta conversacional natural |
| | `wait` | -0.06 | Nunca pausar en conversación social |
| `creative` | `initiate` | +0.08 | Contribución proactiva al trabajo creativo |
| | `ask` | +0.04 | Entender dirección antes de crear |
| `planning` | `ask` | +0.08 | Clarificar alcance — crítico en planificación |
| | `answer` | +0.04 | Plan directo si el alcance está claro |
| `feedback` | `challenge` | +0.06 | El feedback invita a la réplica |
| | `answer` | +0.04 | Evaluación directa también válida |

### Guard explícito en `compute_utility_scores()`

```python
_PROCEDURAL_CONFIDENCE_MIN: float = 0.55  # constante local en decision.py

if procedural_patterns:
    for pattern in procedural_patterns:
        if pattern.confidence < _PROCEDURAL_CONFIDENCE_MIN:
            continue  # zero delta — no se aplica ningún ajuste
        hints = _PROCEDURAL_ACTION_HINTS.get(pattern.context_type, {})
        for action, delta in hints.items():
            scores[action] = scores.get(action, 0.0) + delta * pattern.confidence
```

**Defensa en profundidad**: `_PROCEDURAL_CONFIDENCE_MIN` existe tanto en
`procedural_service.py` (`PROCEDURAL_CONFIDENCE_MIN = 0.55`) como en
`decision.py` (`_PROCEDURAL_CONFIDENCE_MIN = 0.55`). Los dos módulos no se
importan mutuamente para esta constante — el mismo patrón de desacoplamiento
usado entre `_REFLECTION_SALIENCE_MIN` y `episode_service._THR_MEDIA`.

Aunque `load_active_patterns()` ya filtra por `confidence ≥ 0.55`, el guard
en `compute_utility_scores()` protege contra llamadas directas a la función
en tests o futuros call sites que omitan el filtrado en origen.

### `pattern_hint` en Haiku #3 (Decision)

```python
pattern_hint = ""
if procedural_patterns:
    for _p in procedural_patterns:
        if _p.confidence >= _PROCEDURAL_CONFIDENCE_MIN and _p.strategy_description:
            pattern_hint = _p.strategy_description[:120]
            break  # sólo el primer patrón calificado

context = _build_decision_context(user_message, python_scores, signals_summary, pattern_hint)
```

Cuando `pattern_hint` es no vacío, `_build_decision_context()` añade al contexto:

```
LEARNED PATTERN (context_type): <strategy_description>
```

Esto da a Haiku información cualitativa (estrategia aprendida) además de los
scores numéricos — permite sobrerides informados cuando la situación lo justifica.

### Integración en `turn_cognition.py`

```python
try:
    _proc_patterns = load_active_patterns(
        session, user_id=user_id, context_type=perception.context_type
    )
except Exception:
    _proc_patterns = []
decision_result = run_decision(
    ...,
    procedural_patterns=_proc_patterns or None,
)
```

El `or None` convierte lista vacía en `None` para que el guard `if procedural_patterns:`
falle limpiamente sin iterar.

### Tests (22): `tests/test_decision_procedural.py`

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestProceduralBackwardCompat` | 2 | `None` / `[]` → scores idénticos a Fase 6 |
| `TestConfidenceGuard` | 3 | 0.54 → zero delta; 0.549 → zero delta; 0.55 → delta aplicado |
| `TestExactDeltas` | 8 | Deltas exactos `hint_weight × confidence` para cada context_type |
| `TestIsolation` | 2 | Sin contaminación cruzada entre context_types; context_type desconocido → zero |
| `TestMultiplePatterns` | 1 | Dos patrones → deltas sumados independientemente |
| `TestLoadActivePatterns` | 2 | `is_active=False` excluido; `confidence=0.45` excluido (DB) |
| `TestRunDecisionIntegration` | 2 | `run_decision` acepta `procedural_patterns=`; `None` → comportamiento idéntico |
| `TestScenarios` | 2 | `implementation` → `help` mayor; `explanation` → `answer` mayor |

---

## Invariantes de diseño

1. **Aislamiento por usuario**: todo query filtra por `user_id`. Imposible que un
   patrón de usuario A afecte el turno de usuario B.

2. **No-blocking**: `maybe_trigger_pattern_synthesis` (Step 15) y el daemon hilo
   nunca bloquean el turno. Fallos se loguean y se descartan.

3. **Backward compatibility**: `compute_utility_scores()` y `run_decision()` son
   100% compatibles con Fase 6 cuando `procedural_patterns=None` (default) o `[]`.
   Ningún test anterior requirió modificación.

4. **Defensa en profundidad en el umbral**: El guard `confidence ≥ 0.55` existe en
   dos sitios independientes — `load_active_patterns()` (filtrado en DB) y el bucle
   interno de `compute_utility_scores()`.

5. **Patrón recién creado no influye**: Confidence inicial = 0.45 (3 ocurrencias)
   está por debajo del umbral 0.55. Se necesitan ≥ 6 ocurrencias para que el patrón
   influya en Decision.

6. **Haiku de síntesis nunca bloquea el turno**: El daemon usa su propia Session y
   engine. No comparte estado con el Session del turno padre.

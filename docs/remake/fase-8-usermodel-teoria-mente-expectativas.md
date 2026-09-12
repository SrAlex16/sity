# Fase 8 — User Model, Teoría de la Mente y Expectativas

**Estado:** Pasos 1–4 completos (2026-09-12)  
**Tests nuevos:** 53 (22 test_user_model_service.py + 11 test_reflection_belief_attribution.py + 20 test_decision_expectations.py)  
**Commits:** `fbbf161` (Paso 1) · `86b05a6` (Paso 2) · `PENDING` (Pasos 3-4)

---

## Objetivos

Dotar a Sity de tres capacidades interconectadas que forman la base del entendimiento
del usuario:

1. **User Model** — qué sabe Sity sobre el usuario: dominios de conocimiento con nivel
   y confidence estimados.
2. **Teoría de la Mente** — qué cree Sity que el usuario cree: creencias atribuidas al
   usuario con confidence conservadora, extraídas del Reflection Step.
3. **Expectativas** — qué comportamientos predice Sity para el usuario según el
   `context_type`: predicciones forward-looking que ajustan proactivamente la política
   de acción en Decision.

---

## Análisis de reutilización vs. genuinamente nuevo

### REUTILIZADO — no se creó nada nuevo para esto

| Concepto | Qué cubre ya | Por qué no crear tabla |
|---|---|---|
| Preferencias del usuario | `ProceduralPattern` (Fase 7) | Captura exactamente cómo interactúa el usuario en cada context_type |
| `context_type` taxonomy | Enum de 8 valores de Fase 7 | `Expectation` y `BeliefAttribution` la reutilizan directamente |
| `current_state_estimate` | `BeliefAttribution` | Proposiciones sobre el estado actual del usuario son un caso especial de ToM |
| Evidence trail pattern | Todas las tablas existentes | Mismo patrón `[]` de trace_ids |
| Daemon thread pattern | Mismo que `ProceduralPattern` | Para síntesis background si se añade en el futuro |

### GENUINAMENTE NUEVO

1. **`UserKnowledge`** — ningún sistema existente modela qué sabe el usuario de un dominio.
2. **`BeliefAttribution`** — tabla separada de `SelfBelief` (ver decisión abajo).
3. **`Expectation`** — predicción forward-looking con probability. No existía nada parecido.

---

## Paso 1 — Capa de datos + `user_model_service.py`

### Nuevas tablas en `app/memory/models.py`

#### `UserKnowledge`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `user_id` | int (index) | Aislamiento por usuario |
| `topic` | str | "python", "machine_learning", "música clásica", etc. |
| `level` | float [0, 1] | 0=novato, 1=experto |
| `confidence` | float [0, 0.80] | Cap 0.80 — observación indirecta nunca es precisa |
| `evidence_trail_json` | str `[]` | trace_ids que respaldan la estimación |
| `occurrence_count` | int | Veces que se observó evidencia |
| `last_observed_at` | datetime | — |
| `created_at` | datetime | — |
| `is_active` | bool | — |

**Confidence cap 0.80**: el nivel de conocimiento del usuario NUNCA es certero
por observación indirecta de conversación.

#### `BeliefAttribution` — tabla separada de `SelfBelief`

**Decisión: tabla separada.** Tres razones técnicas:

1. **FK incompatible**: `SelfBelief.self_model_id` es FK al singleton `SelfModel`
   (sin `user_id`). `BeliefAttribution` requiere `user_id` obligatorio.
2. **Semántica opuesta**: SelfBelief = lo que Sity cree sobre sí misma.
   BeliefAttribution = lo que Sity cree que el usuario cree.
3. **Query patterns distintos**: SelfBelief se carga globalmente; BeliefAttribution
   siempre filtra por `user_id`.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `user_id` | int (index) | Aislamiento estricto |
| `proposition` | str (≤300 chars) | "The user believes X" |
| `confidence` | float [0, 0.65] | Cap 0.65 — atribuir creencias a otra mente es siempre especulativo |
| `source` | str | `"reflection"` \| `"explicit_statement"` \| `"inference"` |
| `context_type` | str | Contexto en que se observó (enum Fase 7) |
| `evidence_trail_json` | str `[]` | trace_ids |
| `is_active` | bool | — |
| `created_at` / `last_observed_at` | datetime | — |

**Confidence cap 0.65**: más conservadora que `SelfBelief` (0.40 como piso, no techo).
Mismo principio de sección 57, aplicado aún más estrictamente porque atribuir
creencias a otra mente es intrínsecamente especulativo.

#### `Expectation`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `user_id` | int (index) | Aislamiento por usuario |
| `context_type` | str | Reutiliza enum Fase 7 (8 valores) |
| `expected_behavior` | str | Enum de 8 valores — ver tabla abajo |
| `probability` | float [0, 1] | Probabilidad estimada |
| `evidence_trail_json` | str `[]` | trace_ids |
| `occurrence_count` | int | — |
| `last_observed_at` / `created_at` | datetime | — |
| `is_active` | bool | — |

**Enum `expected_behavior`** (8 valores, paralelo a `context_type`):

| Valor | Qué predice |
|-------|-------------|
| `ask_question` | El usuario hará una pregunta antes de continuar |
| `request_help` | El usuario pedirá asistencia directa |
| `challenge_sity` | El usuario cuestionará una respuesta o planteará contraejemplo |
| `share_feedback` | El usuario dará feedback (positivo o crítico) |
| `casual_engagement` | El usuario buscará conversación social |
| `creative_collaboration` | El usuario quiere co-crear |
| `seek_explanation` | El usuario pide que se le explique algo |
| `plan_together` | El usuario quiere planificar en colaboración |

### `user_model_service.py`

| Función | Descripción |
|---------|-------------|
| `load_knowledge(session, user_id, *, topic=None)` | Carga filas activas, opcionalmente filtradas por topic |
| `upsert_knowledge(session, *, user_id, topic, level, confidence, trace_id)` | CREATE OR UPDATE por (user_id, topic); cap confidence 0.80 |
| `load_belief_attributions(session, user_id, *, is_active=True)` | Carga BeliefAttribution filtradas por user_id |
| `add_belief_attribution(session, *, user_id, proposition, confidence, source, context_type, trace_id)` | Inserta candidata; cap confidence 0.65; trunca proposition a 300 chars |
| `load_active_expectations(session, *, user_id, context_type, min_probability=0.60)` | Carga Expectation activas ≥ umbral; siempre filtrado por user_id |
| `upsert_expectation(session, *, user_id, context_type, expected_behavior, probability, trace_id)` | CREATE OR UPDATE; valida expected_behavior contra enum |

**Invariante de aislamiento**: TODAS las consultas filtran por `user_id`. Un dato
de usuario A NUNCA puede aparecer en consultas de usuario B.

### Tests (22): `tests/test_user_model_service.py`

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestUserKnowledge` | 8 | CRUD, cap confidence, deduplication evidence_trail, aislamiento |
| `TestBeliefAttribution` | 6 | CRUD, cap confidence, truncado proposition, filtros is_active, aislamiento |
| `TestExpectation` | 8 | CRUD, upsert UPDATE, enum validation, min_probability, is_active, context_type filter, aislamiento, empty list |

---

## Paso 2 — BeliefAttribution desde Reflection Step

### Extensión zero-cost de Reflection (Fase 6, Haiku #5)

Mismo patrón de coste marginal cero ya usado en:
- `surprise`/`explicit_importance` → Appraisal (Fase 4)
- `context_type` → Perception (Fase 7 Paso 1)

**Campo añadido al JSON de Haiku**: `user_belief_updates` — décima pregunta introspectiva:

> "10. What does Sity now believe the user believes? → user_belief_updates"

**`max_tokens`**: 300 → 380 (7 campos JSON en vez de 6).

### Cambios en `reflection.py`

- `ReflectionResult.user_belief_updates: list[str]` (default `[]`)
- `_REFLECTION_SYSTEM`: 9 → 10 preguntas; `user_belief_updates` en el JSON
- `_parse_reflection_response`: parsea el nuevo campo; ausencia → `[]` (backward compat)
- `run_reflection`: persiste `user_belief_updates_json` en `ReflectionLog`;
  llama `add_belief_attribution(confidence=0.35, source="reflection",
  context_type=perception.context_type)` por cada proposición no vacía

**Confidence 0.35**: más conservadora que `SelfBelief` (0.40) — atribuir creencias
a otra mente es aún más especulativo que la metacognición sobre uno mismo.

### Migración DB — `_migrate_reflectionlog()` en `db.py`

`ReflectionLog` ya existía. Se añade columna con `ALTER TABLE ADD COLUMN ... DEFAULT '[]'`
idempotente — mismo patrón que todas las migraciones de columna del proyecto.

### Backward compatibility

`user_belief_updates=[]` (Haiku no detecta nada) → no se crean filas en
`BeliefAttribution`. Todos los tests existentes de `test_reflection_service.py`
pasan sin modificación.

### Tests (11): `tests/test_reflection_belief_attribution.py`

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestParseUserBeliefUpdates` | 3 | Parsing, key ausente → `[]`, truncado 200 chars |
| `TestBackwardCompat` | 2 | Lista vacía → sin rows, `user_belief_updates_json` en ReflectionLog |
| `TestBeliefAttributionCreation` | 5 | Confidence=0.35, source="reflection", context_type, múltiples rows, blancos ignorados |
| `TestIsolation` | 1 | User A no visible para user B |

---

## Paso 3 — Expectativas en Decision

### Señal `surprise` vs. `prediction_error` — distinción explícita

| | `surprise` (Appraisal, Fase 4) | `prediction_error` (concepto de Fase 8) |
|--|--|--|
| **Naturaleza** | Evaluación holística de Haiku | Calculable matemáticamente: `-log₂(P(event))` |
| **Referencia** | Ninguna Expectation concreta | Expectation específica activa |
| **Generación** | Todos los turnos | Solo cuando hay Expectation activa |
| **Nombre** | `surprise` | Concepto reservado — no implementado en esta fase |

**Decisión**: `prediction_error` se reserva para una futura fase. En Fase 8, las
Expectativas influyen en Decision directamente via su `probability`, sin pasar
por Appraisal ni salience. Esto mantiene los sistemas desacoplados y evita la
colisión de nombres.

### `_EXPECTATION_ACTION_MAP` en `decision.py`

Cuarto pase independiente en `compute_utility_scores()`, después de
`_PROCEDURAL_ACTION_HINTS` (tercer pase):

| `expected_behavior` | acción | delta | razonamiento |
|---------------------|--------|-------|--------------|
| `ask_question` | `ask` +0.05, `answer` +0.03 | Preparar aclaración; o anticipar |
| `request_help` | `help` +0.10, `use_tool` +0.04 | Usuario viene a pedir ayuda |
| `challenge_sity` | `challenge` +0.06, `answer` +0.04 | Preparar contra-argumento |
| `share_feedback` | `answer` +0.05, `challenge` +0.04 | Recibir o rebatir feedback |
| `casual_engagement` | `answer` +0.05, `initiate` +0.04 | Modo conversacional relajado |
| `creative_collaboration` | `initiate` +0.08, `help` +0.04 | Proactividad creativa |
| `seek_explanation` | `answer` +0.10, `ask` +0.03 | Explicar; clarificar si es necesario |
| `plan_together` | `ask` +0.08, `answer` +0.04 | Clarificar alcance; o dar plan |

### Guard explícito — `_EXPECTATION_PROBABILITY_MIN = 0.60`

```python
if active_expectations:
    for exp in active_expectations:
        if exp.probability < _EXPECTATION_PROBABILITY_MIN:
            continue  # zero delta — no adjustment at all
        hints = _EXPECTATION_ACTION_MAP.get(exp.expected_behavior, {})
        for action, delta in hints.items():
            scores[action] = scores.get(action, 0.0) + delta * exp.probability
```

**Defensa en profundidad**: `_EXPECTATION_PROBABILITY_MIN = 0.60` existe tanto
en `decision.py` (guard interno) como en el `min_probability=0.60` default de
`load_active_expectations()`. Mismo patrón que Fase 7 con
`_PROCEDURAL_CONFIDENCE_MIN`.

**Umbral 0.60 > 0.55** (ProceduralPattern): las Expectativas son predicciones
forward-looking inherentemente más especulativas que los patrones conductuales
aprendidos de historial real.

### Escenarios verificados a mano

| expected_behavior | probability | delta aplicado |
|---|---|---|
| `seek_explanation` | 0.75 | `answer` +0.10×0.75=**+0.075** |
| `request_help` | 0.70 | `help` +0.10×0.70=**+0.070** |
| `plan_together` | 0.80 | `ask` +0.08×0.80=**+0.064** |
| `challenge_sity` | 0.55 (<min) | **zero delta** — guard activado |
| `request_help` (0.70) + `seek_explanation` (0.75) | — | `help`+0.070, `answer`+0.075 acumulados |

### Integración en `turn_cognition.py`

```python
try:
    _active_exps = load_active_expectations(
        session, user_id=user_id, context_type=perception.context_type
    )
except Exception:
    _active_exps = []
decision_result = run_decision(
    ...,
    active_expectations=_active_exps or None,
)
```

### Tests (20): `tests/test_decision_expectations.py`

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestExpectationBackwardCompat` | 2 | `None`/`[]` → scores idénticos a Fase 7 |
| `TestProbabilityGuard` | 3 | 0.55 → zero delta; 0.59 → zero delta; 0.60 → delta aplicado |
| `TestExactDeltas` | 8 | `delta × probability` exacto para cada `expected_behavior` |
| `TestIsolation` | 2 | Sin contaminación cruzada; unknown behavior → zero |
| `TestMultipleExpectations` | 1 | Dos expectativas → deltas sumados independientemente |
| `TestRunDecisionIntegration` | 2 | `run_decision` acepta kwarg; `None` → comportamiento idéntico |
| `TestScenarios` | 2 | `request_help` → `help` mayor; `seek_explanation` → `answer` mayor |

---

## Invariantes de diseño

1. **Aislamiento por usuario**: todo query en las 3 tablas nuevas filtra por `user_id`.
   Un dato de usuario A NUNCA puede influir en el turno de usuario B.

2. **Caps de confidence escalonados**:
   - `UserKnowledge.confidence` ≤ 0.80 (observación indirecta)
   - `BeliefAttribution.confidence` ≤ 0.65 (atribuir creencias a otra mente)
   - Ambos caps menores que `SelfBelief` (sin techo en modelo, piso 0.40 por convención)

3. **BeliefAttribution vía Reflection**: las creencias atribuidas al usuario
   se generan SOLO en turnos de salience ≥ 0.45 (condición de Reflection existente).
   NUNCA se generan en todos los turnos.

4. **Defensa en profundidad en umbral de Expectativas**: guard 0.60 en dos sitios
   independientes — `load_active_expectations()` y el bucle en `compute_utility_scores()`.

5. **`prediction_error` vs. `surprise` son conceptos distintos**: `surprise` de
   Appraisal es holístico/subjetivo (Haiku); `prediction_error` matemático
   (-log₂(P)) se reserva para futura integración en salience. No comparten nombre.

6. **Backward compatibility total**: `active_expectations=None` y
   `user_belief_updates=[]` son no-ops. Ningún test de fases anteriores requirió
   modificación.

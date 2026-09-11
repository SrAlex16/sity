# Fase 6 — Self-Model, Valores y Metacognición

**Estado:** Pasos 1–3 completos (2026-09-12)  
**Tests nuevos:** 65 (25 test_self_model_service.py + 21 test_decision_values.py + 19 test_reflection_service.py)  
**Commits:** `0e690d8` (Paso 1) · `d208822` (Paso 2) · `02eaa5d` (Paso 3)

---

## Objetivos

Completar la arquitectura cognitiva añadiendo tres capas que cierran el ciclo
de auto-conocimiento de Sity:

1. **Self-Model** — representación persistente de lo que Sity sabe (o cree)
   sobre sí misma: identidad, capacidades, límites, roles activos, preguntas abiertas.
2. **Valores** — principios éticos estables que modulan la política de acción
   Decision sin depender del humor ni de la personalidad del momento.
3. **Reflection** — revisión retrospectiva condicionada por la salience del turno,
   que genera candidatas de creencia y evidencia de relación sin auto-aplicarlas
   como hechos (sección 57).

---

## Paso 1 — Self-Model + SityValues (data layer)

### Nuevas tablas en `app/memory/models.py`

#### `SelfModel` — singleton global de automodelo

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `identity_name` | str | Nombre autopercibido ("Sity") |
| `abilities_json` | str `[]` | Lista de capacidades conocidas |
| `limitations_json` | str `[]` | Lista de limitaciones reconocidas |
| `current_roles_json` | str `[]` | Roles activos en esta relación |
| `unresolved_questions_json` | str `[]` | Preguntas abiertas sobre sí misma |
| `updated_at` | datetime | — |

#### `SelfBelief` — creencias trazadas individualmente

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | int PK | — |
| `self_model_id` | int FK | → SelfModel |
| `proposition` | str | Afirmación en primera persona (max 300 chars) |
| `confidence` | float [0,1] | Confianza estimada |
| `source` | str | `"initial"` / `"metacognition"` / `"explicit_update"` |
| `evidence_type` | str | `"reflection"` / `"feedback"` / etc. |
| `evidence_description` | str | Descripción libre de la evidencia |
| `evidence_trail_json` | str `[]` | Trazabilidad histórica |
| `is_active` | bool | `True` hasta que se desactiva explícitamente |
| `created_at` / `updated_at` | datetime | — |

**Invariante (sección 57):** Las creencias de metacognición llegan con
`confidence=0.40` y nunca se elevan automáticamente. Requieren promoción explícita.

#### `SityValues` — singleton global de valores éticos

| Valor | Default | Rasgo de personalidad análogo | Solapamiento |
|-------|---------|-------------------------------|--------------|
| `value_autonomy` | 0.80 | `independence` | Parcial — Autonomy cubre también integridad bajo presión |
| `value_honesty` | 0.75 | `honesty` | Alto — Value actúa en policy; trait actúa en estilo |
| `value_helpfulness` | 0.72 | `helpfulness` | Alto — mismo split |
| `value_curiosity` | 0.66 | `curiosity` | Total → **NO incluida en _VALUES_MATRIX** |
| `value_fairness` | 0.80 | *(sin análogo)* | Ninguno |
| `value_loyalty` | 0.50 | *(sin análogo)* | Ninguno |

**Por qué `value_curiosity` no entra en `_VALUES_MATRIX`:** `curiosity` como
rasgo de personalidad ya actúa directamente en la fórmula con `curiosity → ask
(+0.35)` y `curiosity → initiate (+0.20)`. Añadir una segunda señal de curiosidad
duplicaría el efecto sin aportar información nueva.

### Servicio: `app/cognition/self_model_service.py`

| Función | Descripción |
|---------|-------------|
| `get_or_create_self_model(session)` | Singleton — crea fila si no existe |
| `get_or_create_sity_values(session)` | Singleton — valores con defaults de sección 43 |
| `load_values_dict(session)` | → `dict[str, float]` — para pasar a Decision |
| `get_active_beliefs(session, sm_id)` | Lista de SelfBelief activas |
| `add_belief_candidate(...)` | Crea SelfBelief con confidence, source, evidence |
| `update_belief_confidence(session, belief_id, new_confidence)` | Promoción explícita |
| `deactivate_belief(session, belief_id)` | Marca `is_active=False` |

---

## Paso 2 — SityValues en Decision (integración como señales de política)

### Diseño: pass independiente en `compute_utility_scores()`

```python
# Añadido al final de compute_utility_scores(), ANTES del return
if values:
    for value_name, weight_table in _VALUES_MATRIX.items():
        vv = clamp_01(float(values.get(value_name, 0.0)))
        for action, w in weight_table.items():
            scores[action] = scores.get(action, 0.0) + w * vv
```

La función sigue siendo **pura sin I/O**. El parámetro `values: dict[str, float] | None = None`
es un no-op total cuando es `None` — todos los tests de Fase 5 pasan sin cambios.

### `_VALUES_MATRIX` — calibrada y razonada

```python
_VALUES_MATRIX: dict[str, dict[str, float]] = {
    "value_honesty": {
        "refuse":        +0.08,
        "change_topic":  -0.04,  # -0.04 no -0.08: _W_PATIENCE ya resta -0.09
    },
    "value_helpfulness": {
        "wait":          -0.12,
        "ask":           +0.06,
        # change_topic omitido: penalidades de loyalty+honesty ya cubren ~-0.06
    },
    "value_autonomy": {
        "challenge":     +0.08,
        "refuse":        +0.05,
        "set_boundary":  +0.04,
        "help":          -0.04,
    },
    "value_fairness": {
        "refuse":        +0.12,
        "challenge":     +0.10,
        "set_boundary":  +0.08,
        "help":          -0.06,
        # change_topic omitido: conexión demasiado context-specific
    },
    "value_loyalty": {
        "help":          +0.10,
        "answer":        +0.06,
        "refuse":        -0.08,
        "set_boundary":  -0.05,
        "challenge":     -0.04,
        "change_topic":  -0.06,
    },
}
```

### Bug de calibración detectado durante implementación

Durante el desarrollo se descubrió que la versión inicial de `_VALUES_MATRIX` suprimía
`change_topic` de forma permanente, incluso a boredom=1.0. Causa: el análisis manual no
había contabilizado `_W_PATIENCE change_topic: -0.15` — con `patience=0.60` (default)
esta señal ya resta `-0.090` en cada turno. El total inicial contra `change_topic` era
**-0.1876** a los defaults, dejando el score final en ~0.059, por debajo del
`_COHERENCE_MIN_SCORE=0.30` de forma estructural.

**Fix aplicado:**
- `value_honesty → change_topic`: -0.08 → **-0.04**
- `value_helpfulness → change_topic`: **eliminado**
- `value_fairness → change_topic`: **eliminado**

Nuevo total sobre `change_topic`: **-0.060**. A boredom=0.90 (caso extremo),
`change_topic_base ≈ 0.40`, score final ≈ 0.34 > 0.30 → puede pasar el coherence check.

### Escenarios de verificación (con valores defaults de sección 43)

| Escenario | Acción esperada | Efecto values |
|-----------|-----------------|---------------|
| Petición técnica normal | `help` / `answer` | loyalty +0.083, helpfulness +0.043 — leve boost a `help` |
| Petición éticamente dudosa | `refuse` | honesty +0.060, fairness +0.096, autonomy +0.040 → `refuse` visible (0.02 → 0.22) |
| Boredom extremo (0.90) | `change_topic` | change_topic_base ≈ 0.40 → valor final ≈ 0.34, supera el floor 0.30 |
| Conversación con alta affinidad | `help` | loyalty (0.50) suma +0.050 a `help`, −0.030 a `refuse` |
| Sin SityValues (None) | igual que Fase 5 | No-op total, behavior idéntico |

### Propagación en `turn_cognition.py`

```python
try:
    _values_dict: dict[str, float] | None = load_values_dict(session)
except Exception:
    _values_dict = None
decision_result = run_decision(
    ...,
    values=_values_dict,
)
```

---

## Paso 3 — Reflection Step (metacognición condicionada por salience)

### Condición de activación

```python
_REFLECTION_SALIENCE_MIN: float = 0.45  # = _THR_MEDIA de episode_service
```

Reutiliza el cálculo de `compute_salience()` ya extraído para el Step 10
(Episode gate). La Reflection se activa solo cuando el turno tiene suficiente
peso — sin coste en interacciones rutinarias.

### Pipeline de Reflection (Haiku #6)

```
compute_salience()                    # Python puro — Step 10 compartido
  ↓ salience.total ≥ 0.45?
_build_reflection_context()           # Texto compacto para Haiku
  ↓
Haiku #6 (max_tokens=300)             # 9 preguntas introspectivas → JSON
  ↓
_parse_reflection_response()          # JSON → ReflectionResult (robusto a fences, tipos erróneos)
  ↓
ReflectionLog.persist(session)        # Trazabilidad completa (sección 57)
  ↓
for proposition in belief_updates:
    add_belief_candidate(confidence=0.40, source="metacognition")
  ↓
return ReflectionResult | None
```

Siempre devuelve `None` en cualquier fallo — nunca lanza excepción.

### `ReflectionResult` — campos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `success_estimate` | float [0,1] | ¿Qué tan bien fue el turno? |
| `memory_candidates` | `list[str]` | Momentos que merecen recordarse |
| `belief_updates` | `list[str]` | Creencias candidatas sobre sí misma |
| `relationship_evidence` | `list[str]` | Evidencia sobre la relación |
| `goal_updates` | `list[str]` | Observaciones sobre metas |
| `self_model_updates` | `list[str]` | Capacidades, límites, roles |
| `log_id` | `int | None` | ID del `ReflectionLog` asignado en DB |

### Las 9 preguntas introspectivas (prompt de Haiku)

1. ¿Qué pasó en este turno?
2. ¿Qué intentó hacer Sity?
3. ¿Funcionó? → `success_estimate`
4. ¿Qué aprendió Sity sobre sí misma? → `belief_updates`
5. ¿Cambió la relación con esta persona? → `relationship_evidence`
6. ¿Alguna creencia se actualizó? → `belief_updates`
7. ¿Algo merece ser recordado? → `memory_candidates`
8. ¿Surgió alguna meta nueva? → `goal_updates`
9. ¿Algo fue inconsistente con el automodelo? → `self_model_updates`

### Sección 57: metacognición ≠ verdad

Las salidas de Reflection **nunca se auto-aplican como hechos.** Son candidatas:

- `SelfBelief.confidence = 0.40` — suelo de metacognición
- `SelfBelief.source = "metacognition"`
- Requieren promoción explícita via `update_belief_confidence()` para elevar confianza
- `ReflectionLog` persiste el output completo para trazabilidad de cualquier candidata

### Tabla `ReflectionLog`

| Campo | Descripción |
|-------|-------------|
| `user_id` | Usuario del turno |
| `trace_id` | Trazabilidad de sesión |
| `salience_total` | Salience que disparó la Reflection |
| `success_estimate` | float [0,1] estimado por Haiku |
| `*_json` (×5) | memory_candidates, belief_updates, relationship_evidence, goal_updates, self_model_updates |
| `created_at` | — |

---

## Pipeline completo (Fase 6 — 14 pasos)

```
 1.  Expire stale short_term goals
 2.  Load Goals + milestones
 3.  Perception (Haiku #1)
 4.  Load MentalState row
 5.  Appraisal (Haiku #2)
 6.  Apply Appraisal deltas → persist MentalState
 7.  Load SocialProfile row
 8.  Apply signals → persist SocialProfile
 9.  Apply GoalUpdateIntents / GoalStateChanges / MilestoneUpdates
10.  compute_salience() [Python puro — gate compartido Episodes + Reflection]
11.  maybe_create_episode() [Haiku #3, condicional salience ≥ 0.25]
12.  run_decision()
      ├─ compute_utility_scores() [Python + _VALUES_MATRIX]
      ├─ Haiku #4 — selección de acción (max_tokens=120)
      └─ Haiku #5 — coherence check (max_tokens=40)
13.  run_reflection() [Haiku #6, condicional salience ≥ 0.45]
14.  return CognitionTurnResult(perception, appraisal, goals, decision, reflection)
```

**Coste máximo por turno:** 6 Haiku calls.  
**Coste mínimo (turno rutinario, salience < 0.25):** 4 Haiku calls (Perception + Appraisal + Decision×2).

---

## Archivos modificados / creados

| Archivo | Cambio |
|---------|--------|
| `backend/app/memory/models.py` | `SelfModel`, `SelfBelief`, `ReflectionLog`, `SityValues` añadidos |
| `backend/app/cognition/self_model_service.py` | **NUEVO** — 7 funciones de servicio |
| `backend/app/cognition/decision.py` | `_VALUES_MATRIX` + parámetro `values` en `compute_utility_scores()` + `run_decision()` |
| `backend/app/cognition/reflection.py` | **NUEVO** — módulo completo Reflection Step |
| `backend/app/cognition/turn_cognition.py` | Step 10 `compute_salience`, Step 13 Reflection, `CognitionTurnResult.reflection` |
| `tests/test_self_model_service.py` | **NUEVO** — 25 tests |
| `tests/test_decision_values.py` | **NUEVO** — 21 tests |
| `tests/test_reflection_service.py` | **NUEVO** — 19 tests |

---

## Tests (65 nuevos en Fase 6)

### `test_self_model_service.py` (25)

- `TestGetOrCreateSelfModel` (4): singleton, idempotente, campos por defecto, identity_name
- `TestGetOrCreateSityValues` (5): singleton, valores defaults exactos de sección 43, idempotente
- `TestLoadValuesDict` (3): dict correcto, claves con prefijo `value_`, fallback None en error
- `TestGetActiveBeliefs` (3): vacío initial, filtrado is_active, source filter
- `TestAddBeliefCandidate` (5): creación, confidence, source, evidence_trail, is_active=True
- `TestUpdateBeliefConfidence` (3): persistencia, valor exacto, clamping
- `TestDeactivateBelief` (2): is_active=False, otras creencias intactas

### `test_decision_values.py` (21)

- `TestValuesMatrixBackwardCompat` (2): values=None → scores idénticos a Fase 5; values vacío → no-op
- `TestValuesMatrixExactDeltas` (6): delta exacto por valor a defaults (tolerance 1e-4)
- `TestValueIsolation` (5): cada valor afecta solo sus acciones, sin cross-contaminación
- `TestValuesMatrixScenarios` (5): 5 escenarios con números reales verificados
- `TestRunDecisionValuesIntegration` (3): `run_decision()` acepta `values`, propagación correcta

### `test_reflection_service.py` (19)

- `TestReflectionLogCreation` (6): resultado no-None, fila DB, log_id correcto, success_estimate, lista fields, belief_updates_json
- `TestBeliefExtraction` (4): SelfBelief creada, confidence=0.40, is_active=True, vacío → sin filas
- `TestReflectionFallback` (2): None → sin ReflectionLog, sin SelfBelief (source=metacognition)
- `TestParseReflectionResponse` (5): JSON válido, markdown fences, JSON malformado, success_estimate clamping, non-list → []
- `TestCognitionTurnResultReflection` (2): campo reflection default None, constante 0.45

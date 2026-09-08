# Fase 2 — Appraisal, Perception y sistema de metas con ciclo de vida completo

## Resumen

Fase 2 añade dos capas de cognición por turno (Perception + Appraisal) y un sistema de metas
persistentes con máquina de estados, hitos incrementales y resolución automática de metas de
sesión. Todo corre para sesiones `user:` autenticadas; las sesiones guest/default no se ven
afectadas.

---

## 1. Perception

**Módulo:** `app/cognition/perception.py`

Haiku call por turno (max_tokens=80). Clasifica el mensaje del usuario en 5 dimensiones:

| Campo          | Tipo      | Rango / Valores                                                   |
|----------------|-----------|-------------------------------------------------------------------|
| `user_intent`  | str       | request, question, vent, joke, greeting, farewell, task, opinion, complaint, other |
| `tone`         | str       | playful, serious, frustrated, ironic, neutral, warm, hostile, curious, sad, anxious, other |
| `challenge`    | float     | [0, 1] — grado de confrontación                                   |
| `social_signal`| float     | [0, 1] — señal de vínculo/relación                               |
| `novelty`      | float     | [0, 1] — novedad percibida del tema                               |

Fallback: `PerceptionResult.neutral()` en cualquier error. Nunca bloquea el pipeline.

---

## 2. Appraisal

**Módulo:** `app/cognition/appraisal.py`

Segunda Haiku call por turno (max_tokens=300). Recibe: Perception + MentalState + Personality +
metas activas con sus hitos. Produce:

| Campo               | Tipo                     | Descripción                                                  |
|---------------------|--------------------------|--------------------------------------------------------------|
| `interest_delta`    | float [-0.3, 0.3]        | Cambio en MentalState.interest                               |
| `frustration_delta` | float [-0.3, 0.3]        | Cambio en MentalState.frustration                            |
| `trust_evidence`    | float [0, 0.05]          | Evidencia de confianza → nudge a social_comfort (×0.5)       |
| `goal_updates`      | list[GoalUpdateIntent]   | Metas nuevas a crear                                         |
| `goal_relevance`    | list[GoalRelevance]      | Relevancia por-turno de cada meta activa                     |
| `goal_state_changes`| list[GoalStateChange]    | Transiciones de estado (active → resolved / abandoned)       |
| `milestone_updates` | list[MilestoneIntent]    | Añadir hitos a metas o marcar hitos como completados         |

Fallback: `AppraisalResult.zero()` en cualquier error.

### Decisión de diseño: inercia en MentalState

Los deltas se aplican directamente a MentalState sin suavizado adicional. Rationale: MentalState
acumula su propia memoria a través del tiempo. La inercia aplica a `SocialProfile.trust`
(relación establecida que no se sacude por un turno malo), no al estado emocional momentáneo.

### trust_evidence → social_comfort

`trust_evidence` no se almacena en MentalState; en cambio causa un nudge de +`trust_evidence * 0.5`
a `social_comfort`. Es una señal proxy de la calidez relacional del turno.

---

## 3. Sistema de metas (Goal)

**Tabla:** `Goal` (en `app/memory/models.py`)

| Campo            | Tipo    | Descripción                                                         |
|------------------|---------|---------------------------------------------------------------------|
| `id`             | int     | PK                                                                  |
| `user_id`        | int     | FK a User.id (aislamiento por usuario)                              |
| `scope`          | str     | `"short_term"` \| `"long_term"`                                     |
| `description`    | str     | Descripción concisa de la meta                                      |
| `origin`         | str     | `"autonomous"` \| `"user_suggested"`                                |
| `base_importance`| float   | [0, 1] — fijado en creación, no cambia                              |
| `status`         | str     | `"active"` \| `"resolved"` \| `"abandoned"` \| `"expired"`         |
| `is_wellbeing`   | bool    | Excepción de seguridad — ver sección 5                              |
| `created_at`     | datetime|                                                                     |
| `resolved_at`    | datetime| Solo para status=resolved                                           |

---

## 4. Hitos (GoalMilestone)

**Tabla:** `GoalMilestone` (en `app/memory/models.py`)

Una meta puede tener 0 hitos (meta simple) o varios (meta compleja, descompuesta
incrementalmente). El progreso se mide contando hitos completados; no se almacena porcentaje.

| Campo         | Tipo     | Descripción                                         |
|---------------|----------|-----------------------------------------------------|
| `id`          | int      | PK                                                  |
| `goal_id`     | int      | FK a Goal.id (indexed)                              |
| `description` | str      | Descripción del sub-paso                            |
| `status`      | str      | `"pending"` \| `"completed"`                        |
| `order_index` | int      | Orden lógico dentro de la meta                      |
| `created_at`  | datetime |                                                     |
| `completed_at`| datetime | Solo para status=completed                          |

### Generación incremental

Appraisal puede añadir hitos en cualquier turno conforme la conversación revela mayor
complejidad. El diseño es deliberadamente incremental: no se exige una descomposición completa
al crear la meta.

`GoalUpdateIntent.initial_milestones: list[str]` permite que Appraisal incluya hitos iniciales
en el mismo turno en que crea la meta.

---

## 5. Priorización dinámica

**Módulo:** `app/cognition/goal_priority.py`

```
effective_priority = 0.6 * base_importance + 0.4 * (relevance_boost * irony_factor)
```

- `base_importance` — fijado en creación; provee un suelo estable
- `relevance_boost` — `GoalRelevance.relevance` del turno actual (Appraisal)
- `irony_factor` — reduce el boost cuando el tono es irónico/playful

### Excepción de seguridad `is_wellbeing=True`

Para metas con `is_wellbeing=True`, `irony_factor` es siempre `1.0` — regla de código explícita,
no instrucción de prompt:

```python
def _irony_factor(tone: str, is_wellbeing: bool) -> float:
    if is_wellbeing:          # early return — no irony computation runs
        return 1.0
    ...
```

Rationale: el tono irónico o playful puede enmascarar angustia genuina. Reducir la prioridad
de una meta de bienestar porque el usuario parece estar bromeando sería peligroso.

Esta excepción está cubierta por un test de regresión de comportamiento en
`tests/test_behavior_regression.py::test_security_wellbeing_priority_not_reduced_by_irony`.

---

## 6. Máquina de estados de Goal

Transiciones válidas desde `"active"`:

```
active → resolved   (Appraisal detecta logro claro; sets resolved_at)
active → abandoned  (Appraisal detecta renuncia explícita, o logout explícito del usuario)
active → expired    (auto-expiración de short_term al inicio del siguiente turno — red de seguridad)
```

Ninguna transición devuelve a `"active"`. La capa DB lo garantiza: `apply_goal_state_changes`
solo actúa sobre goals con `status == "active"`.

### Cierre por logout explícito (mecanismo primario para short_term)

`resolve_short_term_goals_on_logout(session, user_id)` en `goal_service.py` se llama desde
`POST /auth/logout` (routes_auth.py) inmediatamente antes de limpiar la cookie. Marca como
`"abandoned"` todas las metas `short_term` con `status == "active"` del usuario.

Se usa `"abandoned"` (no `"resolved"`) porque el cierre de sesión no confirma que las metas
se cumplieron — solo que la sesión terminó. `"expired"` queda reservado para expiración
automática por tiempo (mecanismo secundario).

### Resolución automática de short_term (red de seguridad)

`resolve_expired_short_term_goals(session, user_id, *, max_age_hours=24)` se llama al inicio
de cada `run_cognition_turn`, antes de cargar los goals activos. Marca como `"expired"` las
metas `short_term` con `created_at < utc_now() - max_age_hours`. Cubre el caso de sesiones
que terminan sin logout explícito (JWT expirado, pestaña cerrada).

`"expired"` es distinto de `"abandoned"`: indica expiración automática, no acción del usuario.

---

## 7. Metas similares — política de no-duplicación

Appraisal recibe las metas activas del usuario en cada turno. El prompt incluye la guideline:

> "Before creating a new goal, check the ACTIVE GOALS list. If a new goal is semantically similar
> to an existing one (same domain, similar objective), prefer adding milestones to the existing
> goal rather than creating a duplicate. Only create a new goal when the objective is clearly
> distinct from all active goals."

**Decisión deliberada de no implementar:** tabla `GoalSimilarity`, algoritmos de embedding,
FK de hito-a-múltiples-metas. El caso de metas similares con hitos compartidos es un caso de
borde infrecuente; la infraestructura para modelarlo explícitamente sería desproporcionada
frente al valor. Appraisal resuelve el caso turnísticamente con el contexto que ya tiene.

---

## 8. Integración con el pipeline de turno

**Módulo:** `app/cognition/turn_cognition.py` — `run_cognition_turn()`

Secuencia por turno para sesiones `user:`:

1. `resolve_expired_short_term_goals()` — cierra goals de sesión caducos
2. `get_active_goals()` + `get_milestones_for_goal()` — carga contexto de goals
3. `run_perception()` — Haiku call, clasifica el mensaje
4. `get_or_create_mental_state()` — carga fila SQLModel (no el dict de TurnContext)
5. `run_appraisal()` — Haiku call con Perception + MentalState + Goals + Hitos
6. `apply_appraisal_to_mental_state()` + `save_mental_state()` — persiste deltas
7. `apply_goal_intents()` — crea goals nuevos
8. `apply_goal_state_changes()` — transiciones de estado
9. `apply_milestone_updates()` — añade / completa hitos

**Nota de timing del MentalState:** `TurnContext.mental_state` es un snapshot dict creado
antes de que corra cognition y ya pasado a PersonaEngine. Los deltas de Appraisal se aplican
al objeto SQLModel y persisten para el SIGUIENTE turno. Esto es intencional.

### Integración con Expression (turno normal)

`build_active_goals_block(active_goals, appraisal, tone)` inyecta en `persona_prompt` hasta 3
metas con `effective_priority >= 0.5`, ordenadas por prioridad descendente. Solo aplica a
turnos no-refusal (la ruta de refusal tiene su propio generador aislado).

### Integración con Initiative (SHOULD_I_TALK?)

`evaluator.py` carga metas `long_term` activas vía `_get_active_long_term_goals()` y las
incluye en el contexto Haiku del evaluador de iniciativa. Solo metas a largo plazo: las de
corto plazo son demasiado efímeras para influir en si Sity debe iniciar conversación.

---

## 9. Archivos modificados / creados

| Archivo                                   | Cambio                                                  |
|-------------------------------------------|---------------------------------------------------------|
| `backend/app/memory/models.py`            | +Goal, +GoalMilestone                                   |
| `backend/app/cognition/__init__.py`       | creado (vacío)                                          |
| `backend/app/cognition/perception.py`     | creado                                                  |
| `backend/app/cognition/appraisal.py`      | creado                                                  |
| `backend/app/cognition/goal_priority.py`  | creado                                                  |
| `backend/app/cognition/goal_service.py`   | creado                                                  |
| `backend/app/cognition/turn_cognition.py` | creado                                                  |
| `backend/app/chat/turn_runner.py`         | +run_cognition_turn, +goals block injection             |
| `backend/app/initiative/evaluator.py`     | +_get_active_long_term_goals, +goals en contexto Haiku  |
| `backend/app/api/routes_auth.py`          | logout() llama resolve_short_term_goals_on_logout()     |
| `tests/test_cognition.py`                 | creado — 137 tests                                      |
| `tests/test_auth.py`                      | +test_logout_closes_short_term_goals_immediately        |
| `tests/test_behavior_regression.py`       | +test_security_wellbeing_priority_not_reduced_by_irony  |

---

## 10. Commits

| Hash      | Descripción                                                          |
|-----------|----------------------------------------------------------------------|
| `6027689` | Paso 1 — Goal table + Perception + Appraisal + 41 tests             |
| `f7c4a2a` | Paso 2 — Priorización dinámica + excepción is_wellbeing             |
| `b1efc1c` | Paso 3 — GoalService + pipeline + Expression/Initiative             |
| `5811080` | Paso 4 Part 1 — GoalMilestone table + state machine                 |
| `279784c` | Paso 4 Parts 2-4 — hitos + auto-expiración 24h + documentación     |
| `3d1f527` | Ajuste — cierre primario por logout (resolve_short_term_on_logout)  |

# Pipeline Cognitivo Completo — Mapa Maestro

**Fecha:** 2026-09-12 (post-Operación Remake Fases 1–9 + ajuste goal_urgent)

Este documento describe el orden real de ejecución de todo el pipeline cognitivo por turno,
con las llamadas Haiku exactas, sus condiciones de activación, y los procesos de fondo.
Para el diseño detallado de cada fase ver los documentos individuales referenciados.

---

## Prerrequisitos de activación

El pipeline cognitivo completo **solo corre para sesiones `user:` autenticadas**.
Sesiones `guest:` o `default:` bypasan todo el pipeline y van directamente a Expression.

**Entry point:** `app/cognition/turn_cognition.py` → `run_cognition_turn()`
**Llamado desde:** `app/chat/turn_runner.py` antes de construir el prompt de Expression.

---

## Pipeline por turno

```
INPUTS: session, user_id, user_message, personality, trace_id
```

### Paso 1 — Expiración de metas caducadas (puro DB)
`resolve_expired_short_term_goals(session, user_id)`
Cierra como `expired` las metas `short_term` creadas hace > 24h. Mantiene el contexto
de Appraisal limpio. Sin Haiku.
→ _Diseño: docs/remake/fase-2-appraisal-goals.md §6_

---

### Paso 2 — Carga de Goals + Milestones activos (puro DB)
`get_active_goals()` + `get_milestones_for_goal()` por cada goal.
Construye la lista `active_goals_dicts` que Appraisal recibirá.
→ _Diseño: docs/remake/fase-2-appraisal-goals.md §3-4_

---

### Paso 3 — **Haiku #1: Perception** (siempre)
```
Módulo:      app/cognition/perception.py → run_perception()
max_tokens:  110
Fallback:    PerceptionResult.neutral() en cualquier error
```
Clasifica el mensaje del usuario en 6 dimensiones:

| Campo           | Tipo  | Descripción                                                    |
|-----------------|-------|----------------------------------------------------------------|
| `user_intent`   | str   | request / question / vent / joke / greeting / farewell / task / opinion / complaint / other |
| `tone`          | str   | playful / serious / frustrated / ironic / neutral / warm / hostile / curious / sad / anxious / other |
| `challenge`     | float | [0,1] — grado de confrontación                                 |
| `social_signal` | float | [0,1] — señal de vínculo/relación                             |
| `novelty`       | float | [0,1] — novedad percibida del tema                             |
| `context_type`  | str   | 8 valores: task / emotional / social / creative / learning / planning / casual / other |

→ _Diseño: docs/remake/fase-2-appraisal-goals.md §1, docs/remake/fase-7-memoria-procedimental.md_

---

### Paso 4 — Carga de MentalState (puro DB)
`get_or_create_mental_state(user_id)`
Snapshot de 9 dimensiones: interest, frustration, social_comfort, valence, arousal,
current_curiosity, boredom, melancholy, defensiveness.
→ _Diseño: docs/remake/fase-1-personalidad.md_

---

### Paso 5 — **Haiku #2: Appraisal** (siempre)
```
Módulo:      app/cognition/appraisal.py → run_appraisal()
max_tokens:  350
Fallback:    AppraisalResult.zero() en cualquier error
```
Recibe: Perception + MentalState snapshot + Personality + Goals+Milestones activos.
Produce 10 campos:

| Campo                | Descripción                                                          |
|----------------------|----------------------------------------------------------------------|
| `interest_delta`     | float [−0.3, 0.3] — cambio en MentalState.interest                 |
| `frustration_delta`  | float [−0.3, 0.3] — cambio en MentalState.frustration              |
| `trust_evidence`     | float [0, 0.05] → nudge a social_comfort (×0.5)                    |
| `goal_updates`       | list[GoalUpdateIntent] — metas nuevas a crear                       |
| `goal_relevance`     | list[GoalRelevance] — relevancia por-turno de cada meta activa      |
| `goal_state_changes` | list[GoalStateChange] — transiciones active→resolved/abandoned      |
| `milestone_updates`  | list[MilestoneIntent] — añadir/completar hitos                     |
| `surprise`           | float [0,1] — sorpresa holística (≠ prediction_error: ver nota)    |
| `explicit_importance`| float [0,1] — importancia declarada explícitamente por el usuario  |

→ _Diseño: docs/remake/fase-2-appraisal-goals.md §2_

> **Nota crítica — `surprise` vs `prediction_error`:**
> `surprise` (AppraisalResult) = valoración holística/Haiku de lo inesperado del turno.
> `prediction_error` = −log₂(P(event)) referenciado a una Expectation concreta (Fase 8).
> Son semánticamente distintos y viven en capas distintas. `prediction_error` está
> **reservado para futura fase** y no existe aún en el código.

---

### Paso 6 — Persiste deltas en MentalState (puro DB)
`apply_appraisal_to_mental_state(ms_row, appraisal)` + `save_mental_state(ms_row)`
Los 9 campos de MentalState se actualizan en el SQLModel row y se persisten.
**Timing:** `TurnContext.mental_state` ya fue pasado a PersonaEngine como snapshot
ANTES de este paso. Los deltas son visibles en el SIGUIENTE turno.

---

### Paso 7 — Carga SocialProfile (puro DB)
`get_or_create_social_profile(session, user_id)`
11 dimensiones: familiarity, affinity, conflict, trust_honesty, trust_intentions,
trust_competence, trust_reliability, social_comfort, attachment_security, openness,
emotional_depth.

---

### Paso 8 — Actualiza SocialProfile (puro DB)
`apply_appraisal_to_social_profile(...)` + `session.commit()`
Aplica señales de Appraisal (trust_evidence, interest/frustration deltas) y Perception
(social_signal, challenge) sobre las 11 dimensiones relacionales.
→ _Diseño: docs/remake/fase-3-relacion-multidimensional.md_

---

### Paso 9 — Aplica intenciones de Goals (puro DB, condicional)
- `apply_goal_intents()` — si `appraisal.goal_updates` non-empty
- `apply_goal_state_changes()` — si `appraisal.goal_state_changes` non-empty
- `apply_milestone_updates()` — si `appraisal.milestone_updates` non-empty
→ _Diseño: docs/remake/fase-2-appraisal-goals.md §3-5_

---

### Paso 10 — Cálculo de salience (puro Python)
`compute_salience(perception, appraisal)` → `SalienceBreakdown`

```
salience = 0.20*novelty + 0.15*emotional_intensity + 0.25*goal_relevance
         + 0.15*relationship_impact + 0.10*surprise + 0.05*repetition(=0)
         + 0.10*explicit_importance
```
Regla especial: si `explicit_importance > 0.70` → `salience = max(salience, 0.45)`

Este valor `salience.total` actúa como **compuerta dual**:
- `≥ 0.25` → activa Haiku #3 (Episode)
- `≥ 0.45` → activa Haiku #6 (Reflection)

→ _Diseño: docs/remake/fase-4-memoria-episodica-autobiografica.md_

---

### Paso 11 — **Haiku #3: Episode** (condicional: salience ≥ 0.25)
```
Módulo:      app/cognition/episode_service.py → maybe_create_episode()
max_tokens:  150
Condición:   salience.total ≥ 0.25
```
Genera un resumen del episodio y lo persiste como `Episode`. Strength:
- `0.25 ≤ salience < 0.45` → `strength=0.50` (media)
- `salience ≥ 0.45` → `strength=1.00` (alta/muy_alta)

→ _Diseño: docs/remake/fase-4-memoria-episodica-autobiografica.md_

---

### Paso 12 — **Haiku #4 + #5: Decision** (siempre, salvo error técnico)
```
Módulo:      app/cognition/decision.py → run_decision()
Haiku #4:    max_tokens=120  (selección de acción)
Haiku #5:    max_tokens=40   (coherence check)
Fallback:    DecisionResult=None → turn_runner.py usa sistema antiguo
```

Pre-trabajo (puro DB, antes de las llamadas Haiku):
- `load_values_dict(session)` → `SityValues` (6 valores)
- `load_active_patterns(session, user_id, context_type)` → `ProceduralPattern` activos
- `load_active_expectations(session, user_id, context_type)` → `Expectation` activos

**`compute_utility_scores()` — 4 passes independientes:**

| Pass | Fuente                  | Señales                                     |
|------|-------------------------|---------------------------------------------|
| 1    | Base                    | 22 señales × 10 acciones (fórmula U(a))     |
| 2    | SityValues              | `_VALUES_MATRIX` — 5 valores × 10 acciones  |
| 3    | ProceduralPatterns      | `_PROCEDURAL_ACTION_HINTS` — 8 context_types, guard `confidence ≥ 0.55` |
| 4    | Expectations            | `_EXPECTATION_ACTION_MAP` — guard `probability ≥ 0.60` |

→ Haiku #4 selecciona 1 de 10 acciones: `answer`, `ask_question`, `emotional_support`,
`change_topic`, `share_opinion`, `wait`, `tell_story`, `self_disclose`, `validate`, `challenge`.

→ Haiku #5 verifica coherencia: rechaza si la acción es manifiestamente incoherente.

Resultado: `DecisionResult(action, reasoning, coherence_passed)` | `None`.

→ _Diseño: docs/remake/fase-5-decision-expression.md, fase-6, fase-7, fase-8_

---

### Paso 13a — Carga SemanticFacts (puro DB)
`load_active_facts(session, user_id)` → top facts por confidence descendente.
Solo lectura; se pasa a Reflection como contexto. Sin Haiku.
→ _Diseño: docs/remake/fase-9-consolidacion-semantica.md_

---

### Paso 13b — **Haiku #6: Reflection** (condicional: salience ≥ 0.45)
```
Módulo:      app/cognition/reflection.py → run_reflection()
max_tokens:  380
Condición:   salience.total ≥ 0.45
```
10 preguntas introspectivas retrospectivas (sobre el turno actual + sesión).
Recibe SemanticFacts como sección "KNOWN USER FACTS" — **zero coste marginal**
(inyectado en el contexto Haiku ya existente).

Outputs:
- `ReflectionLog` persistido en DB
- `SelfBelief` candidatas (`confidence=0.40, source="metacognition"`) — **nunca auto-hechos**
- `BeliefAttribution` updates (`confidence=0.35, source="reflection"`) — ToM del usuario

→ _Diseño: docs/remake/fase-6-selfmodel-valores-metacognicion.md §Paso 3,
  docs/remake/fase-8-usermodel-teoria-mente-expectativas.md §Paso 2,
  docs/remake/fase-9-consolidacion-semantica.md §Paso 3_

---

### Paso 14 — Retorno de CognitionTurnResult
```python
CognitionTurnResult(perception, appraisal, active_goals, decision, reflection)
```
`run_cognition_turn()` retorna. Control vuelve a `turn_runner.py`.

---

### Paso 15 — ProceduralObservation + dispatch daemon (non-blocking)
`maybe_trigger_pattern_synthesis(session, user_id, context_type, user_message, trace_id)`

1. INSERT `ProceduralObservation` (ligero, siempre).
2. Count observaciones no procesadas para `(user_id, context_type)`.
3. Si `count ≥ _PROCEDURAL_THRESHOLD (3)` → lanza daemon thread `_run_pattern_synthesis`.

El daemon **nunca bloquea el turno**. Cualquier excepción se registra y se descarta.
→ _Diseño: docs/remake/fase-7-memoria-procedimental.md_

---

## Expression (en turn_runner.py, tras run_cognition_turn())

Si `decision.action` is not None:
- `build_action_instruction(action)` genera el bloque de instrucción
- Se inyecta en `persona_prompt` como `\nACCIÓN DECIDIDA: <instrucción>`
- Excepción: `action="answer"` → sin instrucción (comportamiento por defecto)
- Excepción: `action="wait"` → fallback a "answer" + log

Si `decision is None` (fallback): se usa el sistema antiguo (toolset_selector + refusal_mode).

**Main LLM call** (Sonnet o Haiku vía model router): esta es la llamada principal
que genera la respuesta visible al usuario. No contada en el presupuesto Haiku de cognición.

---

## Procesos de fondo (daemon threads, non-blocking)

Estos procesos corren **fuera del turno** — no bloquean la respuesta ni afectan latencia.

### A. ProceduralPattern synthesis
```
Disparado:   en Paso 15, si ≥3 ProceduralObservations sin procesar para (user_id, context_type)
Haiku:       max_tokens=150
Módulo:      app/cognition/procedural_service.py → _run_pattern_synthesis()
```
Genera o actualiza `ProceduralPattern` con `strategy_description`, bump de
`confidence` (fórmula: `min(0.85, 0.45 + (count−3)×0.04)`) y marca observaciones processed.

### B. SocialReflection (snapshotting periódico)
```
Disparado:   app/social/update.py → _run_social_update() cuando pending_loads ≥ threshold (10)
Haiku:       max_tokens=200  (si Δcombined ≥ 0.08 + ≥20 mensajes, o Δcombined ≥ 0.20)
```
Snapshot de `RelationshipSnapshot` + generación de `SocialReflection` Haiku condicional.

### C. AutobiographicalNarrative
```
Disparado:   dentro de _run_social_update(), después de SocialReflection
Haiku:       max_tokens=320  (si ≥3 episodios muy_alta nuevos desde última narrativa)
Módulo:      app/social/update.py → _maybe_generate_narrative()
```

### D. SemanticFact consolidation
```
Disparado:   inline en _run_social_update(), después de _maybe_generate_narrative()
Haiku:       max_tokens=400  (si ≥3 Episodes sin semantically_processed)
Módulo:      app/cognition/semantic_service.py → maybe_trigger_semantic_consolidation()
```
Sintetiza `SemanticFact` (hechos estables sobre el usuario) de batch de episodios.
Anti-duplicación via contexto (no pasada de fusión explícita).

---

## Resumen de llamadas Haiku por turno

| # | Módulo      | Condición         | max_tokens | Función                            |
|---|-------------|-------------------|------------|------------------------------------|
| 1 | perception  | siempre           | 110        | Clasificar turno en 6 dimensiones  |
| 2 | appraisal   | siempre           | 350        | Evaluar impacto en estado+metas    |
| 3 | episode     | salience ≥ 0.25   | 150        | Crear memoria episódica            |
| 4 | decision    | siempre¹          | 120        | Seleccionar acción entre 10        |
| 5 | coherence   | siempre¹          | 40         | Verificar coherencia de acción     |
| 6 | reflection  | salience ≥ 0.45   | 380        | Revisión introspectiva del turno   |

¹ Haiku #4 y #5 se saltan únicamente en caso de error técnico en la orquestación de Decision
  (excepción en turn_cognition.py paso 12). En operación normal siempre corren.

**Por turno normal (sin errores técnicos):**
- **Mínimo: 4 llamadas Haiku** — cuando salience < 0.25 (ni Episode ni Reflection)
- **Máximo: 6 llamadas Haiku** — cuando salience ≥ 0.45 (Episode + Reflection ambos activos)

**Budget de tokens por turno (máximo, solo Haiku de cognición):**
110 + 350 + 150 + 120 + 40 + 380 = **1.150 max_tokens de salida** (Haiku, no Expression)

**Nota:** la llamada principal de Expression (Sonnet/Haiku vía model router) no está
incluida en estos conteos — es la llamada que genera la respuesta visible al usuario.

---

## Flujo simplificado (vista de pájaro)

```
user_message ──► [Paso 1-2: Goal maintenance]
                 [Paso 3: Haiku#1 Perception  ] ──► user_intent, tone, context_type
                 [Paso 4-5: Haiku#2 Appraisal ] ──► deltas emocionales, goal_updates, surprise
                 [Paso 6-9: Persist deltas    ] ──► MentalState, SocialProfile, Goals DB
                 [Paso 10:  Salience (Python) ] ──► compuerta dual (0.25 / 0.45)
                 [Paso 11:  Haiku#3 Episode   ] (si ≥0.25) ──► Episode DB
                 [Paso 12:  Haiku#4+#5 Decision] ──► 4 passes → acción elegida
                 [Paso 13a: SemanticFacts DB   ] ──► contexto para Reflection
                 [Paso 13b: Haiku#6 Reflection ] (si ≥0.45) ──► SelfBelief, BeliefAttribution
                 [Paso 14:  CognitionTurnResult] ──► devuelve al turn_runner
                 [Paso 15:  ProceduralObs     ] ──► daemon thread si umbral
                       │
                       ▼
              [Expression: persona_prompt + ACCIÓN DECIDIDA]
                       │
                       ▼
              [Main LLM (Sonnet/Haiku)] ──► respuesta al usuario
                       │
                       ▼
              [social/update.py daemon] ──► Snapshot + SocialReflection + Narrative + SemanticFact
```

---

## Referencias a documentos de fase

| Fase | Documento                                          | Contenido                                           |
|------|----------------------------------------------------|-----------------------------------------------------|
| 1    | docs/remake/fase-1-personalidad.md                 | 13 rasgos, MentalState, CommunicationPreferences    |
| 2    | docs/remake/fase-2-appraisal-goals.md              | Perception, Appraisal, Goal+Milestone, goal_urgent  |
| 3    | docs/remake/fase-3-relacion-multidimensional.md    | SocialProfile 11 dimensiones                        |
| 4    | docs/remake/fase-4-memoria-episodica-autobiografica.md | Episode, salience, AutobiographicalNarrative    |
| 5    | docs/remake/fase-5-decision-expression.md          | Decision fórmula U(a), 10 acciones, Expression      |
| 6    | docs/remake/fase-6-selfmodel-valores-metacognicion.md | SelfModel, SityValues, Reflection               |
| 7    | docs/remake/fase-7-memoria-procedimental.md        | ProceduralObservation, ProceduralPattern            |
| 8    | docs/remake/fase-8-usermodel-teoria-mente-expectativas.md | UserKnowledge, BeliefAttribution, Expectation |
| 9    | docs/remake/fase-9-consolidacion-semantica.md      | SemanticFact, consolidación, Reflection integration |

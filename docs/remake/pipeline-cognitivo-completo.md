# Pipeline Cognitivo Completo — Mapa Maestro

**Fecha:** 2026-10-01 (post-Operación Remake Fases 1–9 + MINI-REMAKE v2.0 Puntos 1–7 + calidad: semantic resolution + RelationshipEvidence dedup; suite 3537 tests)

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

### Paso 3b — Retrieval episódico (puro DB)
`retrieve_relevant_episodes(session, user_id, current_topics, context_type, limit=3)`
Rankea episodios previos usando `RecallScore = Similarity × Salience × Strength × RecencyBoost × ContextRelevance`.
Carga top-50 por `occurred_at DESC`, rankea y devuelve top-3 con score ≥ 0.60.
Los episodios recuperados se pasan a Decision (Paso 12) para enriquecer el contexto Haiku.
Almacenados en `CognitionTurnResult.recalled_episodes`. Sin Haiku.
→ _Diseño: docs/remake/fase-4-memoria-episodica-autobiografica.md_

---

### Paso 3c — Evaluación de Expectativas pendientes (puro DB + Python)
`evaluate_pending_expectations(session, user_id, perception, current_turn_id)`
Compara la `Expectation` activa más reciente del usuario con las señales de Perception actuales.
Produce `ExpectationEvalResult` con dos efectos downstream:
1. `prediction_errors` → `apply_prediction_error_to_trust(sp_row, ...)` en Paso 8 (nudge en `trust_reliability`)
2. `max_surprise` → boost de `_effective_salience` en Paso 10 si `max_surprise > 0.30`

Sin Haiku. Se ejecuta antes de Appraisal para que la señal de prediction_error esté disponible.
→ _Diseño: docs/remake/fase-8-usermodel-teoria-mente-expectativas.md_

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

Para cada dimensión con `|Δ| ≥ 1e-9`, escribe una fila `RelationshipEvidence(source="appraisal",
applied=True, turn_id=trace_id)`. Esto permite a `apply_reflection_relationship_evidence()`
(Paso 13c) saber qué dimensiones ya fueron actualizadas por Appraisal y evitar doble conteo.

Si `_exp_eval.prediction_errors` existe (Paso 3c):
`apply_prediction_error_to_trust(sp_row, prediction_errors)` — nudge adicional en `trust_reliability`.
→ _Diseño: docs/remake/fase-3-relacion-multidimensional.md, docs/remake/fase-8-usermodel-teoria-mente-expectativas.md_

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

**`_effective_salience`:** si `_exp_eval.max_surprise > 0.30` (Paso 3c):
`_effective_salience = min(1.0, salience.total + max_surprise × 0.10)`
En ausencia de prediction error de alta sorpresa, `_effective_salience == salience.total`.

Este valor `_effective_salience` actúa como **compuerta dual**:
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
- `get_relevant_self_beliefs(session, user_id, context_type, min_confidence=0.60)` → `SelfBelief` activas
- `recalled_episodes` ya disponible desde Paso 3b

**`compute_utility_scores()` — 4 passes independientes (puro Python):**

| Pass | Fuente                  | Señales                                     |
|------|-------------------------|---------------------------------------------|
| 1    | Base                    | 22 señales × 10 acciones (fórmula U(a))     |
| 2    | SityValues              | `_VALUES_MATRIX` — 5 valores × 10 acciones  |
| 3    | ProceduralPatterns      | `_PROCEDURAL_ACTION_HINTS` — 8 context_types, guard `confidence ≥ 0.55` |
| 4    | Expectations            | `_EXPECTATION_ACTION_MAP` — guard `probability ≥ 0.60` |

**Pass 5 — SelfModel metacognitive (después de `compute_utility_scores()`, antes de Haiku #4):**
`compute_metacognitive_adjustments(self_beliefs, context_type, perception, mental_state)` — Haiku
evalúa si las self-beliefs activas aplican al contexto y propone ajustes; fórmula de bounds:
`modifier = proposed × max_conf × 0.05 × weight` (weight=1.5 si `max_conf ≥ 0.80`).
Returns `{}` en cualquier error. No opera en initiative mode.

→ Haiku #4 selecciona 1 de 10 acciones: `answer`, `help`, `ask`, `challenge`, `refuse`,
`set_boundary`, `use_tool`, `wait`, `initiate`, `change_topic`.

→ Haiku #5 verifica coherencia: rechaza si la acción es manifiestamente incoherente.
En initiative mode (user_message=None), Haiku #5 se omite — solo acciones `initiate`/`wait`.

Resultado: `DecisionResult(action, python_scores, reasoning)` | `None`.

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
max_tokens:  600
Condición:   _effective_salience ≥ 0.45
```
10 preguntas introspectivas retrospectivas (sobre el turno actual + sesión).
Recibe SemanticFacts como sección "KNOWN USER FACTS" — **zero coste marginal**
(inyectado en el contexto Haiku ya existente).

Outputs persistidos en DB:
- `ReflectionLog` — registro completo del turno
- `SelfBelief` candidatas vía `belief_updates`: cada proposición pasa por `resolve_candidate()`
  (Haiku semántico, fast-paths: vacío→NEW sin Haiku, exact-match→MATCH conf=1.0 sin Haiku).
  MATCH → `reinforce_belief()` (fórmula: `conf + (1−conf)×0.20`);
  CONTRADICT → `contradict_belief()` (`conf − conf×0.15`);
  NEW/RELATED → insert con `confidence=0.40, source="metacognition"`, opcional `related_belief_id`.
  **Nunca auto-hechos.**
- `BeliefAttribution` updates vía `user_belief_updates` (`confidence=0.35, source="reflection"`) — ToM del usuario
- `SemanticFact` candidatas vía `memory_candidates_typed`: igual que SelfBelief, cada proposición
  pasa por `resolve_candidate()`. MATCH → `reinforce_fact()`, CONTRADICT → `contradict_fact()`,
  NEW → `upsert_semantic_candidate()` (candidate=True, conf ≤ 0.45).
  Tras el loop: `maybe_trigger_volume_consolidation()` si ≥10 candidatos activos (daemon thread).
- `RelationshipEvidence` rows vía `relationship_evidence_structured` (applied=False, escala 0.015)
- `GoalCandidate` (pending) o `Goal` directo vía `goal_updates_structured` (directo solo si explicit + conf ≥ 0.70)
- `SelfBelief` refuerzo vía `self_model_updates` → `add_self_model_observation()` (conf=0.30)

→ _Diseño: docs/remake/fase-6-selfmodel-valores-metacognicion.md §Paso 3,
  docs/remake/fase-8-usermodel-teoria-mente-expectativas.md §Paso 2,
  docs/remake/fase-9-consolidacion-semantica.md §Paso 3_

---

### Paso 13c — Aplica RelationshipEvidence al SocialProfile (puro DB, condicional)
`apply_reflection_relationship_evidence(session, user_id, trace_id)`
Ejecutado solo cuando `reflection_result is not None`.
Carga las filas `RelationshipEvidence(source="reflection", applied=False)` para este `trace_id`.
Para cada fila: comprueba si Appraisal ya escribió una fila para `(turn_id, dimension)` con
`source="appraisal"`. Si existe → marca `applied=False` y omite el delta (Appraisal domina).
Si no existe → aplica `sign × strength × 0.015` sobre la dimensión de `SocialProfile` y
marca `applied=True`. Índice compuesto `idx_re_user_turn_dim (user_id, turn_id, dimension)`
garantiza la consulta de dedup en O(log n).
Sin Haiku.

---

### Paso 14 — Retorno de CognitionTurnResult
```python
CognitionTurnResult(perception, appraisal, active_goals, decision, reflection, recalled_episodes)
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

Si `decision is None` (fallback técnico): el turno continúa sin instrucción de acción — el modelo
principal responde normalmente. No existe "sistema antiguo"; el rechazo (`refuse`) solo llega
vía `decision.action == "refuse"` (Punto 2 Mini-Remake v2.0).

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

### D. SemanticFact consolidation (por episodios)
```
Disparado:   inline en _run_social_update(), después de _maybe_generate_narrative()
Haiku:       max_tokens=400  (si ≥3 Episodes sin semantically_processed)
Módulo:      app/cognition/semantic_service.py → maybe_trigger_semantic_consolidation()
```
Sintetiza `SemanticFact` (hechos estables sobre el usuario) de batch de episodios.
Anti-duplicación via contexto (no pasada de fusión explícita).

### E. Volume consolidation (SemanticFact/SelfBelief candidatos)
```
Disparado:   al final del loop de memory_candidates en run_reflection(), si ≥10 candidatos activos
Haiku:       max_tokens=300  (por cluster de ≥2 proposiciones con mismo prefijo 3 palabras)
Módulo:      app/cognition/semantic_service.py → maybe_trigger_volume_consolidation()
```
Agrupa candidatos por primeras 3 palabras. Por cada cluster ≥2: Haiku elige la proposición más
precisa y marca el resto `active=False`. Evita explosión de candidatos similares sin fusión semántica.

---

## Resumen de llamadas Haiku por turno

| # | Módulo           | Condición                  | max_tokens | Función                              |
|---|------------------|----------------------------|------------|--------------------------------------|
| 1 | perception       | siempre                    | 110        | Clasificar turno en 6 dimensiones    |
| 2 | appraisal        | siempre                    | 350        | Evaluar impacto en estado+metas      |
| 3 | episode          | _effective_salience ≥ 0.25 | 150        | Crear memoria episódica              |
| 4 | decision         | siempre¹                   | 120        | Seleccionar acción entre 10          |
| 4b| metacognitive    | si self-beliefs activas¹   | 120        | Ajustar scores con self-beliefs      |
| 5 | coherence        | siempre¹                   | 40         | Verificar coherencia de acción       |
| 6 | reflection       | _effective_salience ≥ 0.45 | 600        | Revisión introspectiva del turno     |
| 6b| semantic_resolver| por candidato no trivial²  | 80         | Dedup semántico SelfBelief/Fact      |

¹ Haiku #4, #4b y #5 se saltan únicamente en caso de error técnico en la orquestación de Decision.
  Haiku #4b (metacognitive) solo se llama cuando hay `SelfBelief` activas con confidence ≥ 0.60.
² Haiku #6b se llama UNA vez por candidato no trivial dentro de Reflection (fast-path si lista vacía
  o exact-match). En la práctica 0–5 llamadas por turno cuando Reflection se activa.

**Por turno normal (sin errores técnicos, sin self-beliefs):**
- **Mínimo: 4 llamadas Haiku** — cuando _effective_salience < 0.25 (ni Episode ni Reflection)
- **Máximo: 6+ llamadas Haiku** — cuando _effective_salience ≥ 0.45 + self-beliefs activas + candidatos semánticos

**Budget de tokens por turno (máximo sin resolver, solo Haiku de cognición):**
110 + 350 + 150 + 120 + 120 + 40 + 600 = **1.490 max_tokens de salida** (Haiku, no Expression)

**Nota:** la llamada principal de Expression (Sonnet/Haiku vía model router) no está
incluida en estos conteos — es la llamada que genera la respuesta visible al usuario.

---

## Flujo simplificado (vista de pájaro)

```
user_message ──► [Paso 1-2: Goal maintenance]
                 [Paso 3:   Haiku#1 Perception   ] ──► user_intent, tone, context_type
                 [Paso 3b:  Episode retrieval DB  ] ──► recalled_episodes (top-3)
                 [Paso 3c:  ExpectationEval DB    ] ──► prediction_errors, max_surprise
                 [Paso 4-5: Haiku#2 Appraisal    ] ──► deltas emocionales, goal_updates, surprise
                 [Paso 6-9: Persist deltas        ] ──► MentalState, SocialProfile+trust_reliability, Goals DB
                 [Paso 10:  Salience (Python)     ] ──► _effective_salience (boost si max_surprise>0.30)
                 [Paso 11:  Haiku#3 Episode       ] (si ≥0.25) ──► Episode DB
                 [Paso 12:  Haiku#4b+#4+#5 Decision] ──► 4 passes + metacognitive Pass 5 → acción elegida
                 [Paso 13a: SemanticFacts DB       ] ──► contexto para Reflection
                 [Paso 13b: Haiku#6 Reflection     ] (si ≥0.45) ──► ReflectionLog, SelfBelief, BeliefAttribution,
                                                                      SemanticFact candidates, RelationshipEvidence,
                                                                      GoalCandidate/Goal, add_self_model_observation
                 [Paso 13c: RelationshipEvidence   ] ──► apply_reflection_relationship_evidence()
                 [Paso 14:  CognitionTurnResult    ] ──► devuelve al turn_runner
                 [Paso 15:  ProceduralObs          ] ──► daemon thread si umbral
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

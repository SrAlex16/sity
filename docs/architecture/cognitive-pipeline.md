# Cognitive Pipeline / Pipeline Cognitivo

[English](#english) · [Español](#español)

---

## English

### Overview

The cognitive pipeline is the core of what makes Sity more than a chatbot. It runs on every authenticated `user:` turn before the main Claude response, executing up to 6 Haiku calls to classify, appraise, decide, and reflect on the interaction. Guest sessions skip the pipeline entirely.

Entry point: `run_cognition_turn()` in `turn_cognition.py`, called from `turn_runner.py`.

### Full pipeline (15 steps)

```
Turn received
     │
     ├─ 1. Goal maintenance (no LLM)
     │      Close short-term goals older than 24h
     │      Load active goals and milestones
     │
     ├─ 2. Perception (Haiku #1, always)
     │      Classify: intent · tone · challenge · social_signal · novelty · context_type
     │      Fallback: neutral result on error
     │
     ├─ 3. Episodic retrieval + expectation check (no LLM)
     │      Retrieve top-3 relevant episodes (ranked by similarity × salience × strength × recency × context)
     │      Compare against active Expectation → compute prediction_error and surprise
     │
     ├─ 4. Appraisal (Haiku #2, always)
     │      Estimate: emotional deltas · trust evidence · goal changes · surprise · explicit_importance
     │      Fallback: zero result on error
     │
     ├─ 5. State updates (no LLM)
     │      Write deltas to MentalState (11 dimensions)
     │      Update SocialProfile (11 dimensions) via per-turn apply_appraisal_to_social_profile
     │      Update Goals: create / progress / resolve
     │      Prediction errors nudge trust in reliability
     │
     ├─ 6. Salience (Python, deterministic)
     │      Weighted score over 7 components
     │      Surprise can boost it
     │      Thresholds: 0.25 → episode creation; 0.45 → Reflection; 0.55 → procedural influence
     │
     ├─ 7. Episode creation (Haiku #3, if salience ≥ 0.25)
     │      Summarize turn as Episode with strength ∝ salience
     │      muy_alta episodes (salience ≥ 0.70) → candidate for autobiographical narrative
     │
     ├─ 8–10. Decision (Haiku #4, #4b, #5)
     │      #4: Compute utility scores for 10 actions (Python formula + values matrix + procedural hints)
     │      #4b: Haiku selects or overrides action
     │      #5: Coherence check (Python floor at 0.30 + Haiku validation)
     │      Metacognitive pass: SelfBeliefs nudge scores (bounded, confidence ≥ 0.55, hard cap)
     │      Fallback: None → main model decides freely
     │
     ├─ 11. Reflection (Haiku #6, if salience ≥ 0.45)
     │      9 introspective questions
     │      Outputs: SelfBelief candidates · BeliefAttribution · SemanticFact candidates · relationship evidence · goal updates
     │      New beliefs start at confidence 0.40 (source: "metacognition")
     │      Semantic deduplication calls (Haiku #6b) per non-trivial candidate
     │
     ├─ 12. Relationship evidence (no LLM)
     │      Apply reflection-sourced relationship changes
     │      Skip dimensions Appraisal already updated this turn
     │
     ├─ 13. Expectation resolution (no LLM)
     │      Update Expectation states: pending → confirmed / violated / expired_unknown
     │      Absence of mention ≠ violation (expired_unknown ≠ violated)
     │
     ├─ 14. Memory Worthiness (Python, per semantic proposition)
     │      Independent of salience; runs on propositions extracted from Reflection
     │      MW score = f(temporal_scope, behavioral_relevance, personal_relevance, assertion_strength, context_dependency)
     │      Gate: MW ≥ 0.40 → consolidate via Semantic Resolver
     │      Resolver paths: NEW · MATCH (reinforce) · RELATED (link) · CONTRADICT (revise via evidence trail)
     │
     └─ 15. Procedural observation (no LLM, fire-and-forget)
            Log observation for this (user, context_type)
            After 3 unprocessed observations: background pattern synthesis via Haiku
```

### Decision action space

The Decision module selects one of 10 actions per turn:

| Action | Description |
|---|---|
| `answer` | Standard conversational reply |
| `help` | Task-oriented assistance |
| `ask` | Request clarification or more information |
| `challenge` | Push back on a claim or assumption |
| `refuse` | Decline the request (per-turn layer, not structural) |
| `set_boundary` | Express a personal limit |
| `use_tool` | Invoke an integration |
| `wait` | Converted to `answer` in practice |
| `initiate` | Start a new conversational thread |
| `change_topic` | Redirect the conversation |

Utility scores are computed by a Python formula over 22 signals across 5 categories (personality, emotional state, relationship, perception, goals), then optionally adjusted by values matrix and procedural hints. Haiku validates the top choice. Any failure returns `None` and the main model decides freely.

### Haiku budget (typical turn)

| Condition | Calls |
|---|---|
| Minimum (low salience) | 4 (Perception + Appraisal + Decision × 2) |
| With episode creation (salience ≥ 0.25) | 5 |
| With Reflection (salience ≥ 0.45) | 6 |
| With semantic deduplication | 6+ |

Max output budget for core calls: ~1,490 tokens.

### Background daemons (outside the turn)

These run asynchronously and never block the turn:

- **Pattern synthesis**: synthesizes `ProceduralPattern` after 3 unprocessed observations
- **Social snapshots**: periodic snapshots of the relationship state
- **Social reflection**: writes narrative reflection when signal is sufficient (≥20 new messages or opinion delta ≥0.15)
- **Autobiographical narrative**: composes identity narrative from `muy_alta` episodes (≥3 episodes, ≥7 days between narratives)
- **Semantic consolidation**: extracts `SemanticFact` from episodic memory batches (≥3 unprocessed episodes)
- **Semantic volume consolidation**: consolidates candidate facts and beliefs in bulk

---

## Español

### Visión general

El pipeline cognitivo es el núcleo de lo que diferencia a Sity de un chatbot estándar. Corre en cada turno de sesiones `user:` autenticadas antes de la respuesta principal de Claude, ejecutando hasta 6 llamadas a Haiku para clasificar, valorar, decidir y reflexionar sobre la interacción. Las sesiones de tipo guest saltan el pipeline completamente.

Punto de entrada: `run_cognition_turn()` en `turn_cognition.py`, llamado desde `turn_runner.py`.

### Los 10 actions del módulo Decision

El módulo Decision selecciona una de 10 acciones posibles por turno (ver tabla en inglés arriba). Los scores de utilidad se calculan en Python a partir de 22 señales en 5 categorías, con ajustes opcionales de la matriz de valores y los hints procedurales. Haiku valida la elección. Cualquier fallo devuelve `None` y el modelo principal decide libremente.

### Presupuesto Haiku (turno típico)

| Condición | Llamadas |
|---|---|
| Mínimo (salience baja) | 4 |
| Con creación de episodio (salience ≥ 0.25) | 5 |
| Con Reflection (salience ≥ 0.45) | 6 |
| Con deduplicación semántica | 6+ |

### Memory Worthiness (MW)

La MW es una propiedad de cada proposición semántica, independiente de la salience del evento. Una conversación puede tener salience baja (sin episodio) pero contener proposiciones con MW alta (p.ej. "odio el café"). La fórmula:

```
MW = w_duration × expected_duration
   + w_behavioral × behavioral_relevance  
   + w_personal × personal_relevance
   + w_assertion × assertion_strength
   - penalty_context × context_dependency

Gate: MW ≥ 0.40 → consolidar vía Semantic Resolver
```

El Resolver tiene cuatro paths: NEW (crear), MATCH (reforzar), RELATED (enlazar), CONTRADICT (revisar vía evidence trail sin sobrescribir).

### Daemons en background

Corren de forma asíncrona y nunca bloquean el turno:

- **Síntesis de patrones**: `ProceduralPattern` tras 3 observaciones sin procesar
- **Snapshots sociales**: instantáneas periódicas del estado de la relación
- **Reflexión social narrativa**: escribe reflexión narrativa (≥20 mensajes nuevos o delta opinion ≥0.15)
- **Narrativa autobiográfica**: desde episodios `muy_alta` (≥3 episodios, ≥7 días entre narrativas)
- **Consolidación semántica**: extrae `SemanticFact` de batches episódicos (≥3 episodios sin procesar)

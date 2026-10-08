# Decision-Making & Initiative / Toma de Decisiones e Iniciativa

[English](#english) · [Español](#español)

---

## English

### Decision module

The Decision module gives Sity an explicit action policy for each turn. Instead of the main model choosing freely, Decision preselects one of 10 actions using a deterministic utility formula, then validates through Haiku. The chosen action is injected as an instruction into the persona prompt before the main model call.

#### Utility formula

```
score(action) = baseline(action) + Σ weight_i × signal_i

Signals across 5 categories (22 total):
  personality:     warmth, empathy, directness, assertiveness, independence,
                   skepticism, helpfulness, playfulness, emotional_stability
  emotional state: interest, frustration, social_comfort, melancholy
  relationship:    affinity, conflict, familiarity, average_trust
  perception:      social_signal, challenge, novelty, intent_request
  goals:           active_goal_urgency

Contextual bonuses:
  intent_request → boost `help`, reduce `answer`
  domain_activated → boost `use_tool` (absence penalizes it)
```

Score clamped to [0, 1] for each action.

#### Decision pipeline

```
1. Python utility scores (22 signals)
       ↓
2. Values matrix adjustment (independent pass, Phase 6)
       ↓
3. Procedural hints adjustment (confidence ≥ 0.55 required, Phase 7)
       ↓
4. Metacognitive adjustment from SelfBeliefs (bounded, Phase 6)
       ↓
5. Haiku #4b — selects or overrides action, with context
       ↓
6. Coherence check:
   a. Python floor: if score < 0.30 → fallback
   b. Haiku #5 validation
       ↓
7. DecisionResult returned
   (None on any failure → main model decides freely)
```

#### Expression

The selected action is added to `persona_prompt` after the goals block in `turn_runner.py`. `wait` is converted to `answer` in practice. The `refuse` action acts as a per-turn layer, separate from `refusal_mode` which is a structural setting.

### Appraisal

Appraisal (Haiku #2) runs every turn and estimates:
- Emotional deltas (interest, frustration, social_comfort)
- Trust evidence (how reliable was this interaction?)
- Goal changes (create / update / resolve)
- Surprise level
- Explicit_importance (user-stated importance, boosts salience)

Appraisal outputs feed directly into state updates and social profile adjustments.

### Goals

Goals are persistent per-user targets with a status lifecycle:

```
active → resolved (completed)
       → abandoned (on logout: short-term goals are abandoned)
       → expired (24h safety net for short-term goals)
```

Goals never return to `active` once resolved or abandoned.

**Milestones**: Incremental progress markers within a goal. Effective priority blends base importance with current turn's relevance, reduced by irony. Wellbeing goals are exempt from irony reduction (regression test covers this).

**Appraisal instruction**: Prefer adding milestones to similar existing goals rather than creating duplicates.

Active long-term goals feed into the initiative evaluator. Short-term goals feed into expression.

### Expectations

**Purpose**: Forward-looking predictions of user behavior per `context_type`. Influence Decision action scores when active.

**States**: `pending` → `confirmed` / `violated` / `expired_unknown`

Key invariant: absence of mention is never treated as violation. `expired_unknown ≠ violated`. Probability and importance are separate dimensions.

**Decision integration**: An active expectation adjusts action scores by `delta × probability`. Expectations below 0.60 probability are ignored.

**Prediction error**: Computed as `-log₂(P)`. Currently reserved for future calibration work; distinct from the holistic `surprise` signal.

### Proactive Initiative

Sity can initiate contact without being prompted. The system has three trigger types:

| Trigger | Description |
|---|---|
| `conversation_abandoned` | User stopped mid-task |
| `long_inactivity` | Extended silence |
| `open_loop` | User mentioned intention, never followed up |

**Decision flow**:
```
1. Deterministic gate (always runs):
   - 4-hour silence window
   - Trust ≥ 0.30 (familiarity dimension)
   - Rate limits (per user)
   - Per-session toggle
     ↓ (only if gate passes)
2. Haiku judgment: genuine reason to write?
     ↓ (only if approved)
3. Deliver via notification dispatcher (low-urgency)
```

**Adaptive runner** (since 2026-09-28): Replaced fixed 6-hour intervals. Haiku decides when to check next. Urgent goals (base importance ≥ 0.75) can wake the runner early. Soft rule: avoid contact during late-night hours unless a wellbeing goal is very urgent.

**Open-loop detection**: Runs per user turn as fire-and-forget (no chat latency). Passes only user messages to Haiku to avoid self-referential bias. Cap: 20 evaluation attempts per loop before giving up.

Guest sessions are excluded from all initiative behavior.

---

## Español

### Módulo Decision

El módulo Decision da a Sity una política de acción explícita por turno. En lugar de que el modelo principal decida libremente, Decision preselecciona una de 10 acciones usando una fórmula de utilidad determinista, luego valida con Haiku. La acción elegida se inyecta como instrucción en el prompt de persona antes de la llamada principal.

#### Fórmula de utilidad

```
score(acción) = baseline(acción) + Σ peso_i × señal_i
```

22 señales en 5 categorías: personalidad, estado emocional, relación, percepción, goals. Ver sección en inglés para la lista completa.

#### Pipeline de Decision

Ver diagrama en la sección en inglés.

### Goals (Objetivos)

Los goals son objetivos persistentes por usuario con un ciclo de vida:

```
active → resolved (completado)
       → abandoned (al cerrar sesión: goals a corto plazo se abandonan)
       → expired (24h de seguridad para goals a corto plazo)
```

Los goals nunca vuelven a `active` una vez resueltos o abandonados.

Los goals a largo plazo con importancia base ≥ 0.75 pueden despertar al runner de iniciativa anticipadamente. Los goals de bienestar están exentos de la penalización por ironía (cubierto por test de regresión).

### Expectativas

**Invariante clave**: La ausencia de mención nunca se trata como violación. `expired_unknown ≠ violated`. Las expectativas con probabilidad < 0.60 se ignoran en Decision.

### Iniciativa propia

Sity puede iniciar contacto sin ser invocada. Tres tipos de trigger: `conversation_abandoned`, `long_inactivity`, `open_loop`.

**Flujo de decisión**: Primero pasa un gate determinista (ventana de 4h de silencio, confianza ≥ 0.30, límites de frecuencia, toggle por sesión). Solo si el gate pasa, Haiku juzga si hay razón genuina.

**Runner adaptativo** (desde 2026-09-28): Haiku decide cuándo hacer el siguiente check. Los goals urgentes pueden despertar el runner anticipadamente. Regla suave: evitar contacto en horas nocturnas salvo goals de bienestar muy urgentes.

Las sesiones guest están excluidas de toda la iniciativa propia.

**Bugs encontrados en producción** (resueltos):
1. JSON con markdown fence desde Haiku causaba fallos de parsing — el canal open-loop estuvo silenciosamente muerto hasta el fix
2. Contexto auto-referencial: mensajes anteriores de Sity sobre un tema sesgaban a Haiku hacia "skip" indefinidamente — fix: solo pasar mensajes del usuario, cap de 20 intentos por loop
3. TTS faltaba en mensajes de iniciativa (el runner salteaba la ruta normal de síntesis) — fix en frontend también para recarga de página

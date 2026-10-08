# Memory System / Sistema de Memoria

[English](#english) · [Español](#español)

---

## English

Sity has four distinct memory layers, each serving a different cognitive function. All data lives in SQLite (`data/app.db`) with FTS5 for full-text search. Every query is scoped by `user_id` — one user's memory never affects another's turn.

### Memory layers

```
┌──────────────────────────────────────────────────────┐
│  Working Memory (turn context)                       │
│  Active goals · retrieved episodes · social context  │
│  Active expectations · procedural patterns           │
└──────────────────────────────────────────────────────┘
         ↑ injected into prompts each turn
┌──────────────────────────────────────────────────────┐
│  Episodic Memory                                     │
│  Episode table: summarized significant turns          │
│  AutobiographicalNarrative: identity synthesis        │
└──────────────────────────────────────────────────────┘
         ↑ retrieved by similarity + salience ranking
┌──────────────────────────────────────────────────────┐
│  Semantic Memory                                     │
│  SemanticFact: stable propositions about the user    │
│  SelfBelief: Sity's beliefs about itself             │
│  UserKnowledge: estimated user expertise per topic   │
│  BeliefAttribution: what Sity thinks user believes   │
└──────────────────────────────────────────────────────┘
         ↑ consolidated from episodic via background daemons
┌──────────────────────────────────────────────────────┐
│  Procedural Memory                                   │
│  ProceduralObservation: per-turn interaction log     │
│  ProceduralPattern: synthesized interaction patterns │
└──────────────────────────────────────────────────────┘
```

### Episodic memory

**Purpose**: Remember significant events and build identity over time.

**Creation**: Every turn with salience ≥ 0.25 triggers a Haiku call to summarize the episode.

| Salience range | Level | Episode strength | Autobiographical candidate |
|---|---|---|---|
| < 0.25 | None | No episode created | No |
| 0.25 – 0.45 | Media | 0.50 | No |
| 0.45 – 0.70 | Alta | 1.00 | No |
| ≥ 0.70 | Muy alta | 1.00 | Yes |

**Retrieval ranking**: `score = α·similarity + β·salience + γ·strength + δ·recency + ε·context_match`

Top 3 episodes are injected into each turn's context. Old memories become less accessible rather than deleted.

**Autobiographical narrative**: When ≥3 `muy_alta` episodes accumulate (minimum 7 days between narratives), a background job synthesizes a 2-4 sentence identity narrative. This narrative is injected into the prompt as Sity's sense of self over time.

### Semantic memory

**Purpose**: Stable, generalized knowledge about the user — extracted from episodic patterns.

**`SemanticFact`**: A proposition about the user (e.g. "prefers direct communication", "studies computer engineering"). 

- Confidence starts at 0.40 when first extracted
- Reinforcement: +0.05, capped at 0.85
- Contradiction: −0.10 via evidence trail recalculation (never direct overwrite)
- Contradictions weigh twice as much as reinforcements
- Facts below 0.20 confidence are deactivated

**Memory Worthiness gate**: A proposition must score MW ≥ 0.40 to enter the Semantic Resolver. The score weights expected duration, behavioral relevance, personal relevance, and assertion strength, penalized by context dependency. This means low-salience turns can still produce lasting memory (e.g. "I hate coffee" → low salience, high MW).

**Semantic Resolver paths**:
- `NEW`: full Haiku evaluation, then create
- `MATCH`: reinforce existing evidence (no extra LLM call)
- `RELATED`: create link when relation confidence is sufficient
- `CONTRADICT`: revise via evidence trail, never overwrite

**Local embeddings decision**: Rejected for Pi 4B (`all-MiniLM-L6-v2` took 26s to load, 857ms/item, 880MB RAM). During beta, all candidates go to Haiku directly. Future: Anthropic embeddings API for users with >100 entries. See [decisions/0004-embeddings.md](../decisions/0004-embeddings.md).

**`SelfBelief`**: Sity's beliefs about its own capabilities, preferences, and limitations.
- Starting confidence: 0.40 (source: "metacognition")
- Requires explicit promotion to rise above baseline
- Can nudge Decision scores only through bounded metacognitive adjustments (confidence ≥ 0.55, hard cap)

**`UserKnowledge`**: Estimated expertise level per topic.
- Confidence capped at 0.80 (indirect observation is never fully certain)

**`BeliefAttribution`**: What Sity thinks the user believes.
- Starting confidence: 0.35
- Confidence capped at 0.65
- Kept separate from `SelfBelief` (different foreign key, opposite semantics, different query patterns)

### Procedural memory

**Purpose**: Recognize how the user typically interacts per context type, and adjust action scores accordingly.

**`ProceduralObservation`**: Lightweight per-turn record (user, context_type, 100-char excerpt, processed flag).

**`ProceduralPattern`**: Synthesized by Haiku when ≥3 unprocessed observations accumulate for the same (user, context_type).

**Confidence formula**: `min(0.85, 0.45 + max(0, occurrence_count - 3) × 0.04)`

New patterns start at 0.45, below the 0.55 influence threshold. A pattern must accumulate ~6 occurrences before it can influence Decision — preventing weak evidence from changing behavior.

**Context types**: `debugging` · `implementation` · `casual_chat` · `emotional_support` · `learning` · `planning` · `creative` · `other`

### Social memory

**Purpose**: Build a relationship model that shapes Sity's tone and openness without exposing scores to the user.

**`SocialProfile`** (11 dimensions, all [0,1]):
- `affinity` · `conflict` · `trust_reliability` · `trust_emotional` · `familiarity` · `attachment` · `gratitude` · `admiration` · `dependency` · `resentment` · `social_comfort`

Dimensions are updated per turn from Appraisal signals, scaled by Sity's personality traits. Personality traits are never copied into the relationship state.

**`SocialReflection`**: A narrative description (2-4 sentences) generated by Haiku when signal is sufficient. Injected into the prompt as "pattern observed." Expires after 30 days. No numeric values in the narrative text.

**Third-party recall** (`social_recall_impression` tool): Returns qualitative labels (not numeric values, message content, or dates) about another user. Disclosure level depends on the product of both users' average trust:
- Low trust product → minimal disclosure
- Medium → qualitative description
- High → fuller picture

Guest sessions never receive a social profile.

---

## Español

Sity tiene cuatro capas de memoria distintas, cada una con una función cognitiva diferente. Todos los datos viven en SQLite (`data/app.db`) con FTS5. Cada consulta está filtrada por `user_id` — la memoria de un usuario nunca afecta el turno de otro.

### Capas de memoria

Ver diagrama en la sección en inglés.

### Memoria episódica

**Propósito**: Recordar eventos significativos y construir identidad a lo largo del tiempo.

**Creación**: Cualquier turno con salience ≥ 0.25 dispara una llamada a Haiku para resumir el episodio (ver tabla de niveles arriba).

**Ranking de recuperación**: Los 3 episodios más relevantes se inyectan en el contexto de cada turno. Los recuerdos antiguos se vuelven menos accesibles, no se eliminan.

**Narrativa autobiográfica**: Cuando se acumulan ≥3 episodios `muy_alta` (mínimo 7 días entre narrativas), un job en background sintetiza una narrativa de identidad de 2-4 frases.

### Memoria semántica

**Propósito**: Conocimiento estable y generalizado sobre el usuario — extraído de patrones episódicos.

**Gate de Memory Worthiness**: Una proposición necesita MW ≥ 0.40 para entrar al Semantic Resolver. El score pondera duración esperada, relevancia conductual, relevancia personal y fuerza de la aserción, penalizado por dependencia de contexto. Esto permite que turnos de baja salience produzcan memoria duradera (ej. "odio el café" → salience baja, MW alta).

**Paths del Semantic Resolver**:
- `NEW`: evaluación completa con Haiku, luego crear
- `MATCH`: reforzar evidencia existente (sin llamada adicional al LLM)
- `RELATED`: crear enlace cuando la confianza de relación es suficiente
- `CONTRADICT`: revisar vía evidence trail, nunca sobreescribir

**Decisión sobre embeddings locales**: Rechazados para Pi 4B (26s de carga, 857ms/item, 880MB RAM). Durante beta, todos los candidatos van directamente a Haiku. Futuro: API de embeddings de Anthropic para usuarios con >100 entradas. Ver [decisions/0004-embeddings.md](../decisions/0004-embeddings.md).

### Memoria procedimental

**Propósito**: Reconocer cómo interactúa típicamente el usuario por tipo de contexto y ajustar los scores de acción.

**Umbral de influencia**: Los patrones necesitan confianza ≥ 0.55 para influir en Decision. Los patrones nuevos empiezan en 0.45 y necesitan ~6 ocurrencias para alcanzar el umbral.

### Memoria social

**Propósito**: Construir un modelo de la relación que moldee el tono y la apertura de Sity sin exponer los scores al usuario.

**SocialProfile** (11 dimensiones, todas [0,1]): affinity · conflict · trust_reliability · trust_emotional · familiarity · attachment · gratitude · admiration · dependency · resentment · social_comfort.

Las sesiones de tipo guest nunca tienen perfil social.

# Fase 9 — Consolidación Semántica

**Estado:** Pasos 1–4 completos (2026-09-12)  
**Tests nuevos:** 39 (29 test_semantic_service.py + 10 test_reflection_semantic_context.py)

---

## Objetivos

Dotar a Sity de una capa de conocimiento semántico estable sobre el usuario, extraída
inductivamente de la memoria episódica. Complementa:

- **Fase 4** (Episodic Memory) — episodios individuales, alta resolución, perecederos
- **Fase 7** (ProceduralPattern) — patrones de comportamiento por `context_type`
- **Fase 8** (UserKnowledge/BeliefAttribution) — estimaciones y ToM derivadas de conversación
- **Fase 9** (SemanticFact) — **hechos estables sobre el usuario**, sintetizados de múltiples episodios

---

## Decisiones de diseño confirmadas (no reabrir)

| Decisión | Valor |
|---|---|
| Job location | Background job DENTRO de `social/update.py` — sin daemon thread adicional |
| Revisión-a-la-baja | Desde el inicio — confidence puede bajar, no solo crecer |
| Fusión de proposiciones | Anti-duplicación via contexto (no pasada explícita de fusión) |
| Alcance Fase 9 | Capa de datos + consolidación + lectura en Reflection. Sin Decision. |
| Cap activos | Sin cap duro — desactivación automática por umbral de confianza |
| `_SEMANTIC_BATCH_MIN` | 3 (coherente con `_PROCEDURAL_THRESHOLD` de Fase 7) |

---

## Paso 1+2 — Modelo de datos + mecanismo de detección + contradicción

### `SemanticFact` en `app/memory/models.py`

```python
class SemanticFact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    proposition: str                                  # max 300 chars (enforced in service)
    confidence: float = Field(default=0.40, ge=0.0, le=1.0)
    source_episode_ids_json: str = Field(default="[]")
    reinforcement_count: int = Field(default=0)
    contradiction_count: int = Field(default=0)
    last_confirmed_at: Optional[datetime] = Field(default=None)
    last_contradicted_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    is_active: bool = Field(default=True)
```

**Sin unique constraint** sobre `proposition` — la Haiku de síntesis maneja
deduplicación via contexto anti-duplicación (pass de facts existentes).

### Campo de control en `Episode`

`semantically_processed: bool = Field(default=False)` añadido a `Episode` via
migración idempotente `_migrate_episode_semantically_processed()` en `db.py`.
Mismo patrón que `ProceduralObservation.processed` (Fase 7).

### `app/cognition/semantic_service.py` — funciones principales

| Función | Descripción |
|---------|-------------|
| `load_active_facts(session, user_id, *, min_confidence=0.0, limit=50)` | Carga SemanticFacts activos, sorted by confidence desc. Isolation invariant. |
| `reinforce_fact(session, fact_id, *, user_id, trace_id="")` | +0.05, cap 0.85, isolation check |
| `contradict_fact(session, fact_id, *, user_id, trace_id="")` | −0.10, floor 0.0, desactiva si < 0.20, isolation check |
| `_run_fact_synthesis(*, user_id, trace_id="")` | Carga batch → Haiku → upsert facts → marca episodios processed |
| `maybe_trigger_semantic_consolidation(*, user_id, trace_id="")` | Count check → delega a `_run_fact_synthesis` inline |

### Fórmula de confianza

```
Inicial:        0.40  (_SEMANTIC_INITIAL_CONFIDENCE)
Refuerzo:       min(0.85, confidence + 0.05)
Contradicción:  max(0.00, confidence − 0.10)
Desactivación:  confidence < 0.20 → is_active = False
```

**Asimetría intencionada**: contradicción pesa el doble que refuerzo.
Con confidence inicial 0.40:
- 9 refuerzos sin contradicción alcanzan el techo (0.85)
- 3 contradicciones consecutivas desactivan el hecho (0.40→0.30→0.20→0.10 < 0.20)

### Prompt de síntesis Haiku (max_tokens=400)

```
SYSTEM: You are Sity's semantic consolidation module. Extract stable facts about
the user from these conversation episodes.
Given the episodes and existing facts (with IDs), return ONLY this JSON:
{"new_facts": [...], "reinforced_ids": [...], "contradicted_ids": [...]}
Rules: stable patterns only (not one-off events); propositions describe the user;
max 5 new_facts; genuinely new (not covered by existing). Output only valid JSON.

USER: Episodes (N unprocessed):
- (id=X) Summary text...

Existing semantic facts:
- (id=Y, conf=0.62) User prefers Python over Ruby
```

### Flujo de síntesis

1. Count `Episode WHERE user_id = X AND semantically_processed = 0`
2. Si count < 3 → skip
3. Load batch (LIMIT 20, ORDER BY occurred_at ASC)
4. Load existing active SemanticFacts (anti-duplicación + refuerzo/contradicción)
5. Llamada Haiku → `_SynthesisResult(new_facts, reinforced_ids, contradicted_ids)`
6. INSERT new_facts con confidence=0.40
7. Reforzar/contradecir facts existentes según sus IDs
8. `UPDATE episode SET semantically_processed = 1` para el batch
9. `session.commit()`

### Invariantes de aislamiento

- `load_active_facts` siempre filtra por `user_id`
- `reinforce_fact` y `contradict_fact` verifican `fact.user_id == user_id` antes de operar
- `_run_fact_synthesis` obtiene facts vía query filtrado por `user_id`; verifica aislamiento antes de actualizar

---

## Paso 3 AMPLIADO — Integración en Reflection Step (solo lectura)

### En `social/update.py`

`maybe_trigger_semantic_consolidation(user_id=user_id, trace_id=trace_id)` se llama
al final de `_run_social_update`, después de `_maybe_generate_narrative`. El social
update job ya corre en daemon thread — no se necesita daemon thread adicional.

Wrapped en try/except que loguea `semantic_consolidation_failed` y continúa.

### En `reflection.py`

`_build_reflection_context()` acepta `semantic_facts: list | None = None`.
Si non-empty, añade sección al contexto enviado a Haiku #5:

```
KNOWN USER FACTS (high-confidence):
- User primarily works with Python
- User prefers explicit error messages over silent failures
- User tends to test edge cases before submitting PRs
```

Selección: top-5 by confidence descending. Sin coste marginal — se inyecta
en el contexto de la llamada Haiku ya existente (sin llamada extra).

`run_reflection()` acepta `semantic_facts: list | None = None`. Default = None → no-op.
Backward compatible: todos los tests de `test_reflection_service.py` pasan sin modificación.

### En `turn_cognition.py`

Antes del bloque de Reflection (Step 13):
```python
_semantic_facts: list = []
try:
    _semantic_facts = load_active_facts(session, user_id)
except Exception:
    _semantic_facts = []
```

Pasa `semantic_facts=_semantic_facts or None` a `run_reflection()`.

---

## Invariantes de diseño

1. **Aislamiento por usuario**: toda query en `SemanticFact` filtra por `user_id`.
   Un hecho de usuario A NUNCA puede aparecer en el turno de usuario B.

2. **Revisión-a-la-baja desde el inicio**: `contradict_fact()` reduce confidence
   en cada llamada. No hay restricción de dirección de cambio.

3. **Cap asimétrico**: refuerzo +0.05, contradicción −0.10. Intencionado.

4. **No afecta Decision**: `SemanticFact` no alimenta `compute_utility_scores()`.
   Integración futura en Decision reservada para fase posterior.

5. **Zero cost marginal en Reflection**: inyección de facts en contexto existente,
   sin llamada Haiku adicional.

6. **Backward compatibility total**: `semantic_facts=None` → no-op en reflection.
   Ningún test de fases anteriores requirió modificación.

7. **Deactivación automática**: facts con confidence < 0.20 son marcados
   `is_active=False`. Sin cap duro de filas activas.

---

## Tests

### `tests/test_semantic_service.py` (29 tests)

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestSemanticFactCRUD` | 7 | CRUD, defaults, load_active_facts (filter, sort, isolation) |
| `TestReinforceFact` | 6 | +0.05, cap 0.85, count, timestamp, isolation, inactive |
| `TestContradictFact` | 7 | −0.10, floor 0.0, count, timestamp, deactivation, isolation, inactive |
| `TestConfidenceFormula` | 3 | Casos concretos: 3 refuerzos, 1 contradicción, 3 contradicciones |
| `TestParseSynthesisResponse` | 4 | JSON parsing, key ausente, JSON inválido, tipos int |
| `TestMaybeTriggerConsolidation` | 2 | Below threshold → Haiku no llamado; at threshold → synthesis triggered |

### `tests/test_reflection_semantic_context.py` (10 tests)

| Clase | Tests | Qué verifica |
|-------|-------|--------------|
| `TestBuildReflectionContext` | 6 | None/[] → sin sección; facts → sección aparece; top-5; sorted; verbatim |
| `TestRunReflectionWithSemanticFacts` | 4 | None/[] backward compat; fact en contexto; result retornado |

**Total Fase 9: 39 tests**

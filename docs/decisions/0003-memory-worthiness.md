# ADR-0003: Memory Worthiness Separate from Salience / Memory Worthiness Independiente de Salience

[English](#english) · [Español](#español)

**Status:** Accepted  
**Date:** 2026-09

---

## English

## Context

The original memory system used salience as the gate for all memory operations: if salience ≥ 0.30, an episode was created and semantic extraction was considered. This created a coupling problem.

**The canonical example**: "I hate coffee" has:
- **Low salience** (routine factual statement, low emotional load, not novel)
- **High memory worthiness** (personal preference, long duration, high behavioral relevance — should shape future behavior)

Under the salience-gated system, this statement would never be stored. The user could repeat it in multiple conversations without Sity ever learning it.

## Decision

Separate **salience** and **memory worthiness** as independent concepts:

- **Salience** = property of the event/turn. Answers: does this deserve immediate cognitive attention? Determines episode creation and Reflection depth.
- **Memory Worthiness (MW)** = property of each semantic proposition. Answers: does this deserve lasting persistence? Determines whether a SemanticFact is consolidated, reinforced, or revised.

Both paths run within the same turn. A turn can have high salience with low-MW propositions, or low salience with high-MW propositions.

**MW formula**:
```
MW = w_duration × expected_duration
   + w_behavioral × behavioral_relevance
   + w_personal × personal_relevance
   + w_assertion × assertion_strength
   - penalty_context × context_dependency

Gate: MW ≥ 0.40 → enter Semantic Resolver
```

Six dimensions assessed per proposition: personal relevance, temporal scope, context dependency, assertion strength, expected duration, behavioral relevance.

## Rationale

**Why separate them?**

Salience measures how much a turn matters right now. MW measures how much a proposition matters long-term. These are orthogonal dimensions. Coupling them produces systematic blind spots (routine high-value facts never stored).

**Why a separate MW formula instead of using the LLM?**

MW must be fast (runs per proposition within the turn), deterministic, and auditable. A formula allows calibration with real usage data. The LLM evaluates candidates that pass the MW gate — not the gate itself.

**Why 0.40 as the gate?**

Initial value chosen as a conservative starting point, to be calibrated with real data. Too low → too much stored (slow semantic deduplication). Too high → misses important facts.

## Consequences

- Each turn can produce multiple propositions, each with its own MW score and memory operation
- Expression may only claim to remember something when `persisted = true` — prevents Sity from promising to remember things it hasn't stored
- The gate threshold (0.40) should be recalibrated after accumulating real usage data
- MW scores are logged on every turn to support future calibration
- Low-salience turns can now produce lasting memory

## References

- [architecture/memory.md](../architecture/memory.md)
- Source document: `docs/remake/SITY_SEMANTIC_MEMORY_WORTHINESS.md` (archived)
- `backend/app/cognition/memory_worthiness.py`

---

## Español

## Contexto

El sistema de memoria original usaba la salience como gate para todas las operaciones de memoria. Esto creaba un problema de acoplamiento.

**Ejemplo canónico**: "Odio el café" tiene salience baja (declaración factual rutinaria) pero MW alta (preferencia personal, larga duración, alta relevancia conductual). Bajo el sistema gateado por salience, esta declaración nunca se almacenaría.

## Decisión

Separar **salience** y **memory worthiness** como conceptos independientes:

- **Salience**: propiedad del evento/turno. ¿Merece atención cognitiva inmediata?
- **Memory Worthiness (MW)**: propiedad de cada proposición semántica. ¿Merece persistencia duradera?

Ambos caminos corren dentro del mismo turno.

## Justificación

La salience mide cuánto importa un turno ahora. La MW mide cuánto importa una proposición a largo plazo. Son dimensiones ortogonales. El acoplarlas produce puntos ciegos sistemáticos.

## Consecuencias

- Los turnos de salience baja pueden producir memoria duradera
- Expression solo puede afirmar recordar algo cuando `persisted = true`
- El umbral del gate (0.40) debe recalibrarse con datos reales de uso
- Los scores MW se loguean en cada turno para calibración futura

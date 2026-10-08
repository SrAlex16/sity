# ADR-0002: Multi-Stage Cognitive Pipeline / Pipeline Cognitivo Multi-Etapa

[English](#english) · [Español](#español)

**Status:** Accepted  
**Date:** 2026-09

---

## English

## Context

A simple chatbot sends user messages directly to a language model and returns the response. This works but produces stateless, context-free responses: the model has no sense of relationship, emotional state, goals, or self. Each conversation starts from scratch.

Sity's design goal is a home assistant that feels like a persistent presence — one that remembers significant events, tracks relationship quality, pursues goals, and can initiate contact. This requires more than a single model call per turn.

The "Remake" initiative (September 2026) systematically built this pipeline by closing cognitive loops that existed in isolation.

## Decision

Each authenticated user turn runs a multi-stage pipeline before the main Claude response:

1. **Perception** (Haiku): classify message intent, tone, challenge, social signal, novelty, context type
2. **Appraisal** (Haiku): estimate emotional deltas, trust evidence, goal changes, surprise, importance
3. **Salience** (Python): weighted score determining which subsequent stages run
4. **Episode creation** (Haiku, conditional): summarize significant turns into episodic memory
5. **Decision** (Haiku): select action policy from 10 possible actions using utility formula
6. **Reflection** (Haiku, conditional): introspective review producing self-beliefs, belief attributions, semantic candidates, relationship evidence
7. **Memory Worthiness** (Python): per-proposition persistence gate independent of salience

Background daemons handle: pattern synthesis, social reflections, autobiographical narratives, semantic consolidation.

Guest sessions skip the pipeline entirely.

## Rationale

**Why multiple Haiku calls per turn?**

Each stage has a different function that cannot be collapsed into one. Perception needs to classify before Appraisal evaluates. Appraisal needs emotional context before Decision selects action. Reflection needs the full turn context before synthesizing self-knowledge.

**Why Haiku (not Sonnet)?**

Haiku is fast enough (~1-2s per call on Pi 4B network) and cheap enough ($0.0003 per 1K input tokens) that 4-6 calls per turn remains affordable. Sonnet is reserved for complex main responses when the user approves a model upgrade.

**Why not one combined call?**

A single "do all cognition" call would: (a) produce an unpredictably long output, (b) make error isolation impossible (a bad episode creation shouldn't break decision-making), and (c) prevent selective execution based on salience thresholds.

**Why Python for salience?**

Salience must be deterministic, auditable, and free. Using a model for salience would create a non-deterministic gate and add cost to every turn. The Python formula gives consistent, testable behavior.

## Consequences

- Typical turn: 4-6 Haiku calls before the main Claude response
- Maximum Haiku output budget per turn: ~1,490 tokens
- Pipeline adds ~2-4 seconds to turn latency on Pi 4B
- Each stage fails gracefully (returns neutral/None) without breaking the turn
- Stages are individually testable and mockable in CI
- Adding a new stage requires updating `turn_cognition.py` and the test suite

## References

- Full pipeline: [architecture/cognitive-pipeline.md](../architecture/cognitive-pipeline.md)
- Phase docs: [history/remake/](../history/remake/)
- `backend/app/chat/turn_cognition.py`
- `backend/app/chat/turn_runner.py`

---

## Español

## Contexto

Un chatbot simple envía mensajes al modelo y devuelve la respuesta. Funciona, pero produce respuestas sin estado ni contexto relacional. El objetivo de diseño de Sity es un asistente con presencia persistente: que recuerde eventos significativos, rastree la calidad de la relación, persiga goals y pueda iniciar contacto.

La iniciativa "Remake" (septiembre 2026) construyó este pipeline sistemáticamente cerrando los bucles cognitivos que existían en aislamiento.

## Decisión

Cada turno de usuario autenticado corre un pipeline multi-etapa antes de la respuesta principal de Claude. Ver diagrama en [architecture/cognitive-pipeline.md](../architecture/cognitive-pipeline.md).

## Justificación

- Cada etapa tiene una función diferente que no puede colapsar en una sola
- Haiku es suficientemente rápido y barato para 4-6 llamadas por turno
- La salience en Python es determinista, auditable y gratuita
- Las etapas fallan de forma elegante sin romper el turno

## Consecuencias

Latencia adicional de ~2-4 segundos por turno en Pi 4B. Cada etapa es testeable e independiente. Añadir una nueva etapa requiere actualizar `turn_cognition.py` y la suite de tests.

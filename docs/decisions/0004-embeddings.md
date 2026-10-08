# ADR-0004: Reject Local Embeddings for Pi 4B / Rechazar Embeddings Locales en Pi 4B

[English](#english) · [Español](#español)

**Status:** Accepted  
**Date:** 2026-09-30

---

## English

## Context

The semantic memory system (Remake v2.0) needs to deduplicate `SelfBelief` and `SemanticFact` entries as the user's data grows. Without pre-filtering, every new candidate requires comparing against all existing entries — an O(n) operation on the full dataset per turn.

Local embedding models were evaluated as a way to pre-filter candidates (top-K similarity) before sending them to Haiku for deduplication, reducing the token cost as data grows.

## Decision

**Reject local embeddings for the Pi 4B for this use case.**

Benchmark results for `all-MiniLM-L6-v2` on Pi 4B (4GB RAM):

| Metric | Value |
|---|---|
| Model load time | ~26 seconds |
| Latency per proposition | ~857 ms |
| Additional RAM usage | ~880 MB |

All three metrics are disqualifying:
- 26-second load time on every backend startup is unacceptable
- 857ms per item adds unacceptable latency for multi-proposition turns
- 880MB RAM is expensive given other services running on the Pi (backend, Caddy, Home Assistant Docker)

**Current strategy (beta)**: At low data volumes, the semantic resolver sends all existing candidates directly to Haiku without pre-filtering. Expected added latency per turn: modest.

**Future strategy**: When a user exceeds ~100 `SemanticFact` or `SelfBelief` entries, use the Anthropic Embeddings API to select top-K similar items. No local RAM cost, but pay-per-use.

## Rationale

The Pi 4B hardware constraints make local embedding models impractical for synchronous turn processing. The cost of any embedding model currently viable on ARM64 exceeds what the turn budget allows.

The Anthropic Embeddings API trades local latency for API cost, but at low-to-medium data volumes, the cost is negligible and there is no RAM impact.

## Consequences

- No local embedding dependency in production
- Benchmark dependencies (PyTorch, HuggingFace cache) removed after testing
- At high data volumes (>100 entries), Haiku deduplication without pre-filtering will slow turns — this is the trigger to implement API embeddings
- ARM64 embedding models will be re-evaluated if: load time < 2s, RAM < 200 MB

## Review triggers

Re-evaluate if:
- Any user exceeds 100 active `SelfBelief` or `SemanticFact` entries
- Semantic resolver takes > 1 second per new candidate
- An ARM64 embedding model becomes available with load time < 2s and RAM < 200 MB

## References

- Source document: `docs/embeddings-decision.md`
- [architecture/memory.md](../architecture/memory.md) — Embeddings section
- Benchmark date: 2026-09-30

---

## Español

## Contexto

El sistema de memoria semántica necesita deduplicar entradas `SelfBelief` y `SemanticFact` a medida que crecen los datos del usuario. Los modelos de embedding locales se evaluaron para pre-filtrar candidatos antes de enviarlos a Haiku.

## Decisión

**Rechazar los embeddings locales para la Pi 4B para este caso de uso.**

Benchmark de `all-MiniLM-L6-v2` en Pi 4B:
- Tiempo de carga del modelo: ~26 segundos
- Latencia por proposición: ~857 ms
- RAM adicional: ~880 MB

Los tres métricas son descalificadoras.

**Estrategia actual (beta)**: El resolver semántico envía todos los candidatos existentes directamente a Haiku sin pre-filtrado.

**Estrategia futura**: Cuando un usuario supere ~100 entradas, usar la API de Embeddings de Anthropic para seleccionar top-K similares. Sin coste de RAM local.

## Consecuencias

- Sin dependencia de embeddings locales en producción
- Dependencias del benchmark (PyTorch, caché HuggingFace) eliminadas tras el test
- Con >100 entradas, la deduplicación de Haiku sin pre-filtrado ralentizará los turnos — ese es el trigger para implementar embeddings vía API

## Triggers de revisión

Revisitar si: algún usuario supera 100 entradas activas, el resolver tarda >1s por candidato, o aparece un modelo ARM64 con carga <2s y RAM <200MB.

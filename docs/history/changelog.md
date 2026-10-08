# Implementation Changelog / Historial de Implementación

[English](#english) · [Español](#español)

This file records significant implementation events extracted from state.md and project history. For the narrative evolution, see [timeline.md](timeline.md).

---

## English

### 2026-10-08

- **Status**: Public beta active. 0 known P0 issues.
- **Tests**: 3,704 passing (6 skipped), 73% global coverage, 0 mypy errors
- **Remake v2.0 post-adjustments (2026-10-01)**: Seven refinements committed:
  - Evidence trail is the source of truth for confidence
  - SemanticFact and SelfBelief consolidated separately
  - Contradiction handling consistent online and offline
  - Evidence strength weighted in update math
  - Adaptive initiative runner: Haiku decides next check time
  - Urgent goals wake the initiative runner early
  - Expectation resolution: `expired_unknown ≠ violated`

### 2026-09-28 — Adaptive initiative runner

Replaced fixed 6-hour initiative interval with event-driven runner. Haiku decides when to check next. Urgent goals (base importance ≥ 0.75) can wake runner early.

### 2026-09-16 — Post-Remake integral audit

3,104 tests passing. 11 findings identified (see [security/audit-results.md](../security/audit-results.md)). Response integrity layer added (`dc4e7a4`).

### 2026-09-15 — Response integrity + session queue

- Response integrity (`response_integrity.py`, `dc4e7a4`): post-generation safety layer
- Session queue (`063f1e5`): per-session lock to serialize turns, fixes parallel turn race condition

### 2026-09-12 — Remake Phases 6–9 (3 days)

All implemented same day:
- **Phase 6**: SelfModel + SityValues + Reflection. 65 new tests. Commits: `0e690d8`, `d208822`, `02eaa5d`
- **Phase 7**: Procedural memory + pattern synthesis. 53 new tests. Commits: `ba293f0`, `0910095`
- **Phase 8**: UserModel + Theory of Mind + Expectations. 53 new tests.
- **Phase 9**: Semantic consolidation from episodes. 39 new tests.

### 2026-09-10 — Remake Phase 5: Decision

Action policy module. 10 actions, utility formula with 22 signals, Haiku validation, coherence check. 52 new tests in `test_decision_service.py`.

### 2026-09-09 — Remake Phases 2–4

- **Phase 2**: Appraisal + Perception + Goals. Goal lifecycle, milestones, initiative integration.
- **Phase 3**: Multidimensional social model (11 dimensions replacing `opinion`/`trust`). 183 tests across 6 files.
- **Phase 4**: Episodic + autobiographical memory. 46 new tests.

### 2026-09-14 — Database reset (dataset cutoff)

Database reset. Start of LoRA v1 training dataset. Google and Spotify OAuth connections require manual re-establishment.

### 2026-09-13 — Frontend sync for Remake Phase 1

PWA updated for 13 personality traits. Verbosity section changed to admin-only. Old `frontend/` panel removed; debug/dataset tools moved to PWA `DevToolsScreen`.

### 2026-09-08 — Remake Phase 1: Personality refactor

14 traits → 13 traits. Verbosity → `CommunicationPreferences`. Melancholy → `MentalState`. Commit: `6205c6c`.

### 2026-09-07 — File management (Steps 1–3)

`FileArtifact` table, multi-turn visual context, frontend file manager.

### 2026-08-28 — Achievements system

Declarative catalog, engine, inline triggers (Phase 2a, 21 triggers). `test_achievement_triggers.py`.

### 2026-08-25 — Social narrative reflection

Commit `386e476`. Narrative reflection generated from real messages. 8 tests.

### 2026-08-24 — Proactive initiative (verified)

Open-loop detection, conversation-abandoned trigger, long-inactivity trigger. 128 tests.

### 2026-08-11 — Auth system Phase 2

Per-user session IDs (`user:{id}`, `guest:{uuid}`). Chat history isolated per user.

### 2026-08-07 to 2026-08-10 — Notification architecture

SSE fan-out model (zombie connection fix), Web Push with VAPID, `NotificationLog`, `timer_fired` high priority.

### 2026-08-05 — Timers and alarms

`set_timer`, `set_alarm`, `list_timers`, `cancel_timer`. SQLite persistence, asyncio runner. 28 tests.

### 2026-08-04 — Security audit (manual)

18 cases verified. 4 bugs found and fixed. 3 P0 risks closed.

### 2026-08-03 — Security fixes

- Role gating for toolset selector
- Tool result redaction before reaching model
- Explicit timeouts for Google and Claude API calls

### 2026-07-28 — Dataset review

2,029 user messages reviewed; 703 eligible for export. 1,159 untagged pre-instrumentation messages excluded pending review.

### 2026-07-10 — Multi-turn tool loop

Max 3 rounds. Fixes ghost actions (model describing actions it never performed). 6 tests.

### 2026-07-09 — Turn cancellation

Stop button with two independent mechanisms (browser abort + backend flag). 6 chained bugs fixed.

### 2026-07-08 — YouTube channel removed

Built, tested, removed. Manual editing was the bottleneck.

### 2026-06 — Telegram removed

PWA made the Telegram bot redundant. Cleanup pass in September 2026.

---

## Español

Este archivo registra eventos de implementación significativos extraídos de state.md y el historial del proyecto. Para la evolución narrativa, ver [timeline.md](timeline.md).

### 2026-10-08

- **Estado**: Beta pública activa. 0 P0 conocidos.
- **Tests**: 3.704 pasando (6 saltados), 73% cobertura global, 0 errores mypy

### 2026-10-01 — Ajustes post-Remake v2.0

Siete refinamientos: evidence trail como fuente de verdad de confianza, consolidación separada de SemanticFact y SelfBelief, manejo consistente de contradicciones, fuerza de evidencia ponderada en el cálculo, runner adaptativo de iniciativa.

### 2026-09-28 — Runner adaptativo de iniciativa

Reemplazó el intervalo fijo de 6 horas con un runner basado en eventos.

### 2026-09-16 — Auditoría integral post-Remake

3.104 tests pasando. 11 hallazgos identificados. Capa de integridad de respuesta añadida.

### 2026-09-15 — Cola de sesión + integridad de respuesta

Fix de condición de carrera en turnos paralelos. Capa post-generación de seguridad.

### 2026-09-12 — Fases 6–9 del Remake

SelfModel, valores, reflexión metacognitiva, memoria procedimental, UserModel, teoría de la mente, expectativas, consolidación semántica. Total: ~210 tests nuevos.

### 2026-09-14 — Reset de base de datos

Inicio del dataset de entrenamiento LoRA v1.

### 2026-09-08 — Fase 1 del Remake: refactor de personalidad

14 rasgos → 13 rasgos. Commit `6205c6c`.

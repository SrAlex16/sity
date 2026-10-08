# Project Timeline / Línea de Tiempo del Proyecto

[English](#english) · [Español](#español)

---

## English

### Origins (early 2026)

Sity began as a personal AI assistant experiment on a Raspberry Pi 4. The initial concept: a home assistant with a distinct personality, persistent memory, and direct integrations with daily tools — all running locally or at minimal cloud cost.

Early decisions that shaped everything:
- **Claude as the only AI provider**: no attempt to run open models from the start; reliability and tool-use quality were paramount
- **SQLite as the database**: no Docker for the DB, simple deployment, FTS5 for search
- **Git-based workflow**: develop on Pi via Claude Code over SSH, commit, push, CI runs
- **No hardcoded keyword lists**: leave interpretation to the model

### Personality and voice (2026-05 to 2026-06)

The character was established: tsundere anime tropes, sarcastic game AI, Castilian Spanish, feminine grammatical gender. Initial personality had 14 parameters with some overlap and an archetype label visible to the model.

A three-role auth system was built (guest/user/admin). Chat history was isolated per user. The mobile PWA was styled in neon cyberpunk — Chat, Traits, Voice, and Data screens.

### Integrations (2026-06 to 2026-07)

- Google (Gmail read-only, Calendar write with confirmation, Drive metadata)
- Spotify (with task context for URI persistence)
- Home Assistant (Docker on Pi, services abstraction)
- Web search (DuckDuckGo with caching)
- Multi-turn tool loop (max 3 rounds, fixes ghost actions)
- Turn cancellation (stop button with two independent mechanisms)

**Telegram removed** (June 2026): PWA made it redundant.

**YouTube channel module**: built and removed the same month (July 2026). Pipeline worked, but manual editing was the bottleneck.

### Social memory (2026-07 to 2026-08)

Phase 4 introduced social memory: per-user relationship tracking with `opinion` and `trust` fields, a background job using EMA, and prompt injection for authenticated users.

Social narrative reflection was added (August 2026, commit `386e476`): a 2-4 sentence descriptive reflection generated from real messages, injected as "pattern observed."

### Security work (August 2026)

Manual security audit (2026-08-04): 18 cases verified. Four bugs found and fixed (localStorage race, cookie deletion on logout, guest session race condition). Three pre-existing P0 risks closed.

Web Push notifications, timers, shared conversations, file management, and the achievements system were built and stabilized during August.

### The Remake (September 2026)

The "Mini-Operación Remake" systematically replaced the isolated v1 modules with a closed cognitive loop. Nine phases over ~2 weeks:

| Phase | Topic | Commit(s) | Date |
|---|---|---|---|
| 1 | Personality refactor (14→13 traits) | `6205c6c` | 2026-09-08 |
| 2 | Appraisal + Goals + Perception | — | 2026-09-09 |
| 3 | Multidimensional social model (11 dimensions) | — | 2026-09-09 |
| 4 | Episodic + autobiographical memory | — | 2026-09-09 |
| 5 | Decision action policy (10 actions) | — | 2026-09-10 |
| 6 | SelfModel + Values + Reflection | `0e690d8`, `d208822`, `02eaa5d` | 2026-09-12 |
| 7 | Procedural memory + pattern synthesis | `ba293f0`, `0910095` | 2026-09-12 |
| 8 | UserModel + Theory of Mind + Expectations | — | 2026-09-12 |
| 9 | Semantic consolidation from episodes | — | 2026-09-12 |

Post-Remake audit (2026-09-16): 3,104 tests passing. 11 findings (1 P1, several medium, several low).

**Remake v2.0** (September–October 2026): Closing open loops identified after v1. Key changes:
- Episodic retrieval injected into prompts (episodes were stored but never read back)
- Single refusal authority (Decision, not a separate `_should_refuse()`)
- Memory Worthiness separated from Salience
- Local embeddings evaluated and rejected
- Adaptive initiative runner (Haiku decides timing)
- Temporal dynamics: MentalState decay, SemanticFact stability categories

Seven post-implementation refinements (2026-10-01): evidence trail as confidence source, separate consolidation for SemanticFact and SelfBelief, consistent contradiction handling, weighted evidence strength.

### Public beta (October 2026)

- **Database reset**: 2026-09-14 (start of LoRA v1 dataset)
- **Beta launch**: October 2026
- **Status**: 0 known P0 issues, 3,704 tests passing, 73% coverage

---

## Español

### Orígenes (principios de 2026)

Sity comenzó como un experimento de asistente personal con IA en una Raspberry Pi 4. El concepto inicial: un asistente doméstico con personalidad propia, memoria persistente e integraciones directas con herramientas cotidianas.

Decisiones tempranas que definieron todo:
- Claude como único proveedor de IA
- SQLite como base de datos (sin Docker para la BD)
- Flujo basado en git (desarrollar en Pi por SSH, commit, push, CI)
- Sin listas de palabras clave hardcodeadas — interpretación delegada al modelo

### Personalidad y voz (2026-05 a 2026-06)

Se estableció el carácter: tropos tsundere, IA sarcástica, español castellano, género gramatical femenino. Sistema de autenticación con tres roles. PWA móvil con estilo cyberpunk neón.

### Integraciones (2026-06 a 2026-07)

Google, Spotify, Home Assistant, búsqueda web. Bucle multi-turno de tools, cancelación de turno. Telegram eliminado (suprimido por la PWA). Canal de YouTube: construido y eliminado el mismo mes.

### Memoria social (2026-07 a 2026-08)

Memoria social con `opinion` y `trust`, job en background con EMA, reflexión narrativa social.

### Trabajo de seguridad (agosto de 2026)

Auditoría manual (2026-08-04): 18 casos verificados, 4 bugs encontrados y corregidos. Web Push, timers, conversaciones compartidas, gestión de archivos y sistema de logros.

### El Remake (septiembre de 2026)

"Mini-Operación Remake": nueve fases que reemplazaron los módulos aislados de v1 con un bucle cognitivo cerrado. Ver tabla en la sección en inglés.

Auditoría post-Remake (2026-09-16): 3.104 tests pasando. Remake v2.0: cierre de bucles abiertos, episodic retrieval en prompts, Memory Worthiness separada de Salience, runner de iniciativa adaptativo.

### Beta pública (octubre de 2026)

Reset de BD el 2026-09-14 (inicio del dataset LoRA v1). Lanzamiento de beta pública en octubre de 2026. Estado: 0 P0 conocidos, 3.704 tests pasando, 73% de cobertura.

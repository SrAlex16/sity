> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# Personality Alters

**Status**: Superseded by Remake Phase 1 personality refactor (2026-09-08)

This document described the **Alters** system: named snapshots of Sity's personality traits that users could save, load, rename, and clear (up to 5 per user).

The Alters system was designed for the v1 14-trait personality model. The Remake Phase 1 (commit `6205c6c`) restructured personality from 14 to 13 traits with a different schema. Alters may or may not have been preserved through the migration.

**Original design**:
- `PersonalityAlter` table: keyed by user and slot (1–5), traits stored as JSON
- Operations: save, load, rename, clear, copy (via `AlterService`)
- Loading reused the existing bulk personality write
- Guests rejected, every query filtered by user ID
- Six REST endpoints + `AltersPanel` React component

**Tests at time of writing**: 23 service-layer tests, suite of 1,842 tests passing, manual verification 2026-08-13.

For the current personality system, see: [architecture/personality.md](../../architecture/personality.md)

> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# Refusal Mode Architecture

**Superseded by**: Remake Phase 5 — Decision module (2026-09-10)

This document described the `refusal_mode` structural setting and the `_should_refuse()` function. In the original architecture, refusal logic was split between a structural persona setting (`refusal_mode`) and a per-turn function (`_should_refuse()`). This duplicated the decision logic.

**What changed in Remake Phase 5**: The Decision module now handles all per-turn refusal logic as the `refuse` action in the 10-action policy. `_should_refuse()` was removed. `refusal_mode` remains as a structural setting that prevents responses at the persona level (before Decision runs), but per-turn refusal decisions are exclusively handled by Decision.

**Reference in this document**: Any reference to `refusal_chance` in this document is obsolete. `refusal_chance` was replaced by `refusal_propensity` in Remake Phase 1 (2026-09-08, commit `6205c6c`).

See current architecture: [architecture/decision-making.md](../../architecture/decision-making.md)

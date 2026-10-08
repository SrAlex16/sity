> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# Personality Isolation

**Status**: Superseded — integrated into the auth system (see auth-system.md, Phase 2b)

This document originally described the personality isolation design: personality and voice settings stored per session using a composite key `(key, session_id)` with a NULL session as the global fallback.

The design was integrated into the auth system Phase 2b. See the current auth documentation: [architecture/integrations.md](../../architecture/integrations.md)

**Key lesson recorded**: A bug was found where turns read the global personality value instead of the session-specific one. The checklist to prevent this: always query with `session_id`, never fall through silently to the global value when a session is active.

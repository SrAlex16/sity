> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# Self-Service Integrations Analysis

**Status**: This was a design spec for Phase 6 of auth — per-user Google and Spotify OAuth connections. Implementation status is unclear from this document.

**Original design**:
- `UserIntegration` table: one row per user/provider, credentials encrypted with Fernet
- Web OAuth flow with HMAC-signed `state` parameter, 10-minute expiry
- Disconnection sets `is_active=False` (preserves audit history)
- Key safety: startup check that encryption key can decrypt existing data
- Tool handlers load the active user's credentials and return actionable messages when unconfigured
- One-time migration script for Admin's existing token files
- Home Assistant stays global/Admin-only (uses long-lived token, not OAuth)

See current integration docs: [architecture/integrations.md](../../architecture/integrations.md)

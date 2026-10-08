> **[ARCHIVED]** This document describes a feature or design that has been removed or superseded. It is preserved for historical reference only.
> 
> **[ARCHIVADO]** Este documento describe una funcionalidad o diseño eliminado o sustituido. Se conserva solo como referencia histórica.

---

# Web Navigation Risk Analysis

**Date**: 2026-08-06  
**Status**: Analysis complete. Conclusions were implemented.

This document analyzed whether Sity should gain active web browsing capabilities (browser-use, crawl4ai, or similar tools that render pages and interact with them).

**Conclusion**: Full interactive browsing deferred. Read-only `read_webpage(url)` tool implemented instead (22 tests).

**Reasons for deferral of full browsing**:
- Prompt injection risk through hidden page content
- Unintended form submission risk
- Resource exhaustion risk on Pi 4B (JavaScript rendering is CPU-intensive)
- Requires Docker sandboxing that doesn't yet exist

**Implemented alternative**: A narrow `read_webpage(url)` tool with:
- Text extraction only (no JavaScript, no interaction)
- Explicit timeouts
- Output truncation
- Download blocking
- SSRF protections

This document is archived because the decision was made and implemented. If full interactive browsing is revisited, the risk analysis here provides the baseline threat model.

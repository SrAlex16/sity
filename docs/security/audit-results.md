# Security Audit Results / Resultados de Auditorías

[English](#english) · [Español](#español)

---

## English

### Audit 1: Manual security checklist (2026-08-04)

**Scope**: Manual testing of major changes. 18 cases verified (18/18).
**Excludes**: RAG, automated attack generation, CI regression.

**Results by area**:

| ID | Area | Result |
|---|---|---|
| SEC-01, 02 | System prompt extraction | Passed — prompt not revealed under direct or injection attacks |
| SEC-03, 04 | Web search prompt injection | Passed — adversarial instruction in search result ignored |
| SEC-05 to 08 | User isolation | Passed — history scoped by JWT session ID; cookie swap cannot cross-authenticate |
| SEC-09, 10 | Social memory | Passed — single message cannot change trust/opinion; no concrete data about other users disclosed |
| SEC-11, 12 | Least privilege | Passed — git, file, service-control tools restricted to admins |
| SEC-13, 14 | Destructive actions | Passed (after fix) — P0 cross-session confirmation flaw found and fixed in `c4a307a` |
| SEC-15 | Secrets | Passed (after fix) — redaction applied to tool results |
| SEC-16, 17 | Timeouts and anti-bot | Passed — explicit timeouts, reCAPTCHA fails closed |
| SEC-18 | Error disclosure | Passed — no stack traces, paths, or env vars in errors |

**Bugs found and fixed during execution**:

1. **Bug 1** (localStorage race): Global localStorage key shared chat-clear state across users. Fixed.
2. **Bug 2** (Admin cookie): Admin session cookie survived logout on Chrome 104+ because the delete header lacked matching attributes. Service restart required to deploy fix.
3. **Bug 3** (Guest cookie): Same deletion problem as Bug 2. Fixed.
4. **Bug 4** (Race condition): A response from an in-flight turn could land in a new Guest session. Fixed by aborting the stream on logout and adding a user-key guard.

**P0 pre-existing risks closed on 2026-08-03**:
- Role gating for toolset selector (SEC-11/12)
- Redaction of tool results before reaching the model (SEC-15)
- Explicit timeouts for Google and Claude API calls (SEC-16)

---

### Audit 2: Post-Remake integral audit (2026-09-16)

**Scope**: Passive code review, docs, tests, and CI. No production logs or active exploitation.
**Method**: Static analysis (`pyflakes`), query-level user isolation checks, layer boundary review, test suite run.

**Test results**: 3,104 backend tests passing, 0 failed. Frontend (vitest): 12/12.

**Strengths confirmed**:
- Three independent access control layers (toolset construction → executor gate → post-generation check)
- Upload path-traversal validation solid
- CI isolates backend from real API keys
- Deleting another user's file returns 404 without revealing ownership
- No secrets in git history or hardcoded credentials

**Findings**:

| ID | Severity | Finding |
|---|---|---|
| A1 | Medium | `GET /uploads/images/{filename}` has no authentication or ownership check |
| A2 | Medium-High | `/auth/login` and password reset have no rate limit. reCAPTCHA fails open if key missing |
| A3 | Medium | Frontend tests never run in CI |
| A4 | Medium | `vite-plugin-mkcert` loads unconditionally (Vitest fails without network) |
| A5 | Medium | `docs/architecture.md` outdated relative to Remake (closed by this doc reorganization) |
| A6 | Low | Failed file deletions silently ignored (can leave orphaned files on disk) |
| A7 | Low | 9 direct `datetime.utcnow()` calls remain |
| A8 | Low | Dev proxy omits `/uploads` and `/files` |
| A9 | Low | Known flaky test unresolved |
| A10 | Low | Caddy config lacks security headers |
| A11 | To verify | `refusal-mode-architecture.md` references `refusal_chance` (superseded) — document archived |

**Status of findings**:
- A5: Closed by doc reorganization
- A11: Closed — document moved to `history/archive/`
- A1, A2, A3, A4: Open (see [security/overview.md](overview.md))
- A6–A10: Open (low priority)

**Priority recommendations from audit**:
1. Rate limiting on login/reset + reCAPTCHA fail-closed in production (A2)
2. Auth + ownership check on `GET /uploads/images/{filename}` (A1)
3. Conditional mkcert + add `npm test` to mobile CI job (A3, A4)
4. Fix file-deletion error handling, `utcnow()` usage, dev proxy (A6, A7, A8)
5. Fix flaky test, add Caddy security headers (A9, A10)

**Audit limitations**: Production logs and real DB not inspected. No active exploitation attempted. A1 and A2 confirmed by code reading only.

---

### Audit 3: Security scan (QA Round 5, 2026-09-2x)

See project QA docs (`qa/ronda-5-informe.md`) for full findings from this round. The audit campaign produced 36 total findings across all rounds.

---

## Español

### Auditoría 1: Checklist de seguridad manual (2026-08-04)

18 casos verificados (18/18). Ver tabla de resultados en la sección en inglés.

**Bugs encontrados y corregidos durante la ejecución**:

1. Clave localStorage global compartía estado de borrado de chat entre usuarios
2. Cookie de sesión Admin sobrevivía al logout en Chrome 104+ (header de delete sin atributos coincidentes) — requirió reinicio del servicio
3. Mismo problema de borrado en cookie Guest
4. Condición de carrera: respuesta de turno en vuelo podía aterrizar en nueva sesión Guest — fix: abortar stream al logout + guard de clave de usuario

**P0 pre-existentes cerrados el 2026-08-03**: gating por rol del toolset selector, redacción de resultados de tools, timeouts explícitos.

---

### Auditoría 2: Auditoría integral post-Remake (2026-09-16)

**Alcance**: Revisión pasiva de código, docs, tests y CI. Sin logs de producción ni explotación activa.

**Resultados de tests**: 3.104 backend passing, 0 failed. Frontend: 12/12.

**Puntos fuertes confirmados**: tres capas independientes de control de acceso, validación de path-traversal sólida, CI aislado de keys reales, eliminación de archivo ajeno devuelve 404 sin revelar propiedad, sin secretos en el historial de git.

**Hallazgos**: Ver tabla en la sección en inglés (A1–A11).

**Estado de hallazgos**:
- A5: Cerrado por reorganización de docs
- A11: Cerrado — documento movido a `history/archive/`
- A1, A2, A3, A4: Abiertos
- A6–A10: Abiertos (prioridad baja)

**Limitaciones de la auditoría**: No se inspeccionaron logs de producción ni la BD real. No se intentó explotación activa.

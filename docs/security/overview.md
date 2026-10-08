# Security Overview / Modelo de Seguridad

[English](#english) · [Español](#español)

---

## English

### Threat model

Sity is a home assistant with access to personal data, integrations with external services, and system-level capabilities. The main threats are:

1. **Prompt injection** — adversarial content in external data (search results, emails) instructing the model to act outside its scope
2. **Privilege escalation** — a guest or user session accessing admin-level tools or another user's data
3. **Capability fabrication** — the model claiming to have tools or capabilities it doesn't
4. **Memory fabrication** — the model claiming to remember things it doesn't (especially in guest sessions)
5. **Secrets exposure** — API keys, passwords, or internal architecture leaking in responses
6. **Social manipulation** — adversarial inputs attempting to directly modify trust or opinion scores

### Defense layers

#### Layer 1: Toolset construction (role-based)

Tools are assembled at session start based on role. Admin tools are never included in user or guest toolsets. This is enforced before any prompt is constructed.

#### Layer 2: Executor gate (runtime authorization)

`tool_executor.py` re-checks authorization at execution time. Even if the model somehow requests an admin tool in a user session, the executor refuses it.

#### Layer 3: Post-generation check (`response_integrity.py`)

Scans every response for:
- `capability_overclaim` — claiming tools it doesn't have
- `internal_leak` — revealing internal architecture
- `memory_fabrication` — claiming memory for guest sessions
- `contradiction` — contradicting earlier confirmed statements
- `architecture_disclosure` — revealing cognitive pipeline details

Pre-filter (free regex): only activates for risk-pattern turns. Haiku call only on positive match. If API fails: text passes unchanged (turn must not be broken).

#### Layer 4: Unknown tool sanitization

If the model invokes a tool that doesn't exist: user receives a generic message ("I can't complete that action"). The actual tool name is preserved in audit logs (WARN level).

#### Additional mechanisms

| Mechanism | Commit | Blocks |
|---|---|---|
| toolset_selector | pre-existing | Admin tools out of scope |
| Executor auth gate | `5935831` | Admin tool execution at runtime |
| Unknown tool sanitization | `3136cd4` | Exposing internal tool names |
| response_integrity | `dc4e7a4`+ | Capability claims, leaks, fabricated memory |
| Role attribution | `3299eb3` | Role inversion in message history |
| History level "moderate" | `ab810e7` | Anaphoric references without context |
| Session queue | `063f1e5` | Concurrent turns with incomplete context |

### Critical actions

Destructive or irreversible actions require a two-step confirmation:
1. The model proposes a plan (pending state)
2. The user confirms with an exact confirmation phrase

A P0 cross-session confirmation flaw was found and fixed in commit `c4a307a` (one session could confirm another session's pending action).

### Network security

- Backend listens on `localhost:8000` only (no direct external access)
- Caddy handles TLS termination and auth headers
- No open ports on the Pi; remote access via Cloudflare Tunnel only
- Audio and capture routes require authentication with role-based restrictions

### Secret redaction

API responses redact secrets before they reach the model. This applies to tool results as well (fixed in 2026-08-03 audit).

External HTTP calls have explicit timeouts (no hanging connections).

### Social memory security invariants

- Guest sessions never receive a social profile
- Only the background job writes `opinion` and trust dimensions
- Load tags come from the model output, never from user text
- Third-party information limited to qualitative labels (no literal message content, dates, or numeric values)

### Data isolation

Every database query involving user data is filtered by `user_id` or `session_id`. There is no shared query path between users.

File ownership is checked on every file operation. Deleting another user's file returns 404 without revealing ownership.

### Prompt injection mitigation

Web search results are wrapped as explicitly untrusted content in the prompt. The model is instructed to treat them as data, not instructions.

### Open security findings (post 2026-09-16 audit)

| ID | Severity | Finding | Status |
|---|---|---|---|
| A1 | Medium | `GET /uploads/images/{filename}` no auth | Open |
| A2 | Medium-High | No rate limit on `/auth/login` and reset; reCAPTCHA fails open if key missing | Open |
| A3 | Medium | Frontend tests not in CI | Open |
| A4 | Medium | `vite-plugin-mkcert` loads unconditionally | Open |

---

## Español

### Modelo de amenazas

Las principales amenazas son:

1. **Prompt injection** — contenido adversarial en datos externos (resultados de búsqueda, emails) instruyendo al modelo a actuar fuera de su alcance
2. **Escalada de privilegios** — sesión guest o user accediendo a tools de admin o datos de otro usuario
3. **Fabricación de capacidades** — el modelo afirma tener tools que no tiene
4. **Fabricación de memoria** — el modelo afirma recordar cosas que no recuerda (especialmente en sesiones guest)
5. **Exposición de secretos** — API keys, contraseñas o arquitectura interna filtrándose en respuestas
6. **Manipulación social** — inputs adversariales intentando modificar directamente los scores de confianza u opinión

### Capas de defensa

#### Capa 1: Construcción del toolset (por rol)

Las tools se ensamblan al inicio de la sesión según el rol. Las tools de admin nunca se incluyen en toolsets de user o guest.

#### Capa 2: Gate del executor (autorización en runtime)

`tool_executor.py` re-verifica la autorización en el momento de ejecución.

#### Capa 3: Verificación post-generación (`response_integrity.py`)

Escanea cada respuesta buscando afirmaciones de capacidad, fugas internas, memoria fabricada, contradicciones y revelación de arquitectura.

Pre-filtro con regex (gratuito): solo activa la verificación con Haiku para patrones de riesgo. Si falla la API: el texto pasa sin cambios.

#### Capa 4: Sanitización de tools desconocidas

Si el modelo invoca una tool inexistente: el usuario recibe un mensaje genérico. El nombre real de la tool se conserva en logs de auditoría (nivel WARN).

### Acciones críticas

Las acciones destructivas requieren confirmación en dos pasos: el modelo propone un plan → el usuario confirma con frase exacta.

Un fallo P0 de confirmación cross-sesión fue encontrado y corregido en commit `c4a307a` (una sesión podía confirmar la acción pendiente de otra sesión).

### Seguridad de red

- Backend solo escucha en localhost:8000
- Caddy gestiona TLS y headers de auth
- Sin puertos abiertos en la Pi; acceso remoto solo vía Cloudflare Tunnel
- Las rutas de audio y captura requieren autenticación con restricciones por rol

### Invariantes de memoria social

- Los guest nunca tienen perfil social
- Solo el job en background escribe opinion y dimensiones de confianza
- Las etiquetas de carga vienen del output del modelo, nunca del texto del usuario
- La información de terceros está limitada a etiquetas cualitativas

### Hallazgos de seguridad abiertos (post auditoría 2026-09-16)

Ver tabla en la sección en inglés.

# Integrations / Integraciones

[English](#english) · [Español](#español)

---

## English

### Authentication system

Three roles, all enforced at multiple layers:

| Role | Account | Message limit | Session ID | Toolset |
|---|---|---|---|---|
| Guest | None (cookie) | 20/day per IP | `guest:{uuid}` | Read-only, no admin tools |
| User | DB row | 100/day | `user:{id}` | Full user toolset |
| Admin | DB row (env vars) | None | `user:{id}` | Full toolset including admin tools |

**Session lifecycle**:
- Authenticated users: JWT in `HttpOnly`, `SameSite=Lax` cookie, 72-hour lifetime
- Guest: `sity_guest_session` cookie, deleted on login/register. Guest history not migrated to accounts.
- No refresh tokens yet.

**Auth endpoints**: `/auth/register` · `/auth/login` · `/auth/logout` · `/auth/me` · `/auth/forgot-password` · `/auth/reset-password` · `DELETE /auth/me`

**Hashing**: bcrypt directly (not passlib). Passwords: minimum policy enforced.

**Reset tokens**: Single-use UUID with 1-hour TTL. No password emailed.

**Rate limiting**:
- Guest sessions: 30 requests/hour per IP (in-memory)
- Login/reset: needs rate limiting (open finding A2 from 2026-09-16 audit)

**reCAPTCHA v3**: Used on register and login. Fails closed in production when key is present.

**Personality isolation**: Settings are per session. Composite key `(key, session_id)` with NULL session as global fallback. A bug was found where turns read the global value instead of the session value — always query with session_id, never fall through silently.

### Google OAuth (Gmail, Calendar, Drive)

- Gmail: read-only
- Calendar: create, edit, delete — with user confirmation for write actions
- Drive: read-only (metadata)

OAuth 2.0 + PKCE. Google integration stays in "Testing" mode until test users are explicitly added in Cloud Console.

Tools are self-contained because the model planner makes one tool call per turn.

### Spotify

OAuth 2.0 + PKCE. Redirect URIs must be plain text and saved explicitly in the Spotify dashboard.

Integration uses `task_context` (see [features/conversation.md](../features/conversation.md)) to persist `spotify_uri` and `spotify_device_id` across turns so retries don't need to re-search.

### Home Assistant

Home Assistant runs in **Docker on the Pi** as an abstraction layer for home automation.

Available tools:
- List entities
- Read state
- Call services (irreversible actions require confirmation)

Design principle: HA is an abstraction layer. Sity doesn't talk directly to smart home devices — it talks to HA, which handles device-specific protocols.

### Web search

DuckDuckGo-based `web_search` tool. Invoked only when information may be outdated. Three-iteration cap on the tool loop. Results cached in SQLite:
- Dynamic content: ~1 hour TTL
- Stable content: ~24 hours TTL

### Image input

Images attached to messages are stored in `uploads/images/` and registered in `FileArtifact`. They are included in prior message history so the model can see images from recent turns. The routing planner never receives image blocks (saves tokens).

Background semantic extraction: uploads sent to Haiku → up to 3 `SemanticFact` rows per image stored.

---

## Español

### Sistema de autenticación

Tres roles, todos reforzados en múltiples capas. Ver tabla en la sección en inglés.

**Aislamiento de personalidad**: Los settings son por sesión. Clave compuesta `(key, session_id)` con NULL session como fallback global. Bug encontrado: los turnos leían el valor global en lugar del de sesión — siempre consultar con session_id, nunca hacer fallthrough silencioso.

**reCAPTCHA v3**: Falla cerrado en producción cuando la clave está presente. Falla abierto cuando la clave falta (hallazgo A2 de la auditoría 2026-09-16, pendiente de fix).

### Google OAuth (Gmail, Calendario, Drive)

- Gmail: solo lectura
- Calendario: crear, editar, borrar — con confirmación del usuario para escrituras
- Drive: solo lectura (metadatos)

Las herramientas son autocontenidas porque el planificador hace una tool call por turno.

### Spotify

OAuth 2.0 + PKCE. Los URIs de redirección deben ser texto plano y guardados explícitamente en el dashboard de Spotify.

La integración usa `task_context` para persistir `spotify_uri` y `spotify_device_id` entre turnos. Esto permite que los reintentos no necesiten volver a buscar.

### Home Assistant

Home Assistant corre en **Docker en la Pi** como capa de abstracción para domótica. Las acciones irreversibles requieren confirmación del usuario.

Principio de diseño: HA es la capa de abstracción. Sity no habla directamente con dispositivos del hogar — habla con HA, que gestiona los protocolos específicos de cada dispositivo.

### Búsqueda web

Tool `web_search` basada en DuckDuckGo. Solo cuando la información puede estar desactualizada. Cap de 3 iteraciones en el bucle de tools. Resultados cacheados en SQLite con TTL diferenciado (contenido dinámico ~1h, contenido estable ~24h).

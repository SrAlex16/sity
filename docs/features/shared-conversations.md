# Shared Conversations / Conversaciones Compartidas

[English](#english) · [Español](#español)

---

## English

### Overview

Users can share a conversation with Sity through a public, read-only link that expires automatically. The link is a **fixed snapshot** — messages sent after sharing do not appear.

### Privacy principles

- Public response never includes the real session ID or owner identity metadata
- Snapshot is a fixed JSON copy, not a live view
- Share IDs are random 32-character hex strings (UUID4) — not enumerable
- Guest users cannot create share links (no persistent identity)
- Public messages expose only: role · text · timestamp

### Data model (`SharedConversation`)

Stored in SQLite. Fields:

| Field | Description |
|---|---|
| `id` | 32-char random hex |
| `owner_session` | Session ID of creator |
| `snapshot` | Fixed JSON copy of messages at share time |
| `created_at` | Creation timestamp |
| `expires_at` | Default: 7 days, configurable |
| `view_limit` | Optional max views (null = unlimited) |
| `view_count` | Number of times accessed |
| `revoked_at` | Set on revocation |

A link is valid only if: not revoked AND not expired AND view count < limit.

### Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/chat/share` | User/Admin | Create snapshot, return share ID + URL + expiry |
| `GET` | `/shared/{share_id}` | Public | Return filtered messages + metadata, increment view count |
| `DELETE` | `/chat/share/{share_id}` | Owner only | Revoke (idempotent) |

`GET /shared/{share_id}` returns:
- 410 Gone if expired, revoked, not found, or over view limit

### Frontend

"Compartir conversación" option in the chat menu (logged-in users only). Shows the link with a copy button and expiry date.

Public `/shared/{id}` route: read-only message view with no login, no app chrome, no input field, no tool access.

### Known limitations

- No UI to list or revoke active links; revocation requires the API or DevTools
- View limit cannot be set from the UI (defaults to unlimited; must be set in DB directly)

### Tests

15 tests cover: creation · snapshot immutability · expiry · revocation · view counting · sensitive field exclusion · authorization

---

## Español

### Visión general

Los usuarios pueden compartir una conversación mediante un enlace público de solo lectura que expira automáticamente. El enlace es una **foto fija** — los mensajes enviados después de compartir no aparecen.

### Principios de privacidad

- La respuesta pública nunca incluye el session ID real ni metadatos de identidad del propietario
- Share IDs: hex aleatorio de 32 caracteres (UUID4) — no enumerables
- Los guest no pueden crear enlaces (sin identidad persistente)
- Los mensajes públicos exponen solo: rol · texto · timestamp

### Modelo de datos

Ver tabla en la sección en inglés. Un enlace es válido solo si: no está revocado AND no ha expirado AND view_count < límite.

### Endpoints

Ver tabla en la sección en inglés. El endpoint público devuelve 410 Gone si el enlace expiró, fue revocado, no existe o superó el límite de vistas.

### Limitaciones conocidas

- Sin UI para listar o revocar enlaces activos; la revocación requiere la API o DevTools
- El límite de vistas no se puede configurar desde la UI (por defecto ilimitado)

### Tests

15 tests: creación · inmutabilidad del snapshot · expiración · revocación · conteo de vistas · exclusión de campos sensibles · autorización

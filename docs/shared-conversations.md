# Conversaciones compartidas

Última actualización: 2026-08-05.

## Propósito

Permite compartir una conversación completa con Sity mediante un enlace público
de solo lectura que caduca automáticamente. El enlace es una **foto fija** de la
conversación en el momento de compartir: los mensajes posteriores nunca
aparecen en el enlace ya generado.

## Decisiones de privacidad (motivación)

La funcionalidad se diseñó con el mismo rigor que el aislamiento de sesiones
(ver bugs resueltos 2026-08-04). Las invariantes clave son:

- **Sin `session_id` expuesto**: la respuesta pública nunca incluye el ID de sesión
  real ni ningún metadato de identidad del propietario.
- **Instantánea, no ventana en vivo**: `snapshot_json` es una copia JSON fija.
  Aunque el usuario siga hablando con Sity tras compartir, el enlace no cambia.
- **ID no enumerable**: `share_id` es `uuid4().hex` (32 caracteres hex aleatorios),
  no un entero autoincremental. Un atacante no puede iterar IDs para descubrir
  conversaciones ajenas.
- **Guests excluidos**: los invitados no tienen identidad persistente, por lo que
  no pueden crear enlaces. La ruta `POST /chat/share` exige usuario autenticado.
- **Solo metadatos mínimos en la respuesta pública**: `role`, `text`, `created_at`
  por mensaje. Nunca `tone_meta`, `speaker_id`, `identity_evidence_json`,
  `dataset_source` ni similares.

## Modelo de datos — `SharedConversation`

Tabla SQLite persistente en `data/app.db`.

```
id              TEXT  PK  — uuid4().hex (32 chars, not sequential)
session_id      TEXT      — sesión propietaria (no se expone públicamente)
snapshot_json   TEXT      — JSON [{role, text, created_at}] — copia fija
created_at      DATETIME
expires_at      DATETIME  — default: created_at + 7 días (configurable)
max_views       INT?      — NULL = sin límite de vistas
view_count      INT       — cuántas veces se ha accedido
revoked_at      DATETIME? — NULL = no revocado; != NULL = revocado manualmente
```

Un enlace es válido si: `revoked_at IS NULL AND now < expires_at AND (max_views IS NULL OR view_count < max_views)`.

## Endpoints

### `POST /chat/share`

Requiere autenticación (non-guest). Crea la instantánea y devuelve el enlace.

**Request:** sin body. La sesión se determina por la cookie `sity_session`.

**Response (201):**
```json
{
  "share_id": "a1b2c3d4...",
  "url": "https://sity.aletm.com/shared/a1b2c3d4...",
  "expires_at": "2026-08-12T14:30:00+00:00"
}
```

**Errores:**
- `401` — invitado sin sesión autenticada.

---

### `GET /shared/{share_id}`

**Público, sin autenticación.** Valida el estado del enlace, incrementa `view_count`,
devuelve la instantánea filtrada.

**Response (200):**
```json
{
  "share_id": "a1b2c3d4...",
  "messages": [
    { "role": "user",  "text": "Hola", "created_at": "2026-08-05T10:00:00+00:00" },
    { "role": "sity",  "text": "Hola, ¿qué tal?", "created_at": "2026-08-05T10:00:01+00:00" }
  ],
  "created_at": "2026-08-05T10:05:00+00:00",
  "expires_at": "2026-08-12T10:05:00+00:00",
  "view_count": 1
}
```

**Errores:**
- `410` — enlace caducado, revocado, no encontrado, o límite de vistas superado.
  (Se usa 410 Gone en lugar de 404 para indicar que existió pero ya no es accesible.)

---

### `DELETE /chat/share/{share_id}`

Requiere autenticación. Solo el propietario puede revocar. Idempotente.

**Response (200):**
```json
{ "ok": true, "share_id": "a1b2c3d4..." }
```

**Errores:**
- `401` — invitado.
- `404` — ID no encontrado o no es propietario.

## Configuración

```yaml
# config/default_config.yaml
sharing:
  default_expiry_days: 7
```

## Frontend

### Botón "Compartir conversación"

Disponible en el menú (tres puntos) del chat, solo para usuarios autenticados
(no aparece para invitados). Al pulsar:

1. Llama `POST /chat/share` con las credenciales del usuario.
2. Muestra un modal con el enlace generado y un botón "Copiar enlace".
3. Indica la fecha de caducidad.

### Vista pública `/shared/{id}`

Si `window.location.pathname` coincide con `/shared/<32-hex-chars>` al cargar la
app, se renderiza `SharedConversationView` directamente (el mismo mecanismo que
`/reset-password`): sin login, sin chrome de la app, sin campo de texto, sin acceso
a tools ni a la sesión real. Solo la lista de mensajes y los metadatos del enlace.

## Tests — `tests/test_shared_conversations.py`

15 tests:
- `TestCreateShare` — happy path, guest rechazado, conversación vacía permitida.
- `TestGetShared` — snapshot correcto, inmutabilidad tras nuevos mensajes,
  enlace caducado/revocado/max_views, contador de vistas, sin metadatos sensibles,
  ID inexistente devuelve 410.
- `TestRevokeShare` — propietario puede revocar (enlace deja de funcionar),
  no-propietario recibe 404, guest recibe 401, doble revocación idempotente.

## Limitaciones conocidas

- **No hay pantalla de gestión de enlaces**: el usuario no puede ver ni revocar
  desde la UI todos sus enlaces activos. Se puede revocar con `DELETE /chat/share/{id}`
  manualmente (o desde DevTools), pero no hay un listado frontend todavía.
- **max_views no configurable desde la UI**: el valor por defecto es `null` (sin límite).
  Para forzar un límite de vistas hay que hacerlo directamente en la base de datos.
  Se puede añadir como parámetro de `POST /chat/share` en el futuro.

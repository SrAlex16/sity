# Fase 6: Integraciones self-service por usuario — Diseño

Fecha: 2026-08-04. Estado: **diseño aprobado**, implementación en curso.

Referencia en docs/state.md → "Mejoras pendientes → Integraciones self-service por usuario".

---

## Resumen ejecutivo

Actualmente Google (Gmail/Calendar/Drive) y Spotify funcionan con un único token
global en `data/google_token.json` y `data/spotify_token.json`, vinculado al Admin.
Cualquier User autenticado que pida "reproduce música" usa las credenciales de Admin
sin saberlo — y sin poder conectar las suyas propias.

El objetivo de la Fase 6 es que cada usuario (`user_id` propio) pueda autorizar sus
propias cuentas de Google y Spotify desde la PWA, y que las herramientas del backend
usen automáticamente las credenciales del usuario activo. Home Assistant queda fuera
del alcance (no es OAuth estándar; sigue controlado desde Admin via `.env`).

---

## 1. Modelo de datos: `UserIntegration`

Nueva tabla SQLModel en `backend/app/memory/models.py`, junto a `User` y `PasswordResetToken`.

```python
class UserIntegration(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str              # "google" | "spotify"
    encrypted_credentials: str # JSON cifrado con Fernet (ver §3)
    scopes: str                # scopes autorizados, guardados para auditoría
    connected_at: datetime
    last_refreshed_at: datetime | None = None
    is_active: bool = Field(default=True)

    # Constraint de unicidad: un usuario solo puede tener una fila activa por proveedor
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
```

**`encrypted_credentials` por proveedor:**

- **Google**: string resultado de `creds.to_json()` de `google.oauth2.credentials.Credentials`,
  que incluye `token`, `refresh_token`, `token_uri`, `client_id`, `client_secret`, `scopes`.
- **Spotify**: dict JSON con `access_token`, `refresh_token`, `expires_at`, `client_id`,
  `client_secret` — mismo formato que el actual `spotify_token.json`.

Ambos son strings JSON cifrados simétricamente antes de guardar en SQLite.

---

## 2. Flujo OAuth web

### Diferencia con el flujo actual (CLI)

El flujo actual usa `urn:ietf:wg:oauth:2.0:oob` (Google) o `http://127.0.0.1:8888/callback`
(Spotify) — ambos pensados para terminal interactiva. El nuevo flujo usa un **callback
HTTP real** alojado en el propio backend de Sity.

### Endpoints nuevos: `GET /auth/integrations/{provider}/connect`

Inicia el flujo. Requiere sesión de usuario (`get_current_user`, no guest).

1. Genera un `state` firmado: `HMAC-SHA256(SITY_ENCRYPTION_KEY, f"{user_id}:{provider}:{ts}")`,
   codificado en base64. Incluye timestamp para expiración (10 min).
2. Construye la URL de autorización del proveedor:
   - Google: `InstalledAppFlow` con `redirect_uri=https://sity.aletm.com/auth/integrations/google/callback`
   - Spotify: URL de `accounts.spotify.com/authorize` con mismo redirect
3. Responde `{"auth_url": "..."}` — el frontend abre la URL en pestaña nueva o
   `window.location.href`.

**Redirect URI a registrar** (configuración única en consola del proveedor):
- `https://sity.aletm.com/auth/integrations/google/callback`
- `https://sity.aletm.com/auth/integrations/spotify/callback`

### Endpoint callback: `GET /auth/integrations/{provider}/callback?code=...&state=...`

1. Valida `state`: verifica HMAC, extrae `user_id`, comprueba que no ha expirado.
   Si falla → respuesta HTML con mensaje claro y accionable:
   `"El enlace de autorización caducó o no es válido. Vuelve a intentarlo desde Ajustes → Integraciones."`.
   No un 400 genérico sin contexto — el usuario llega aquí desde el navegador, sin
   capa de frontend que interprete el código de error.
2. Intercambia `code` por tokens llamando a la API del proveedor.
3. Cifra las credenciales con Fernet (§3).
4. Upsert en `UserIntegration` (insert o update si ya existe fila para ese usuario+proveedor).
5. Redirige a `https://sity.aletm.com/settings/integrations?connected={provider}` — la PWA
   muestra un banner de confirmación.

### Endpoint desconexión: `DELETE /auth/integrations/{provider}`

Pone `is_active=False` en la fila de `UserIntegration` del usuario activo. No borra
la fila — se conserva el historial de auditoría de qué integraciones ha tenido cada
usuario (cuándo se conectó, cuándo se desconectó, cuándo se hizo el último refresh).

El token no se revoca en el proveedor — la revocación es responsabilidad del usuario
desde la cuenta del proveedor si lo necesita.

**Por qué esto es distinto de `DELETE /auth/me`:** el borrado real de cuenta
(`DELETE /auth/me`) elimina la fila `User` porque es el acto explícito e irreversible
de abandonar el servicio, y la coherencia de los datos de ese usuario deja de importar.
La desconexión de una integración, en cambio, es una operación reversible y recurrente
— el usuario puede volver a conectar mañana. Usar `is_active=False` aquí no es
inconsistencia respecto a `DELETE /auth/me`; son decisiones correctas en contextos
distintos: borrado real cuando la entidad muere, soft-delete cuando la entidad vive
pero una relación se desactiva temporalmente.

### Pantalla frontend "Integraciones" (concepto, sin implementación)

Nueva pestaña en Ajustes (Settings). Para cada proveedor:

```
┌─────────────────────────────────────────────────┐
│ Google (Gmail · Calendar · Drive)               │
│ Estado: Conectado como alex@gmail.com ✓          │
│                                          [Desconectar] │
├─────────────────────────────────────────────────┤
│ Spotify                                         │
│ Estado: No conectado                             │
│                                          [Conectar]    │
└─────────────────────────────────────────────────┘
```

El botón "Conectar" llama a `GET /auth/integrations/{provider}/connect` y redirige
al usuario a la URL devuelta. El callback actualiza el estado en DB y la PWA recarga
el estado de conexión al volver.

---

## 3. Cifrado de tokens en reposo

### Elección: Fernet (cryptography)

Fernet es cifrado simétrico autenticado (AES-128-CBC + HMAC-SHA256). Es reversible
(necesario: los tokens deben poder descifrarse para usarse) y está incluido en
`cryptography`, que ya está en el stack.

bcrypt no aplica aquí porque es unidireccional (diseñado para passwords).

### Implementación

Nuevo módulo `backend/app/auth/encryption.py`:

```python
import os
from cryptography.fernet import Fernet

def _get_fernet() -> Fernet:
    key = os.environ.get("SITY_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("SITY_ENCRYPTION_KEY no está configurada")
    return Fernet(key.encode())

def encrypt_str(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_str(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
```

`SITY_ENCRYPTION_KEY` se genera una vez con `Fernet.generate_key().decode()` y se
añade al `.env`. Es una clave base64url de 32 bytes. Añadir a `.env.example`.

### Chequeo de arranque: protección contra clave incorrecta o rotada

Al arrancar el backend (en el mismo punto donde ya se ejecutan otras comprobaciones
de arranque, como la creación de tablas o el seeder de Admin), se añade una
verificación fail-fast:

```python
def _verify_encryption_key(session: Session) -> None:
    """Falla al arrancar si SITY_ENCRYPTION_KEY no descifra los datos existentes."""
    row = session.exec(select(UserIntegration)).first()
    if row is None:
        return  # tabla vacía — primer despliegue, nada que verificar
    try:
        decrypt_str(row.encrypted_credentials)
    except Exception:
        raise RuntimeError(
            "SITY_ENCRYPTION_KEY no coincide con los datos cifrados existentes en "
            "UserIntegration — revisa el .env. El backend no puede arrancar con una "
            "clave incorrecta o rotada."
        )
```

**Por qué fail-fast en el arranque:** si la clave es incorrecta, los fallos llegarían
dispersos y confusos más tarde, en producción, para usuarios reales. El arranque es
el momento donde Alex está mirando activamente los logs — es el mejor punto para
detectar el problema. Si la tabla está vacía (primer despliegue), el chequeo se salta
sin más.

### Limitaciones conocidas en v1

- **Rotación de clave**: si `SITY_ENCRYPTION_KEY` cambia, todas las filas de
  `UserIntegration` quedan inaccesibles. En v1 no hay rotación automática — documentar
  como requisito operativo: nunca borrar la clave si hay datos en DB.
- **Backup**: la clave debe incluirse en el backup del `.env`, junto a `data/app.db`.

---

## 4. Modificación de tool handlers para credenciales por usuario

### Patrón de acceso a `user_id` en un handler

Los handlers ya tienen acceso a `ctx.executor.session_id` y `ctx.executor.session`
(Session de SQLModel). El `user_id` se extrae así:

```python
def _user_id_from_ctx(ctx: ToolContext) -> int | None:
    sid = ctx.executor.session_id
    if sid.startswith("user:"):
        return int(sid.removeprefix("user:"))
    return None  # guest o sesión sin usuario
```

### Nueva función en cada `*_auth.py`: `load_user_credentials(user_id, session)`

**`google_auth.py`:**

```python
def load_user_credentials(user_id: int, session: Session) -> Credentials | None:
    row = session.exec(
        select(UserIntegration)
        .where(UserIntegration.user_id == user_id)
        .where(UserIntegration.provider == "google")
        .where(UserIntegration.is_active == True)
    ).first()
    if not row:
        return None

    creds_json = decrypt_str(row.encrypted_credentials)
    creds = Credentials.from_authorized_user_info(json.loads(creds_json), SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            row.encrypted_credentials = encrypt_str(creds.to_json())
            row.last_refreshed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(row)
            session.commit()
        except Exception:
            return None

    return creds if creds.valid else None
```

**`spotify_auth.py`:** equivalente — carga dict JSON, aplica lógica de refresh del
token ya existente en `_do_refresh()`, actualiza `encrypted_credentials` en DB.

### Modificación de handlers

Los handlers de Google y Spotify reemplazan la llamada a `load_credentials()` (global)
por una secuencia:

```python
user_id = _user_id_from_ctx(ctx)
if user_id is None:
    return ToolExecutionResult(ok=False, text="Esta herramienta requiere una cuenta de usuario.")

creds = load_user_credentials(user_id, ctx.executor.session)
if creds is None:
    return ToolExecutionResult(
        ok=False,
        text="No tienes Google conectado. Ve a Ajustes → Integraciones y conecta tu cuenta."
    )
# ... resto del handler sin cambios
```

Mismo patrón para Spotify con texto equivalente.

### Impacto en tests

Los tests existentes de herramientas Google/Spotify que mockean `load_credentials()`
tendrán que mockear `load_user_credentials()` en su lugar. Se puede hacer con
`monkeypatch` de la función en el módulo del handler, sin cambiar la estructura
de tests.

---

## 5. Comportamiento cuando el usuario no tiene la integración conectada

El handler devuelve un `ToolExecutionResult(ok=False, text="...")` con un mensaje
claro y accionable. El modelo lo recibe como resultado de tool y lo narra al usuario.

Ejemplos de mensajes por proveedor:

| Proveedor | Mensaje |
|-----------|---------|
| Google    | "No tienes Google conectado. Ve a Ajustes → Integraciones y conecta tu cuenta para acceder a Gmail, Calendar y Drive." |
| Spotify   | "No tienes Spotify conectado. Ve a Ajustes → Integraciones y conecta tu cuenta para controlar la reproducción." |
| (guest)   | "Esta herramienta no está disponible para usuarios invitados. Crea una cuenta para conectar tus integraciones." |

El modelo no intenta reintentar ni ofrecer alternativas — simplemente transmite el
mensaje al usuario. No se necesita lógica especial en el prompt del sistema.

---

## 6. Compatibilidad Admin y migración

### Situación actual

Admin tiene tokens globales en `data/google_token.json` y `data/spotify_token.json`.
Estos archivos son leídos por `load_credentials()` sin ninguna referencia a `user_id`.

### Estrategia recomendada: migración por script (opción A)

Script `scripts/migrate_admin_integrations.py` (a ejecutar una sola vez después de
desplegar la Fase 6):

1. Lee `data/google_token.json` y `data/spotify_token.json`.
2. Cifra el contenido con Fernet usando `SITY_ENCRYPTION_KEY`.
3. Inserta filas en `UserIntegration` con `user_id=1` (Admin) para cada proveedor.
4. Mueve los archivos originales a `data/legacy/` (no los borra — rollback posible).

Tras la migración, `load_credentials()` global ya no se usa en producción.

**Por qué no "fallback permanente":** mantener dos rutas de acceso a credenciales
(archivo + DB) duplica la lógica de refresh, complica los tests y crea ambigüedad
sobre cuál es la fuente de verdad. Un script de migración es más limpio.

### Opción B: compatibilidad permanente (no recomendada)

Añadir en `load_user_credentials()` un fallback a los archivos globales cuando
`user_id == 1`. Solo considerarla si la migración presenta riesgos (por ejemplo,
si Admin tiene tokens distintos para Google y Spotify que no se pueden re-autorizar
fácilmente).

---

## 7. Casos de validación

### Dos usuarios con el mismo proveedor

Normal — cada `UserIntegration` está indexado por `(user_id, provider)`.
User A puede tener cuenta de Spotify A y User B puede tener cuenta de Spotify B,
con tokens completamente independientes. El refresh de uno no afecta al otro.

### Desconexión / revocación

- `DELETE /auth/integrations/{provider}` pone `is_active=False` en la fila de DB (no la borra).
- `load_user_credentials()` filtra por `is_active == True` → devuelve `None` → mensaje claro al usuario.
- El token permanece válido en el proveedor hasta que expire o el usuario lo revoque
  desde la consola del proveedor. Esto es aceptable en v1 — la mayoría de servicios
  expiran access tokens en < 1h.
- Re-conectar actualiza la fila existente (upsert): `is_active=True`, credenciales nuevas,
  `connected_at` actualizado.

### Refresh de token por usuario

Cada llamada a `load_user_credentials()` evalúa `expires_at` del token del usuario
activo. Si expira, llama a la API del proveedor con el `refresh_token` del usuario
y actualiza su propia fila en DB. El refresh de User A no escribe en la fila de User B.

### Usuarios Guest

`_user_id_from_ctx()` devuelve `None` para `session_id` que comienza con `"guest:"`.
Todos los handlers de integraciones devuelven el mensaje de "no disponible para invitados"
sin llegar a consultar la DB.

### Token caducado sin refresh_token (edge case)

Si `creds.refresh_token` es `None` (puede ocurrir en Google si el usuario revocó el
acceso desde su cuenta), `load_user_credentials()` devuelve `None`. El usuario
recibe el mensaje de "no conectado" y debe volver a pasar por el flujo OAuth.

---

## Dependencias y prerrequisitos

| Elemento | Acción necesaria |
|----------|-----------------|
| `cryptography` | Ya en el stack (`pip show cryptography`) — sin cambios |
| `SITY_ENCRYPTION_KEY` | Generar y añadir a `.env` + `.env.example` |
| Google Cloud Console | Añadir redirect URI de callback |
| Spotify Developer Dashboard | Añadir redirect URI de callback |
| Migración DB | `alembic revision` (o migración manual) para la tabla `UserIntegration` |
| Script migración Admin | `scripts/migrate_admin_integrations.py` |

---

## Orden de implementación sugerido

1. `backend/app/auth/encryption.py` — cifrado Fernet (sin DB, testeable aislado)
2. Modelo `UserIntegration` + migración de esquema
3. Endpoints `/auth/integrations/*` (connect, callback, delete) con tests
4. `load_user_credentials()` en `google_auth.py` y `spotify_auth.py`
5. Adaptación de handlers (reemplazar `load_credentials()` global)
6. Script de migración Admin
7. Frontend: pantalla "Integraciones" en Settings

---

## Fuera de alcance: Home Assistant

Home Assistant no usa OAuth estándar — usa un Long-Lived Token en `.env`
(`HA_TOKEN`). Mientras HA sea una instalación compartida en la red local de Alex
(no hay una cuenta HA por usuario), este token permanece global y Admin-only.
Si en el futuro se contemplan cuentas HA por usuario, requeriría diseño separado.

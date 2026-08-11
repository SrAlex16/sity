# Sistema de autenticación y roles

Última actualización: 2026-08-11.

Implementación de las Fases 1 y 2 del sistema de usuarios de Sity:
tabla `User`, hashing de contraseñas, sesiones JWT en cookie, siete
endpoints de auth, dependencia `get_current_user` reutilizable,
seeding del Admin único (Fase 1); y migración de `session_id="default"`
a session_ids reales por usuario, aislamiento completo de historial de
chat entre usuarios y Guests (Fase 2). El repo de Sity es público en
el portfolio de Alex — estas fases protegen el sistema antes de exponer
las rutas de chat/tools al sistema de roles en fases posteriores.

## Fase 2 — Session IDs reales (completada 2026-07-28)

Toda la capa de chat usa ahora un `session_id` real en vez de la
constante `"default"` hardcodeada.

### Estrategia de session_id

| Rol | session_id | Cookie |
|---|---|---|
| User/Admin | `f"user:{user_id}"` | —, estable entre sesiones |
| Guest | `f"guest:{uuid4().hex}"` | `sity_guest_session` (session cookie sin Max-Age) |

**Guest UUID:** generado en el backend en la primera petición que pasa
por `get_current_user`. Se almacena en la cookie `sity_guest_session`
(httpOnly, SameSite=lax, sin Max-Age → dura hasta cerrar la pestaña).
Cada pestaña/navegador/TestClient nuevo tiene su propio UUID.

**Guest cookie al hacer login/register:** `routes_auth.py` llama a
`response.delete_cookie("sity_guest_session")` al completar login o
register con éxito. El historial del Guest NO se migra a la cuenta de
usuario — es efímero por diseño.

### Cascada de cambios (Fase 2)

- `app/auth/dependencies.py` — `CurrentUser.session_id`, cookie guest
- `app/api/routes_auth.py` — borra `sity_guest_session` en login/register
- `app/chat/turn_context.py` — `TurnContext.session_id` + `build_turn_context(session_id=...)`
- `app/chat/chat_persistence.py` — `get_or_create_chat_session(session, session_id)`, `save_chat_message(..., session_id=...)`, `get_recent_db_messages(session, session_id, ...)`
- `app/chat/turn_persistence.py` — `ChatTurnPersistence(session, capture_ctx, capture_svc, session_id)`
- `app/chat/ai_turn_prep.py` — usa `ctx.session_id` para task_context y prompt_context
- `app/chat/ai_orchestrator.py` — `_BG_SESSION_ID` eliminado; `ctx.session_id` en closure de `_detach_tool`
- `app/core/tool_executor.py` — `ToolExecutor(session, session_id)`
- `app/actions/confirmation_manager.py` — `ConfirmationManager(session, session_id)`, `_last_sity_message_references_action` usa `self._session_id`
- `app/chat/pre_ai_flow.py` — `ConfirmationManager(session, ctx.session_id)`
- `app/api/routes_chat.py` — inyecta `get_current_user`, pasa `session_id` al thread de fondo
- `app/api/routes_debug.py` — `dataset_stats` filtra por `current.session_id`
- Todos los handlers de tools — `ConfirmationManager(ctx.executor.session, ctx.executor.session_id)`

### Migración de datos

```bash
# Desde la raíz del proyecto, con venv activo:
python scripts/migrate_default_session.py --dry-run   # preview
python scripts/migrate_default_session.py              # ejecutar
```

Migra `session_id="default"` → `session_id="user:{admin_id}"`.
Idempotente: seguro re-ejecutar si se interrumpe.

### Tests

`tests/test_session_isolation.py` — 10 tests:
- Guest obtiene UUID único y estable
- Dos Guests no se ven el historial
- Dos usuarios no se ven el historial
- Cookie guest borrada en login/register
- Mensajes guardados bajo session_id correcto en DB

## Roles — tres, fijos

| Rol | Tiene fila en `User` | Persistencia | Límite de uso |
|---|---|---|---|
| **Guest** | No | Efímera (solo la pestaña abierta) | 20 msgs/día por IP (Fase 3) |
| **User** | Sí | Sesión persistente (cookie JWT) | 100 msgs/día (Fase 3) |
| **Admin** | Sí (`role="admin"`) | Sesión persistente | Sin límite |

**Por qué Guest no persiste nada:** la sesión de un Guest es
completamente efímera — no hay `session_id` persistente, no hay
historial entre visitas, y recargar la página equivale a empezar de
cero. El conteo de mensajes se hace por `session_id` de pestaña
(cookie `sity_guest_session`) en la tabla `DailyMessageUsage` —
se borra automáticamente al día siguiente (el guard resetea el
contador cuando detecta un cambio de fecha). Nada que borrar en GDPR.

**Por qué Admin es único y fijo:** Sity es un asistente personal de
Alex, no una plataforma multi-tenant. Tener un Admin configurable o
promoable añadiría complejidad de gestión de privilegios sin ningún
caso de uso real. El Admin se crea en `seed_admin()` desde env vars y
no hay ningún endpoint que cambie el rol de un User. Si el Admin ya
existe, el seeder es un no-op (idempotente).

**Admin no tiene privilegios especiales sobre la sesión de otros
usuarios:** la configuración de personalidad (sliders) es por sesión,
y cada usuario — incluido Admin — solo controla la suya.

## Modelo de datos

### `User`

```
id            INTEGER PK autoincrement
email         TEXT    unique, indexed
password_hash TEXT    bcrypt hash (bcrypt 5.x, 12 rondas por defecto)
role          TEXT    "user" | "admin"
is_active     BOOLEAN default True
created_at    DATETIME utc
last_login_at DATETIME nullable
```

`last_login_at` se actualiza en cada login exitoso. Útil para
auditoría de seguridad (detectar cuentas inactivas) sin añadir
complejidad.

### `PasswordResetToken`

```
id         INTEGER PK autoincrement
token      TEXT    UUID v4, unique, indexed
user_id    INTEGER indexed (FK lógico a User)
expires_at DATETIME naive UTC (TTL 1h)
used_at    DATETIME nullable
created_at DATETIME utc
```

Token de un solo uso con TTL de 1 hora. `used_at` no nulo = token ya
consumido. Los tokens no se eliminan automáticamente (no es necesario
para la seguridad — la comprobación de `expires_at` y `used_at` es
suficiente). Una tarea de limpieza periódica se puede añadir después.

**Por qué un token en vez de una contraseña nueva por correo:** enviar
una contraseña por correo expondría una contraseña válida en texto
plano en el historial del servidor de correo del proveedor, en el
historial del cliente de email del usuario, y en cualquier gateway
intermedio. El token sigue siendo un secreto de un solo uso y con TTL
corto, y la contraseña se establece en el dispositivo del usuario.

## Hashing de contraseñas

`bcrypt` 5.x directamente (sin passlib — incompatibilidad conocida
de passlib 1.7.4 con bcrypt ≥ 5.0). Implementado en
`app/auth/hashing.py`. Factor de coste por defecto del módulo `bcrypt`
(12 rondas), lo que da ~100-200ms de cómputo en la Pi — suficiente
para resistir fuerza bruta offline.

**Política de contraseña:** ≥ 8 caracteres, al menos una mayúscula,
una minúscula y un dígito. El error de validación es un mensaje
explícito en castellano para que el frontend lo muestre como popup
directamente, sin necesidad de parsear códigos de error.

## Sesiones JWT

- **Librería:** PyJWT 2.10.1, algoritmo HS256.
- **Payload:** `{"sub": "<user_id>", "role": "<role>", "exp": <timestamp>}`.
- **Secreto:** env var `SITY_JWT_SECRET`. Si no está definido, se usa
  un fallback inseguro y se loguea un WARN en cada llamada. Para
  producción, generar con `openssl rand -hex 32` y añadir al `.env`.
- **Cookie:** nombre `sity_session`, `HttpOnly`, `SameSite=Lax`,
  `Max-Age=72h`, `Path=/`.
- **`Secure`:** controlado por `SITY_COOKIE_SECURE` (default `true`).
  La instalación con Caddy + Cloudflare Tunnel sirve todo por HTTPS,
  así que `Secure=true` es seguro en producción. En tests y desarrollo
  local HTTP, se pone a `false` (ya configurado en `tests/conftest.py`).
- **Sin refresh token en Fase 1:** la sesión dura 72 horas y el
  usuario vuelve a hacer login al expirar. Si en el futuro se necesita
  renovación transparente, se añade un refresh token en Fase posterior.

## Endpoints

| Método | Ruta | Auth requerida | Descripción |
|---|---|---|---|
| POST | `/auth/register` | No | Registro libre (solo `role="user"`) |
| POST | `/auth/login` | No | Email + password → cookie de sesión |
| POST | `/auth/logout` | No (idempotente) | Borra la cookie |
| GET | `/auth/me` | No | Usuario actual o `{"role":"guest"}` |
| POST | `/auth/forgot-password` | No | Genera token de recuperación |
| POST | `/auth/reset-password` | No | Valida token + cambia contraseña |
| DELETE | `/auth/me` | Sí (User/Admin) | Borra cuenta y datos (ver limitación Fase 1) |

### Anti-enumeración en forgot-password

`POST /auth/forgot-password` siempre devuelve 200, tanto si el email
existe como si no. Esto impide que un atacante use el endpoint para
descubrir qué emails están registrados. Cuando el email existe y la
cuenta está activa, se genera un token y se llama a
`send_password_reset_email`.

### Limitación temporal DELETE /auth/me

En Fase 1, solo se elimina la fila de `User`. Los `ChatMessage`,
`Setting` (task_context, previous_context de Spotify, etc.) asociados
a esta cuenta no se borran todavía — la asociación entre `session_id`
y `user_id` se establece en Fase 2. El código tiene un TODO marcado
explícitamente en `routes_auth.py`.

## Dependencia de auth (`get_current_user`)

`app/auth/dependencies.py` expone `CurrentUser` y `get_current_user`:

```python
from app.auth.dependencies import CurrentUser, get_current_user

@router.get("/protected")
def protected(current: CurrentUser = Depends(get_current_user)):
    if current.is_guest:
        raise HTTPException(status_code=401, detail="Autenticación requerida")
    if not current.is_admin:
        raise HTTPException(status_code=403, detail="Acceso restringido")
    ...
```

`get_current_user` **nunca lanza excepción** — siempre resuelve a
un `CurrentUser`. Un token inválido, expirado o ausente devuelve un
Guest. Las decisiones de acceso son responsabilidad del endpoint.

`CurrentUser` tiene: `role`, `user_id`, `user`, `is_authenticated`,
`is_admin`, `is_guest`.

**Fase 1:** la dependencia no está enganchada a `/chat/*`, `/events/*`
ni ninguna ruta existente — solo existe y se demuestra con tests.
El enganche a las rutas existentes ocurre en Fase 3.

## reCAPTCHA v3

`RegisterRequest` y `LoginRequest` envían un campo `recaptcha_token: str`
(default `""`). El backend lo verifica en `app/auth/recaptcha.py` contra
`https://www.google.com/recaptcha/api/siteverify`.

**Modo bypass:** si `RECAPTCHA_SECRET_KEY` no está configurada, la función
devuelve `True` e imprime un WARN en el log. Esto permite que el sistema
funcione en desarrollo y tests sin claves reales.

**Configuración para producción:**

1. Ir a <https://www.google.com/recaptcha/admin> y crear un sitio de tipo
   **reCAPTCHA v3**.
2. Copiar las dos claves generadas y añadirlas al `.env` de la **raíz del repo**
   (`~/projects/sity/.env`), no en `mobile/.env`:
   - `VITE_RECAPTCHA_SITE_KEY=<site_key>` — el prefijo `VITE_` es obligatorio
     para que Vite lo exponga al bundle; sin él, Vite ignora la variable
     silenciosamente aunque esté en el archivo.
   - `RECAPTCHA_SECRET_KEY=<secret_key>` — la usa el backend directamente.
3. Opcionalmente ajustar el umbral de score (default 0.5):
   `RECAPTCHA_SCORE_THRESHOLD=0.5` en `.env`.
4. Reconstruir el frontend: `npm run build` en `mobile/` (o `./deploy.sh`).
   El valor de `VITE_RECAPTCHA_SITE_KEY` se compila en el bundle en tiempo de
   build; un rebuild es obligatorio tras cualquier cambio en la clave.

**Nota de configuración Vite:** `mobile/vite.config.ts` tiene `envDir: '../'`
para que Vite lea el `.env` de la raíz del repo en vez de buscar en `mobile/`.
Sin esto, Vite usaría su comportamiento por defecto (buscar en el directorio
donde está `vite.config.ts`) y nunca encontraría las variables.

El widget v3 es invisible — el usuario no ve ningún reto. Si `VITE_RECAPTCHA_SITE_KEY`
no está en el bundle, `getRecaptchaToken()` devuelve `""` y el backend lo acepta
por bypass (sin marca de agua visible en login/registro).

## Email de recuperación

`app/auth/email_stub.py` implementa `send_password_reset_email`. Sin
SMTP configurado, el enlace de recuperación se loguea a nivel WARN en
`data/logs/app-YYYY-MM-DD.jsonl` para que Alex pueda usarlo
manualmente. Para activar el envío real:

```
SITY_SMTP_HOST=smtp.gmail.com
SITY_SMTP_PORT=587
SITY_SMTP_USER=...
SITY_SMTP_PASSWORD=...
SITY_SMTP_FROM_EMAIL=no-reply@sity.aletm.com
SITY_BASE_URL=https://sity.aletm.com
```

El bloque de código SMTP está preparado en el stub como comentario.

## Admin seeder

`app/auth/admin_seeder.py` — llamado desde `on_startup` de `main.py`.

```env
SITY_ADMIN_EMAIL=tu_email@ejemplo.com
SITY_ADMIN_PASSWORD=contraseña_segura
```

Si las vars no están definidas, no se seedea nada (no es un error).
Si el admin ya existe, el seeder no hace nada (idempotente).

## Configuración

```yaml
# config/default_config.yaml
auth:
  jwt_expiry_hours: 72
  user_daily_message_limit: 100      # UserMessageGuard en pre_ai_flow; 0 = desactivado
  guest_daily_message_limit: 20      # igual; reseteo automático al cambio de día
  guest_ip_rate_limit_per_hour: 30   # GuestIPRateLimiter en routes_chat; 0 = desactivado; in-memory
  password_reset_expiry_minutes: 60
  registration_open: true
```

Variables de entorno relacionadas con seguridad:

```
SITY_MAINTENANCE_MODE=true   # bloquea Guest/User con 503; Admin pasa siempre
```

Variables de entorno (van en `.env`):

```
SITY_JWT_SECRET=<hex 32 bytes — openssl rand -hex 32>
SITY_ADMIN_EMAIL=...
SITY_ADMIN_PASSWORD=...
SITY_COOKIE_SECURE=true   # false solo en dev HTTP local
SITY_BASE_URL=https://sity.aletm.com
```

## Módulos nuevos

```
backend/app/auth/
├── __init__.py
├── hashing.py            # hash_password, verify_password (bcrypt)
├── jwt_utils.py          # create_token, decode_token (PyJWT HS256)
├── dependencies.py       # CurrentUser, get_current_user
├── email_stub.py         # send_password_reset_email (stub con TODO SMTP)
├── admin_seeder.py       # seed_admin() llamado en startup
├── ip_rate_limiter.py    # GuestIPRateLimiter, get_real_client_ip; singleton por proceso
└── maintenance.py        # MaintenanceModeMiddleware (pure ASGI)
backend/app/api/
├── routes_auth.py        # 7 endpoints /auth/*
└── schemas_auth.py       # RegisterRequest, LoginRequest, MeResponse, ...
```

## Modo mantenimiento / kill-switch de acceso público (Punto 10 — 2026-08-05)

### Activar/desactivar

```bash
# Activar: añadir al .env
SITY_MAINTENANCE_MODE=true

# Aplicar sin rebuild (solo reiniciar backend):
./deploy.sh

# Desactivar: eliminar o comentar la línea en .env, luego ./deploy.sh
```

### Comportamiento

| Rol | Acceso durante mantenimiento |
|---|---|
| Admin | Sin restricciones — todo pasa |
| User | 503 en todos los endpoints salvo los exentos |
| Guest | 503 en todos los endpoints salvo los exentos |

**Endpoints siempre exentos:**
- `GET /health` — checks de infraestructura
- `POST /auth/login` — Admin puede autenticarse aunque no tenga sesión activa
- `POST /auth/logout` — cierre de sesión graceful

### Implementación

- **`RuntimeConfig.maintenance_mode`** — leído de `SITY_MAINTENANCE_MODE` en `runtime_config.py`
- **`MaintenanceModeMiddleware`** — middleware ASGI puro en `auth/maintenance.py`; registrado después de `CORSMiddleware` en `main.py` (inner, para que CORS añada cabeceras al 503)
- Detección de Admin: lee cookie `sity_session` de los headers ASGI crudos, decodifica el JWT
- Respuesta: `HTTP 503` + `{"detail": "Sity está en mantenimiento. Vuelve más tarde."}`

### Frontend

- `useAuth.ts` detecta 503 en `fetchMe()` → estado `maintenance: boolean`
- `App.tsx` muestra `<MaintenanceScreen />` para Guest/User durante mantenimiento
- El botón "acceder como administrador" en `<MaintenanceScreen />` abre `<LoginScreen />`; si se loguea como Admin, `fetchMe()` vuelve a funcionar (el middleware deja pasar `/auth/login`)

### Tests

`tests/test_maintenance_mode.py` — 16 tests:
- Modo OFF → comportamiento normal para todos
- Modo ON: Admin pasa (/auth/me, /health, /settings), Guest bloqueado (/auth/me, /chat/message, /settings), User bloqueado (/auth/me, /chat/message), cuerpo del 503 con campo `detail`, /health y /auth/login y /auth/logout siempre exentos

## Rate limiting de Guest por IP (Punto 7 — 2026-08-05)

Complemento al límite diario por sesión (Punto 6): sin esto, un atacante
puede generar sesiones Guest nuevas indefinidamente para saltarse el contador
`DailyMessageUsage`.

### Dónde aplica

Solo en `POST /chat/message` para Guests (`current.is_guest`). Users y Admins
autenticados nunca pasan por este check.

### Extracción de IP

```
backend/app/auth/ip_rate_limiter.py → get_real_client_ip(request)
```

Prioridad (Cloudflare Tunnel + Caddy):

1. `CF-Connecting-IP` — cabecera que Cloudflare añade con la IP real del visitante;
   no necesita configuración adicional en Caddy porque Caddy pasa todas las cabeceras
   entrantes al backend por defecto.
2. `X-Forwarded-For` — primer valor (puede haber múltiples si hay proxies encadenados).
3. `request.client.host` — host TCP interno de Caddy; solo como último recurso.

> **Caddyfile:** no es necesario ningún cambio. Caddy reenvía todas las cabeceras
> del cliente original al backend (`reverse_proxy` no filtra cabeceras entrantes).

### Almacenamiento

In-memory, por proceso: `dict[str, list[float]]` (IP → timestamps monotónicos).
Se limpia de forma perezosa en cada llamada — no hay hilo de fondo ni cron.
Se pierde al reiniciar el proceso (aceptable: los reinicios son poco frecuentes).

### Configuración

```yaml
auth:
  guest_ip_rate_limit_per_hour: 30   # 0 = desactivado
```

### Respuesta al exceder el límite

```
HTTP 429 Too Many Requests
{"detail": "Demasiadas solicitudes. Inténtalo de nuevo más tarde."}
```

### Tests

`tests/test_guest_ip_rate_limiter.py` — 14 tests:
- IP extraction: CF-Connecting-IP gana, XFF gana sin CF, primer valor de XFF,
  fallback a client.host, sin client → "unknown"
- Limiter: dentro del límite, excede, IPs independientes, límite 0 nunca bloquea,
  slot no consumido al ser bloqueado, timestamps antiguos expiran, propiedad `limit`
- Singleton: lee límite del config, default 30 cuando falta la clave

## Tests (`tests/test_auth.py`)

34 tests, cobertura completa:

- **Register:** happy path, email duplicado, password débil (3 variantes),
  email inválido, fila creada en DB
- **Login:** happy path, password incorrecta, email desconocido,
  `last_login_at` actualizado, cuenta inactiva
- **Logout:** devuelve OK, idempotente (sin sesión)
- **GET /me:** usuario autenticado, guest
- **Forgot password:** email conocido, email desconocido (mismo 200),
  token creado en DB
- **Reset password:** éxito (contraseña nueva funciona, vieja no), token
  marcado como usado, token expirado, token ya usado, token inexistente,
  contraseña nueva débil
- **Delete account:** éxito (fila eliminada), guest rechazado, login falla
  tras borrado
- **Dependencia:** sin cookie → Guest, token inválido → Guest, token
  válido → CurrentUser correcto, token expirado → Guest

## Fase 2b — Aislamiento de personalidad por sesión (completada 2026-07-30)

Resuelta la vulnerabilidad de seguridad descrita en la sesión anterior:
cualquier Guest podía modificar la personalidad de Sity de forma global y
persistente para todos los usuarios.

Ver diseño completo en `docs/personality-isolation.md`.

**Cambios de esquema:** `Setting.key unique=True` → `(key, session_id)` composite
unique. Columna `session_id TEXT NULL` añadida; `NULL` = valor global/fallback.
Migración `_migrate_setting()` en `db.py` reconstruye la tabla sin pérdida de datos.

**Semántica de acceso:**
- Read: fila de sesión si existe, si no → fila global (NULL).
- Write: siempre a la sesión activa, nunca al global excepto en reset admin explícito.
- `/personality/reset`: elimina overrides de la sesión actual (vuelve al global). Accesible a todos los roles.

**Endpoints:** `GET /settings`, `GET /settings/personality`, `POST /settings/personality/adjust` y `/reset` usan `Depends(get_current_user)` para extraer `session_id`. `require_admin` eliminado de `/reset`.

**Tests:** 8 nuevos tests en `tests/test_personality_isolation.py`.

## Fases posteriores

- ✅ **Fase 2:** `session_id` real por usuario en todo el sistema,
  migración de producción ejecutada y verificada.
- ✅ **Fase 3:** revisión manual del dataset existente.
- ✅ **Fase 4:** memoria social — opinión + confianza por usuario.
- ✅ **Fase 5:** UI de login/registro/roles en el frontend — login,
  registro, invitado, logout, adaptación por rol, reCAPTCHA v3
  activo.
- ✅ **Fase 2b:** aislamiento de personalidad por sesión.
- ✅ **Fase 6:** sistema de integraciones self-service — cada usuario
  conecta sus propias cuentas de Google/Spotify con OAuth 2.0 + PKCE.

## Nota operativa — Google OAuth en modo "Testing"

Mientras la aplicación esté en modo **Testing** en Google Cloud Console
(OAuth consent screen no verificada/publicada), Google muestra a los
usuarios la pantalla de advertencia "esta app está en desarrollo, solo
acepta si conoces al desarrollador".

**Esto es comportamiento estándar de Google, no un bug de código.**

Para que un usuario pueda autenticarse con Google sin ver esa advertencia:

1. Ve a [Google Cloud Console](https://console.cloud.google.com/) →
   APIs & Services → OAuth consent screen → **Test users**.
2. Añade el email del usuario de prueba con el botón **+ Add Users**.
3. El usuario ya puede completar el flujo sin ver la advertencia de app
   no verificada.

Si en algún momento se abre el acceso a usuarios externos reales, habrá
que pasar por el proceso de verificación de Google (requiere datos de
privacidad, revisión manual, etc.).

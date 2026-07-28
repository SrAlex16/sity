# Sistema de autenticación y roles

Última actualización: 2026-07-11.

Implementación de la Fase 1 del sistema de usuarios de Sity: tabla
`User`, hashing de contraseñas, sesiones JWT en cookie, seis endpoints
de auth, dependencia `get_current_user` reutilizable, y seeding del
Admin único. El repo de Sity es público en el portfolio de Alex — esta
fase protege el sistema antes de exponer las rutas de chat/tools al
sistema de roles en fases posteriores.

## Roles — tres, fijos

| Rol | Tiene fila en `User` | Persistencia | Límite de uso |
|---|---|---|---|
| **Guest** | No | Efímera (solo la pestaña abierta) | 20 msgs/día por IP (Fase 3) |
| **User** | Sí | Sesión persistente (cookie JWT) | 100 msgs/día (Fase 3) |
| **Admin** | Sí (`role="admin"`) | Sesión persistente | Sin límite |

**Por qué Guest no persiste nada:** la sesión de un Guest es
completamente efímera — no hay `session_id` persistente, no hay
historial entre visitas, y recargar la página equivale a empezar de
cero. El conteo de mensajes para rate limiting (Fase 3) se hará por
IP/fingerprint de sesión de pestaña, sin ningún registro permanente
en DB. Esto mantiene el GDPR simple: nada que borrar.

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

## Captcha

`RegisterRequest` y `LoginRequest` aceptan un campo opcional
`captcha_token`. La validación es un stub que siempre pasa. Para
activar hCaptcha o reCAPTCHA:

1. Crear una cuenta en hCaptcha/reCAPTCHA y obtener las claves.
2. Añadir `SITY_CAPTCHA_SECRET` al `.env`.
3. Implementar la validación en `routes_auth.py` — el TODO está marcado
   en `schemas_auth.py`.

Esto no bloquea el resto de la Fase 1.

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
  user_daily_message_limit: 100      # Fase 3
  guest_daily_message_limit: 20      # Fase 3
  password_reset_expiry_minutes: 60
  registration_open: true
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
├── hashing.py          # hash_password, verify_password (bcrypt)
├── jwt_utils.py        # create_token, decode_token (PyJWT HS256)
├── dependencies.py     # CurrentUser, get_current_user
├── email_stub.py       # send_password_reset_email (stub con TODO SMTP)
└── admin_seeder.py     # seed_admin() llamado en startup
backend/app/api/
├── routes_auth.py      # 7 endpoints /auth/*
└── schemas_auth.py     # RegisterRequest, LoginRequest, MeResponse, ...
```

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

## Fases posteriores

- **Fase 2:** asociar `ChatMessage`/`Setting` a `user_id` real;
  completar el borrado de datos en DELETE /auth/me.
- **Fase 3:** enganchar `get_current_user` a `/chat/*`, `/events/*`,
  `/settings/*`; implementar los límites de uso por rol; rate limiting
  de Guest por IP.
- **Fase 4:** memoria social/opinión/confianza por usuario (fuera de
  alcance de las fases de auth).
- **Fase 5:** UI de login/registro en el frontend.

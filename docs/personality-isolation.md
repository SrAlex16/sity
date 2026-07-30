# Aislamiento de personalidad por sesión (Fase 2b)

Implementado: 2026-07-30.

## El problema original

`Setting.key` tenía `unique=True` global sin ninguna columna `session_id`.
Cualquier usuario — incluido un Guest anónimo — que ajustase un slider de
personalidad en `PersonalityScreen` modificaba la configuración de Sity para
**todos los usuarios simultáneamente**, incluido Admin, de forma persistente
en SQLite. No había ningún aislamiento entre sesiones.

## Diseño adoptado

**Lectura (fallback chain):**
1. Si existe una fila con `(key, session_id=sesión_actual)` → usa ese valor.
2. Si no → usa la fila global `(key, session_id=NULL)`.
3. Si tampoco hay fila global → usa el default de `config/default_config.yaml`.

**Escritura:**
- Siempre escribe a `(key, session_id=sesión_actual)`. Nunca modifica la fila global.
- La fila global solo cambia cuando Admin ejecuta explícitamente un reset global (pendiente para fase posterior; hoy `/personality/reset` resetea la sesión activa, no el global).

**Reset (`POST /settings/personality/reset`):**
- Elimina todas las filas `personality.*` de la sesión actual.
- La sesión vuelve a leer los valores del fallback global (cadena de lectura normal).
- Accesible a todos los roles (Guest, User, Admin) — cada uno resetea su propia sesión.
- No existe todavía un endpoint para que Admin resetee el global; los valores globales se establecen al arrancar via `CANONICAL_PERSONALITY` cuando no hay filas globales.

## Esquema `Setting`

```
id            INTEGER PRIMARY KEY
key           TEXT    NOT NULL             -- e.g. "personality.sarcasm_level"
value_json    TEXT    NOT NULL             -- JSON value
source        TEXT    NOT NULL DEFAULT 'default'
created_at    DATETIME NOT NULL
updated_at    DATETIME NOT NULL
session_id    TEXT    DEFAULT NULL         -- NULL = fila global/fallback

UNIQUE (key, session_id)  -- nota: SQLite trata NULLs como distintos en UNIQUE
                          -- la unicidad de filas globales la garantiza set_setting()
```

**Nota SQLite:** el estándar SQL (y SQLite específicamente) trata `NULL` como
distinto de cualquier otro valor en constraints `UNIQUE`, lo que significa que
técnicamente podrían existir dos filas `(personality.sarcasm_level, NULL)`. En
la práctica esto no ocurre porque `SettingsService.set_setting()` hace un
"upsert" que comprueba la existencia antes de insertar. No es una limitación
operativa real.

## Migración de datos en producción

`_migrate_setting()` en `backend/app/memory/db.py` — idempotente, se ejecuta
en cada arranque del backend. Si la tabla ya tiene `session_id`, retorna
inmediatamente.

Si la columna no existe, reconstruye la tabla completa vía SQLite
"create-copy-drop-rename" (único camino en SQLite para cambiar un constraint
`UNIQUE`). Las filas existentes reciben `session_id=NULL` (se tratan como
valores globales). No hay pérdida de datos.

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `backend/app/memory/models.py` | `Setting`: añade `session_id`, reemplaza `unique=True` en key por `__table_args__` con `UniqueConstraint("key", "session_id")` |
| `backend/app/memory/db.py` | Añade `_migrate_setting()`, llamado en `init_db()` |
| `backend/app/settings/settings_service.py` | Todos los métodos de personality aceptan `session_id`; read con fallback chain; write siempre a sesión |
| `backend/app/chat/turn_context.py` | `get_personality(session_id=session_id)` |
| `backend/app/core/tool_executor.py` | `adjust_personality(..., session_id=self.session_id)` |
| `backend/app/api/routes_settings.py` | `get_current_user` en endpoints de personality; `require_admin` eliminado de `/reset` |
| `tests/test_personality_isolation.py` | 8 tests nuevos |
| `tests/test_require_admin.py` | Eliminados 3 tests de reset personality (ya no es require_admin) |

## Tests

`tests/test_personality_isolation.py`:

- Dos sesiones Guest ajustan `sarcasm_level` de forma independiente sin interferirse.
- Sesión User y sesión Guest son independientes.
- Sesión nueva sin overrides hereda exactamente los valores de `CANONICAL_PERSONALITY`.
- Reset elimina overrides y cae al global.
- Reset de sesión A no afecta a sesión B.
- Todos los roles (Guest, User, Admin) pueden ajustar y resetear su propia personalidad.

## Pendiente para fases posteriores

- **Reset global por Admin:** endpoint para que Admin restaure los valores globales
  (`session_id=NULL`) a `CANONICAL_PERSONALITY`. Actualmente el reset de Admin solo
  borra sus propios overrides de sesión (mismo comportamiento que cualquier usuario).
- **`DELETE /auth/me`:** borrar filas `Setting` con `session_id=f"user:{id}"` al
  eliminar la cuenta. Hoy solo se borra la fila `User`.

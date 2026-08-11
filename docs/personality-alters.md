# Sistema de Alters de Personalidad

Última actualización: 2026-08-11 (Paso 1 completado — modelo + servicio).

Documenta el diseño completo del sistema de Alters: presets de personalidad
guardados por usuario, independientes de la personalidad activa por sesión.

Para arquitectura general ver `docs/architecture.md`.
Para el sistema de aislamiento de personalidad por sesión ver `docs/personality-isolation.md`.
Para estado actual ver `docs/state.md`.

---

## Motivación y concepto

Un Alter es un "archivo de guardado" de personalidad — una foto completa de los
14 parámetros de personalidad de Sity, almacenada bajo un nombre elegido por el
usuario y recuperable en cualquier momento.

### Por qué es distinto de la personalidad activa por sesión (Fase 2b)

La Fase 2b introdujo aislamiento de personalidad por sesión: cada usuario tiene
su propia configuración activa, que puede cambiar slider a slider en tiempo real.
Esos cambios son efímeros en el sentido de que no tienen nombre ni identidad
propia — si el usuario mueve el slider de Sarcasmo a 0.8 y luego a 0.3, no hay
forma de "volver a la configuración que tenía antes" salvo reajustar manualmente.

Los Alters resuelven esto: el usuario puede guardar una configuración con nombre
("Modo trabajo", "Modo noche", "Modo amigos"), y recuperarla con un solo gesto.
La activación de un Alter es equivalente a mover los 14 sliders a mano hasta esos
valores — no hay magia adicional, solo una escritura en bulk.

### Por qué es independiente de la memoria social (SocialProfile)

`SocialProfile` registra la opinión y confianza de Sity hacia un usuario concreto
— es una propiedad de la **relación** entre Sity y ese usuario, acumulada a lo
largo del tiempo mediante un job de background. Cambiar de Alter (de "Modo amigos"
a "Modo trabajo") no cambia quién es el usuario, ni qué ha hecho en el pasado, ni
cómo de cerca están. Por tanto `SocialProfile` y `OpinionSnapshot` son
completamente inmutables al cambio de Alter. El código de `AlterService` no
importa ni referencia ninguna clase de `app/social/`.

---

## Modelo de datos

### `PersonalityAlter`

```
id               INTEGER PK autoincrement
user_id          INTEGER  indexed  — FK lógico a User.id
slot             INTEGER            — 1 a 5
name             TEXT     nullable  — None = slot vacío
parameters_json  TEXT     nullable  — JSON dict[str, float] de 14 parámetros, None = slot vacío
created_at       DATETIME utc
updated_at       DATETIME utc
UniqueConstraint("user_id", "slot")
```

### Decisiones de diseño

**`user_id` en vez de `session_id`:** Los Alters son propiedad del usuario, no de
la sesión. Un User tiene siempre `session_id = "user:{id}"`, estable entre visitas.
Un Guest no tiene `user_id` y tampoco puede guardar Alters (sin identidad persistente
no hay dónde guardar nada). Usar `user_id` refleja correctamente que los Alters
siguen al usuario, no al dispositivo o pestaña.

**5 slots fijos, no un número configurable:** 5 es un límite de producto (interfaz
con 5 botones fijos en el frontend), no un umbral operativo que deba ajustarse sin
deploy. El mismo criterio que el número de roles fijos (Guest/User/Admin) o los 14
parámetros de personalidad — no vive en `default_config.yaml`. La constante
`_MAX_SLOTS = 5` vive en `alter_service.py` como un único punto de verdad en código.

**`parameters_json` como JSON en vez de columnas individuales:** Los 14 parámetros
son un bloque atómico — siempre se leen todos juntos y se escriben todos juntos.
Columnas individuales solo servirían si necesitáramos queries por parámetro concreto
(ej. "dáme todos los Alters donde sarcasm_level > 0.5"), que no es un caso de uso
previsto. El JSON compacto ocupa menos espacio y es más fácil de mantener si el
conjunto de parámetros cambia.

**Slots como filas opcionales (no pre-creadas):** Solo existen filas para slots
que han sido guardados al menos una vez. `list_alters()` sintetiza los slots vacíos
en memoria, evitando la inicialización implícita de 5 filas por usuario al crear
la cuenta.

---

## Las 5 operaciones

### `save_alter(user_id, slot, name, current_session_id)`

Lee la personalidad activa de `current_session_id` via `SettingsService.get_personality()`
y la guarda en el slot con el nombre indicado. Si el slot ya tenía contenido, lo
sobrescribe completamente (incluyendo el nombre). Idempotente: guardar dos veces
sobre el mismo slot no crea duplicados.

**Casos límite:** no hay validación de que el nombre sea no vacío — el usuario puede
guardar un Alter sin nombre si quiere. El slot debe estar en rango 1–5 (ValueError
si no).

### `load_alter(user_id, slot, session_id)`

Lee el JSON de parámetros del slot y los aplica a `session_id` via
`set_all_personality()`. Devuelve el estado resultante de la personalidad de la
sesión (los 14 valores tras aplicar el Alter).

**Casos límite:** slot vacío → `ValueError("Slot N is empty — nothing to load")`.
No crashea, no aplica valores basura. El slot de otro usuario es inaccessible porque
`user_id` está en la query.

### `rename_alter(user_id, slot, new_name)`

Modifica solo el campo `name` de la fila existente. Los `parameters_json` no se
tocan. `updated_at` se actualiza.

**Casos límite:** slot vacío → `ValueError`.

### `clear_alter(user_id, slot)`

Elimina la fila del slot. Si el slot ya estaba vacío, no hace nada (no es un error).
Tras el borrado, `list_alters()` muestra ese slot como vacío.

### `copy_alter(user_id, from_slot, to_slot)`

Copia el contenido completo de `from_slot` (parámetros **y** nombre) a `to_slot`.
El destino queda como un clon idéntico del origen. Si el destino tenía contenido
previo, se sobrescribe completamente — no quedan restos del estado anterior.

**Decisión de diseño (nombre):** copiar incluye el nombre por defecto. Un Alter
copiado es una copia completa, no una copia parcial. Si el usuario quiere un nombre
distinto en el destino, puede renombrarlo a continuación con `rename_alter`. Simple
de entender, sin comportamiento especial que recordar.

**Casos límite:** `from_slot` vacío → `ValueError("Source slot N is empty")`.
`to_slot` puede estar vacío (se crea) o tener contenido (se sobrescribe).

---

## Arquitectura por capas

```
HTTP endpoints (Paso 2 — pendiente)
    └── AlterService   [backend/app/settings/alter_service.py]
            └── SettingsService.get_personality()     — lectura de la sesión activa
            └── SettingsService.set_all_personality() — escritura en bulk a la sesión
                    └── SettingsService.set_setting()  — mecanismo base ya existente
                            └── Setting (SQLModel)     — tabla DB ya existente
```

`AlterService` no tiene su propio mecanismo de escritura de personalidad: reutiliza
`set_all_personality()`, que a su vez reutiliza `set_setting()` con la cadena de
aislamiento por sesión ya existente (session row → global fallback). No hay un
segundo camino de aplicación de personalidad — hay uno solo, y los Alters lo usan.

`PersonalityAlter` es un modelo separado de `Setting` porque su semántica es
distinta: `Setting` es una configuración activa (mutable, viva), `PersonalityAlter`
es un snapshot guardado (inmutable hasta que el usuario lo sobreescriba
explícitamente). Mezclarlos en la misma tabla requeriría un sistema de namespacing
más complejo sin ningún beneficio real.

### `set_all_personality()` en `SettingsService`

Método añadido en el Paso 1 para soportar `load_alter`. Aplica los 14 parámetros
de golpe en una sola llamada, evitando que el frontend tenga que hacer 14 llamadas
HTTP separadas. Valida que el dict sea completo (exactamente los 14 keys de
`PERSONALITY_KEYS`) y clampea cada valor a [0, 1].

---

## Aislamiento y seguridad

**Solo User/Admin, nunca Guest.** Un Guest no tiene `user_id` — no hay fila en
`User` y por tanto no hay dónde anclar los Alters. El endpoint (Paso 2) rechazará
a Guest con 401. No hay ninguna ruta de código en `AlterService` que reciba un
Guest: `user_id` es un entero que viene del JWT, y los Guests no tienen JWT.

**Aislamiento por `user_id`.** Todas las queries en `AlterService` filtran
`PersonalityAlter.user_id == user_id`. No es posible leer ni modificar los Alters
de otro usuario desde la capa de servicio. Los tests verifican este aislamiento
explícitamente (ver §Tests).

**`load_alter` solo escribe sobre la sesión del llamador.** El `session_id` que
se pasa a `set_all_personality()` es el de la sesión activa del usuario que hace
la petición (extraído del JWT en el endpoint). Un usuario no puede cargar un Alter
sobre la sesión de otro usuario.

---

## Logging y trazas

Todas las operaciones de mutación emiten un evento a nivel `INFO` via `write_log`
con `module="alters"`:

| Evento | Payload |
|---|---|
| `alter_saved` | `user_id`, `slot`, `name` |
| `alter_loaded` | `user_id`, `slot`, `name`, `session_id` |
| `alter_renamed` | `user_id`, `slot`, `new_name` |
| `alter_cleared` | `user_id`, `slot` |
| `alter_copied` | `user_id`, `from_slot`, `to_slot`, `name` |

**Por qué loguear:** Los Alters son cambios de configuración con efecto inmediato
sobre el comportamiento de Sity. El mismo criterio que ya se aplica a cambios de
personalidad individuales (loguear el `adjust` con `source`) y a acciones de
settings (voice, language). Si Sity empieza a comportarse de forma inesperada, el
log de `alter_loaded` permite saber qué preset estaba activo en ese momento.

`list_alters` y `rename_alter` no loguean a nivel INFO — leer la lista es una
operación de consulta sin efecto sobre el comportamiento de Sity; `rename_alter`
es solo un cambio de etiqueta sin efecto sobre la personalidad activa.

Los logs van a `data/logs/app-YYYY-MM-DD.jsonl` con el mismo sistema JSONL usado
en todo el proyecto (retención 14 días, rotación diaria).

---

## Endpoints REST (Paso 2 — pendiente)

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/settings/alters` | User/Admin | Lista los 5 slots del usuario |
| POST | `/settings/alters/{slot}/save` | User/Admin | Guarda la personalidad actual en el slot |
| POST | `/settings/alters/{slot}/load` | User/Admin | Aplica el slot a la sesión actual |
| PATCH | `/settings/alters/{slot}/rename` | User/Admin | Renombra el slot |
| DELETE | `/settings/alters/{slot}` | User/Admin | Vacía el slot |
| POST | `/settings/alters/{slot}/copy-to/{dest}` | User/Admin | Copia slot a otro slot |

---

## Tests

`tests/test_alters.py` — 23 tests, todos en capa de servicio (sin HTTP):

**CRUD básico:**
- `list_alters` devuelve exactamente 5 slots vacíos por defecto
- `save_alter` almacena los 14 parámetros de la sesión actual
- `list_alters` después de `save_alter` muestra el slot lleno y los otros vacíos
- `save_alter` sobre un slot existente sobrescribe (idempotente, sin filas duplicadas)

**Aislamiento:**
- Dos usuarios con `user_id` distintos tienen sus 5 slots completamente separados

**`load_alter`:**
- Slot vacío lanza `ValueError` con mensaje que contiene "empty"
- Aplica exactamente los 14 valores guardados a la sesión destino
- No afecta a otras sesiones (ni del mismo usuario ni de otro)

**`rename_alter`:**
- Cambia el nombre sin tocar los parámetros
- Slot vacío lanza `ValueError`

**`clear_alter`:**
- Elimina el contenido y el slot vuelve a aparecer como vacío
- Sobre slot ya vacío es un no-op sin excepción

**`copy_alter`:**
- Sobrescribe el destino completamente — ningún valor del contenido anterior persiste
- Copia el nombre además de los parámetros
- Origen vacío lanza `ValueError`

**Validación de slot:**
- Slots 0, 6, -1, 99 lanzan `ValueError` con mensaje que contiene "Slot"

**`set_all_personality` (SettingsService):**
- Aplica los 14 valores correctamente a la sesión destino
- Rechaza un dict con una key desconocida (`ValueError("Unknown")`)
- Rechaza un dict con keys faltantes (`ValueError("Missing")`)
- No afecta a otras sesiones al escribir sobre una sesión concreta

---

## Pendiente

- **Paso 2** — Endpoints REST (ver tabla §Endpoints)
- **Paso 3** — UI en la pantalla de Ajustes (5 slots con nombre, botones guardar/cargar/renombrar/borrar/copiar)
- **Logging de `alter_loaded` en aiOrchestrator** — si en algún momento queremos incluir el nombre del Alter activo en los logs de turno (para saber "este turno se respondió con el Alter X activo"), habrá que pasar el nombre del Alter cargado hasta `TurnContext`; pendiente de decidir si aporta suficiente valor diagnóstico.

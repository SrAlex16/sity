# Sistema de Alters de Personalidad

Última actualización: 2026-08-13 (sistema completo — modelo + servicio + endpoints + frontend verificados en producción).

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
HTTP endpoints  [backend/app/api/routes_settings.py]
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

## Endpoints REST (completado — Paso 2)

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| GET | `/settings/alters` | User/Admin | Lista los 5 slots del usuario; siempre devuelve exactamente 5 entradas (is_empty=true para los vacíos) |
| POST | `/settings/alters/{slot}/save` | User/Admin | Guarda la personalidad activa de la sesión en el slot. Body: `{"name": "..."}`. 422 si slot fuera de [1-5] |
| POST | `/settings/alters/{slot}/load` | User/Admin | Aplica el slot a la sesión activa. 400 si el slot está vacío |
| PATCH | `/settings/alters/{slot}/rename` | User/Admin | Renombra el slot. Body: `{"name": "..."}`. 400 si el slot está vacío |
| DELETE | `/settings/alters/{slot}` | User/Admin | Vacía el slot (204, no-op si ya estaba vacío) |
| POST | `/settings/alters/{from_slot}/copy/{to_slot}` | User/Admin | Copia nombre + parámetros de from_slot a to_slot. 400 si el origen está vacío |

Todos devuelven 401 para Guest. La validación de rango (1-5) es enforced por FastAPI `Path(ge=1, le=5)` → 422 automático.

`AlterSlot` response shape:
```json
{
  "slot": 2,
  "name": "Modo trabajo",
  "parameters": {"sarcasm_level": 0.25, "warmth_level": 0.35, ...},
  "is_empty": false
}
```

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

## Frontend (completado — Paso 3)

### Ubicación

Sub-pestaña "Alters" dentro de `PersonalityScreen` (pantalla de Rasgos/Parámetros).
Un tab bar con dos pestañas — **Rasgos** (sliders existentes) y **Alters** (presets) — se muestra solo para User/Admin. Los Guests ven solo la vista de Rasgos sin acceso a Alters.

### Componentes

**`mobile/src/hooks/useAlters.ts`** — hook de datos:
- `useAlters()` hace `GET /settings/alters` al montar y expone `slots`, `busy` (slot en vuelo), y las funciones `save`, `load`, `rename`, `clear`, `copy`.
- Las operaciones actualizan el estado local optimistamente donde es posible (rename, clear) o con la respuesta del servidor (save, copy).
- `busy: number | null` — el slot actualmente en vuelo; cada slot lo usa para deshabilitar sus botones mientras hay una petición en curso.

**`mobile/src/components/AltersPanel.tsx`** — UI principal:
- Renderiza los 5 slots en cards estilo cyberpunk.
- Cada slot muestra: número (indicador cuadrado), nombre (o "Vacío" en cursiva para slots vacíos).
- **Slot vacío:** botón "Guardar aquí" → despliega inline un input de nombre + botón Guardar + cancelar.
- **Slot con contenido:** botones Cargar / Renombrar / Copiar / Vaciar.
  - **Cargar** → confirmación inline ("Sobrescribirá la personalidad activa") + Confirmar / Cancelar.
  - **Renombrar** → input con nombre actual + guardar + cancelar.
  - **Copiar** → selector de slot destino (excluye el origen) + Copiar + cancelar.
  - **Vaciar** → confirmación inline ("Se eliminará este preset") + Confirmar / Cancelar.
- Solo un slot puede tener acción activa a la vez (cancel limpia el estado global).
- `onLoaded` callback: tras cargar un Alter, AltersPanel llama a `onLoaded` → `PersonalityScreen` limpia `liveOverride` y llama a `reload()` → los sliders reflejan los valores del Alter inmediatamente sin recargar la página.

**`mobile/src/screens/PersonalityScreen.tsx`** — modificaciones:
- Acepta `role: string` como prop (pasado desde `App.tsx`).
- `const isGuest = role === 'guest'` — el tab bar Alters solo se muestra si `!isGuest`.
- `handleAlterLoaded`: `setLiveOverride({})` + `await reload()` — wired a `AltersPanel.onLoaded`.
- `view: 'params' | 'alters'` — estado local que controla qué vista se muestra bajo el tab bar.

**`mobile/src/App.tsx`** — `<PersonalityScreen role={role} />` (antes sin props).

### Interacción con el estado de sliders

Cuando se carga un Alter:
1. `AlterService.load_alter()` escribe los 14 parámetros en la DB vía `set_all_personality`.
2. El endpoint `/settings/alters/{slot}/load` retorna 200.
3. `handleAlterLoaded` en `PersonalityScreen` llama a `reload()` de `usePersonality`.
4. `usePersonality.load()` re-fetcha `/settings/personality` y actualiza `settings`.
5. `liveOverride` se limpia → `displayed` refleja los valores del Alter cargado.
6. Los sliders se actualizan visualmente con animación normal de Framer Motion.

No hay necesidad de un segundo canal de eventos (`sity:personality-updated`) — el callback directo `onLoaded` es suficiente y más explícito.

## Mejoras posibles

- **Logging de `alter_loaded` en TurnContext** — si se quiere saber qué Alter estaba activo durante un turno, habría que pasar el nombre del Alter cargado hasta `TurnContext`. No implementado; la decisión de si aporta suficiente valor diagnóstico queda abierta.
- **i18n** — PersonalityScreen y AltersPanel están en español hardcoded, consistente con el resto de PersonalityScreen. Se actualizará junto con el namespace `chat` cuando se extienda i18n a ChatScreen.

## Verificado en producción (2026-08-13)

Sistema completo (Pasos 1–3) verificado en real por Alex: guardar, cargar, renombrar,
copiar y vaciar slots; sliders actualizados inmediatamente al cargar un Alter;
interfaz cyberpunk con confirmaciones inline. 1842 tests en verde.

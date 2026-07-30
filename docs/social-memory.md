# Sistema de Memoria Social

Última actualización: 2026-07-30.

Documenta las 4 fases de la Fase 4 del proyecto: modelo de datos,
extracción de carga conversacional, job de actualización en background,
e inyección de contexto en el prompt.

Para arquitectura general ver docs/architecture.md.
Para estado actual ver docs/state.md.

---

## Motivación

Sity necesita acumular una impresión de cada usuario a lo largo del tiempo —
no para anunciarlo en voz alta, sino para modular tono, apertura y disposición
de forma coherente con la relación real. El mecanismo es completamente opaco
al usuario: no hay frases como "mi opinión sobre ti es 0.3", del mismo modo
que una persona real no verbaliza continuamente sus evaluaciones internas.

**Restricción fundamental:** ningún valor en este sistema puede ser escrito
directamente desde el contenido del mensaje del usuario. La única ruta de
escritura a `opinion`/`trust` es el job de background, que opera sobre cargas
emitidas por el propio modelo (no por el usuario).

---

## Paso 1 — Modelo de datos

**Ficheros:** `backend/app/memory/models.py`

### SocialProfile

Un perfil por usuario (`user_id` único). Nunca se crea para sesiones `guest:`.

| Campo | Tipo | Descripción |
|---|---|---|
| `user_id` | int (unique) | FK lógica al User |
| `opinion` | float [-1, +1] | Media móvil exponencial de la impresión acumulada |
| `trust` | float [0, 1] | Confianza construida (tiempo + estabilidad) |
| `pending_loads_json` | str (JSON array) | Cargas de turno pendientes de procesar |
| `last_updated_at` | datetime? | Último procesado por el job |
| `created_at` | datetime | Fecha de primer contacto |

### OpinionSnapshot

Un registro por actualización del job. Permite calcular estabilidad histórica.

| Campo | Tipo | Descripción |
|---|---|---|
| `profile_id` | int (index) | FK a SocialProfile.id |
| `opinion_value` | float | Valor de opinion en este snapshot |
| `trust_value` | float | Valor de trust en este snapshot |
| `computed_at` | datetime | Cuándo se calculó |

---

## Paso 2 — Extracción de carga conversacional (`<R:N>`)

**Ficheros:** `backend/app/chat/final_response_builder.py`,
`backend/app/core/persona_engine.py`, `backend/app/prompts/persona_system.md`

### Mecanismo

El modelo emite un tag `<R:N>` al final de cada respuesta (N entero -2..+2)
que refleja la lectura emocional del turno:

```
-2  conflicto explícito / frustración marcada
-1  turno algo tenso o incómodo
 0  turno neutro
+1  humor, buen feeling, colaboración
+2  gratitud, celebración
```

Este tag se **elimina siempre** antes de que el texto llegue al usuario
o al TTS, y antes de `save_message`. El strip es incondicional.

### Instrucción al modelo

El placeholder `{turn_load_instruction}` en `persona_system.md` se resuelve
en `persona_engine.py`:

- Sesión `user:` → texto completo con escala y reglas
- Guest / otros → `""` (el placeholder desaparece)

### Pipeline en `build_final_ai_response` (paso 4.5)

```
_strip_turn_load_tag(response.text)
   ├─ tag presente + valor válido [-2,+2] + sesión user:
   │     → _append_pending_load(session, session_id, load)
   ├─ tag presente + valor inválido (ej. <R:99>)
   │     → WARN turn_load_tag_invalid {raw_value, session_id}
   ├─ tag ausente + sesión user:
   │     → WARN turn_load_tag_missing {session_id}
   └─ tag ausente + guest:
         → silencio total
```

### `_append_pending_load` — upsert atómico

```sql
INSERT INTO socialprofile (user_id, opinion, trust, pending_loads_json, created_at)
VALUES (:uid, 0.0, 0.0, json_array(:load), :now)
ON CONFLICT(user_id) DO UPDATE
SET pending_loads_json =
    json_insert(COALESCE(socialprofile.pending_loads_json, '[]'), '$[#]', :load)
```

Un solo statement SQL sin read-modify-write en Python. Elimina la race
condition entre llamadas concurrentes (SQLite serializa escrituras).

---

## Paso 3 — Job de actualización en background

**Ficheros:** `backend/app/social/update.py`, `config/default_config.yaml`

### Trigger

`maybe_trigger_social_update` se llama en `build_final_ai_response` (paso 6.5)
después de `save_message`. Comprueba:

```sql
SELECT json_array_length(COALESCE(pending_loads_json, '[]'))
FROM socialprofile WHERE user_id = :uid
```

Si el resultado ≥ `social.update_threshold_turns` (default: 10), dispara un
hilo daemon:

```python
threading.Thread(target=_run_social_update, args=(user_id, trace_id), daemon=True).start()
```

### `_run_social_update` — atomicidad con BEGIN IMMEDIATE

```
Adquiere per-user threading.Lock(blocking=False)
   └─ si ya hay un job activo: log social_update_skipped_locked, salir

engine.raw_connection()
BEGIN IMMEDIATE          ← write lock desde el inicio
SELECT perfil + loads    ← bajo lock
[si vacío → ROLLBACK, salir]
[_test_hook_after_read]  ← punto de inyección para tests de concurrencia
Calcular batch_opinion, new_opinion, new_trust
UPDATE socialprofile SET pending_loads_json = '[]', opinion, trust
INSERT INTO opinionsnapshot
[_test_hook_before_commit] ← punto de inyección para tests de atomicidad
COMMIT                   ← libera lock; escritores bloqueados prosiguen
log social_profile_updated
```

Si hay excepción antes del commit: `ROLLBACK`, log `social_update_failed`.
El estado de la DB queda idéntico al punto de entrada.

El `BEGIN IMMEDIATE` garantiza que cualquier `_append_pending_load` concurrente
que llegue durante el job quede en cola y escriba en el `[]` del post-commit,
no en el batch en proceso.

### Fórmulas

**`compute_batch_opinion(loads: list[int]) → float`**

```
weight(load) = 1 + |load|
batch_opinion_raw = Σ(load_i × weight_i) / Σ(weight_i)   → [-2, +2]
batch_opinion_norm = batch_opinion_raw / 2                  → [-1, +1]
```

Cargas extremas (±2) tienen el doble de peso que cargas neutras (0 → peso 1).

**`new_opinion`** — EMA con α=0.3:

```
new_opinion = clamp(-1, 1, 0.3 × batch_norm + 0.7 × old_opinion)
```

**`compute_trust(created_at_str, snapshot_opinions, now) → float`**

```
time_factor       = min(1.0, days_known / 365)
stability_factor  = max(0.0, 1.0 - pstdev(all_opinion_snapshots))
trust             = time_factor × (0.5 + 0.5 × stability_factor)
```

- El tiempo aporta hasta el 50% de la confianza (un año para alcanzar el máximo).
- La estabilidad (baja desviación típica entre snapshots) aporta el otro 50%.
- Un usuario inconsistente (sube y baja de opinión) limita el trust máximo alcanzable.

### Configuración

```yaml
# config/default_config.yaml
social:
  update_threshold_turns: 10
```

---

## Paso 4 — Inyección de contexto social en el prompt

**Fichero:** `backend/app/chat/prompt_context.py`

### `_build_social_context_block(session, session_id) → str`

Función de solo lectura. Retorna `""` si:
- La sesión no es `user:` (guest, telegram, etc.)
- No existe SocialProfile para el usuario (primer contacto)
- Error en la consulta (no propaga excepción)

Cuando existe perfil, retorna un bloque que describe la relación
en términos cualitativos + el valor numérico entre paréntesis:

```
Contexto de relación (uso interno — informa tono y disposición, no citar directamente):
- Disposición hacia este interlocutor: positiva (0.34)
- Confianza acumulada: consolidada (0.55)
Deja que esto module el tono con el que te expresas; no menciones estos valores salvo que resulte muy natural.
```

**Etiquetas de opinión:**
- `≤ -0.5` → "bastante negativa"
- `(-0.5, -0.1]` → "algo negativa"
- `(-0.1, 0.1)` → "neutra"
- `[0.1, 0.5)` → "positiva"
- `≥ 0.5` → "muy positiva"

**Etiquetas de trust:**
- `< 0.2` → "inicial (poca historia compartida)"
- `[0.2, 0.4)` → "en desarrollo"
- `[0.4, 0.7)` → "consolidada"
- `≥ 0.7` → "alta"

### Punto de inyección

El bloque se añade en `PromptContextBuilder.build()`, en **ambos** mensajes:

- `user_message_with_history` (mensaje principal → tono de la respuesta)
- `planner_user_message` (mensaje al planner → routing y decisión de tools)

Orden en el mensaje: tiempo → memoria → **social** → [voice flags] → mensaje usuario.

---

## Reglas de seguridad invariables

1. **Guest nunca obtiene SocialProfile.** La comprobación está en la guardia
   `if not session_id.startswith("user:")`.

2. **opinion/trust solo los escribe el job de background.** `_build_social_context_block`
   y `_append_pending_load` son de solo lectura y acumulación respectivamente.
   No existe ninguna ruta que escriba `opinion` o `trust` desde texto del usuario.

3. **El tag `<R:N>` viene del modelo, no del usuario.** `_strip_turn_load_tag`
   solo se aplica a `response.text` (respuesta del asistente). El texto del usuario
   nunca se parsea en busca del tag.

4. **No keyword matching.** El sistema no contiene ningún `if "confianza" in texto`
   ni detección de palabras clave para inferir opinión. Solo el tag emitido por
   el modelo tras evaluar el tono real del turno.

5. **Sin datos concretos verificables de terceros.** La regla de "cotilleo" se
   aplica siempre, independientemente del nivel de confianza del interlocutor
   que pregunta. Ver sección siguiente.

---

## Paso 4b — Tool `social_recall_impression` (terceros)

**Ficheros:** `backend/app/tools/handlers/social_tools.py`,
`backend/app/cortex/tool_schemas.py` (en `BASE_TOOLSET`)

### Prerequisito — `User.display_name`

Campo añadido a la tabla `User` (`Optional[str]`, índice). Derivación automática:
- **Admin (Alex):** seeder `admin_seeder.py` siembra `"Alex"` (nuevo y backfill de instancias existentes)
- **Registro:** `display_name = email.split("@")[0]` — prefijo del email como nombre inicial
- **Edición:** pendiente (PATCH `/auth/me` — Fase 5)

Migración: `_migrate_user()` en `db.py`, mismo patrón que `_migrate_chatmessage()`.

### Mecanismo

El modelo invoca `social_recall_impression(username: str)` cuando el interlocutor
menciona a alguien y necesita contexto. El modelo decide cuándo llamarla — no hay
detección de menciones en el backend.

```
A = session actual (session_id "user:N")
B = usuario buscado por display_name (case-insensitive, exacto)
```

### Fórmula de confianza relativa

```
disclosure = trust_A × trust_B
```

Actúa como doble cerrojo: ambas relaciones deben estar establecidas para
que aumente el nivel de detalle. Si cualquiera de las dos es nueva, la
divulgación queda en el mínimo.

Umbrales:

| Rango | Nivel | Contenido devuelto |
|---|---|---|
| `< 0.05` | LOW | Solo la etiqueta de opinión; sin nombrar a B |
| `0.05 – 0.20` | MEDIUM | Etiqueta + nombre de B + frase de familiaridad |
| `≥ 0.20` | HIGH | Todo lo anterior + una línea cualitativa de matiz |

Ejemplos numéricos:
- trust_A=0.05, trust_B=0.05 → 0.0025 → LOW
- trust_A=0.30, trust_B=0.30 → 0.09 → MEDIUM
- trust_A=0.60, trust_B=0.60 → 0.36 → HIGH

### Casos especiales

| Caso | Respuesta |
|---|---|
| Sesión guest | "No tengo memoria de relaciones en esta sesión." |
| A == B (pregunta por sí mismo) | "Estás preguntando por ti mismo." |
| Nombre no reconocido | "No conozco a nadie con el nombre X." |
| B sin SocialProfile | "No tengo ninguna impresión formada sobre X todavía." |

### Límite duro — aplicado siempre, en todos los niveles

**NUNCA** se incluye contenido literal de mensajes de B, hechos concretos,
fechas, ni ningún dato verificable sobre B. Solo etiquetas cualitativas
derivadas de `opinion` y `trust`. El handler no consulta la tabla
`chatmessage` para B — solo `socialprofile`.

### Restricción de rol

El handler comprueba `session_id.startswith("user:")` al inicio. No hay
mecanismo genérico de restricción por rol en el toolset — este es el
primer caso que lo necesita. Si en el futuro más tools requieren restricción
por rol, ese sería el momento de generalizarlo en `toolset_selector.py`.

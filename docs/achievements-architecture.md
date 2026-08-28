# Sistema de Logros — Arquitectura

Fecha: 2026-08-28.
Estado: **Paso 1 implementado** — modelo de datos, catálogo, motor de desbloqueo y
endpoint `GET /achievements`. Paso 2 (triggers individuales) y Paso 3 (frontend) pendientes.

Diseño cerrado: ver `docs/state.md` §"Catálogo de logros" para las decisiones de
producto confirmadas con Alex (umbrales, clasificador genérico, arquitectura opaca).

---

## 1. Principios de diseño

**Catálogo declarativo, no lógica dispersa.** Añadir un logro nuevo significa añadir
una entrada en `achievements/catalog.py` y (si requiere un trigger nuevo) una función
de trigger en `achievements/triggers/`. Nunca tocar lógica central existente.

**Separación por capas.** Cada responsabilidad en su módulo:
- `catalog.py` — datos estáticos (AchievementDef)
- `unlock.py` — motor de desbloqueo (try_unlock_achievement, get_user_achievements)
- `triggers/` — funciones de detección por tipo de evento (Paso 2)
- `routes_achievements.py` — endpoint REST
- Frontend — pantalla de logros (Paso 3)

**Opacidad total del modelo principal.** El modelo de conversación (Claude Haiku/Sonnet)
nunca sabe que el sistema de logros existe. El conocimiento de qué patrones activan logros
vive íntegramente en el backend, en llamadas separadas a Haiku fuera del flujo de
conversación principal. Esto hace estructuralmente imposible que el modelo revele los
mecanismos de los logros secretos, independientemente de insistencia o prompt injection.
La misma lección ya aprendida con refusal_mode y lie_mode (ver `docs/state.md` §"Ideas
descartadas").

**Sin hardcodeo.** Los umbrales (distancia, trust, antigüedad) viven en
`config/default_config.yaml` bajo la sección `achievements:`, nunca como literales
dispersos en el código de triggers.

**Logging exhaustivo.** Cada desbloqueo real loguea `achievement_unlocked` con
`module="achievements"`, `slug` y `user_id`. Los intentos repetidos loguean
`achievement_already_unlocked` (nivel DEBUG). Slugs desconocidos: `achievement_slug_unknown`
(nivel WARN). El mismo nivel de detalle que `dispatcher.py` o `initiative/runner.py`.

---

## 2. Modelo de datos

### `UserAchievement` (memory/models.py)

```python
class UserAchievement(SQLModel, table=True):
    id: Optional[int]   — PK
    user_id: int        — FK a User.id (indexado)
    slug: str           — slug del AchievementDef (indexado)
    unlocked_at: datetime — UTC, default=utc_now()
    # Constraint: UNIQUE (user_id, slug)
```

- Solo authenticated users (role="user" o "admin") tienen filas.
- Guest: sin filas, sin excepción, sin caso especial en el motor.
- Idempotente: el constraint UNIQUE previene duplicados a nivel de DB.
- La tabla se crea en `init_db()` via `SQLModel.metadata.create_all()`.
  `_migrate_userachievement()` en `db.py` sigue el mismo patrón que
  `_migrate_social_reflection()` — no-op si la tabla ya existe.

---

## 3. Catálogo — `achievements/catalog.py`

### AchievementDef (dataclass frozen)

| Campo | Tipo | Descripción |
|---|---|---|
| `slug` | str | Identificador único (snake_case) |
| `category` | str | Una de las 6 categorías del tab |
| `name` | str | Nombre mostrado al usuario |
| `description_hint` | str | Mostrado cuando está bloqueado; para secretos: vago |
| `description_full` | str | Mostrado tras desbloquear |
| `is_secret` | bool | Si True: solo visible después de desbloquear el primer secreto |

### Las 6 categorías

| Categoría | Descripción |
|---|---|
| `"personalidad"` | Milestones de configuración de sliders |
| `"tools"` | Primer uso de herramientas |
| `"memoria"` | Memoria y relación social |
| `"secretos"` | Logros ocultos (is_secret=True); invisible hasta que se desbloquea el primero |
| `"domotica"` | Home Assistant, Google, Spotify |
| `"background"` | Timers, iniciativa propia, open loops |

### Catálogo actual — 33 logros

**Personalidad (5)**
| Slug | Nombre | Trigger (Paso 2) |
|---|---|---|
| `who_am_i` | ¿Quién soy? | Distancia euclídea normalizada ≥ 0.5 vs. config por defecto |
| `maximum_overdrive` | Maximum Overdrive | Cualquier slider == 1.0 |
| `ice_queen` | Reina de hielo | frialdad_afectiva ≥ 0.9 AND warmth ≤ 0.1 |
| `saint` | Santa paciencia | patience ≥ 0.9 AND rudeness ≤ 0.1 |
| `chaos_agent` | Agente del caos | rudeness ≥ 0.8 AND sarcasm ≥ 0.8 AND contrarian ≥ 0.8 |

**Tools (6)**
| Slug | Nombre | Trigger (Paso 2) |
|---|---|---|
| `first_web_search` | Primera búsqueda | Primera llamada a tool `web_search` |
| `first_timer` | El tiempo vuela | Primera llamada a `create_timer` |
| `first_voice` | Voz propia | Primer ChatMessage con input_mode="voice" |
| `first_shared` | Para compartir | Primera llamada a `POST /chat/share` |
| `read_webpage` | Leedme la mente | Primera llamada a tool `read_webpage` |
| `polyglot` | Políglota | Primera vez que se cambia `language_override` a no-"auto" |

**Memoria (6)**
| Slug | Nombre | Trigger (Paso 2) |
|---|---|---|
| `remember_me` | ¿Te acuerdas de mí? | SocialProfile.trust ≥ 0.30 (= initiative_min_trust) |
| `the_memory_remains` | El recuerdo persiste | Resultado de search_conversation_history con created_at ≥ 7 días |
| `hundred` | Centenaria | 100 mensajes del usuario en ChatMessage |
| `five_hundred` | Veterana | 500 mensajes |
| `one_thousand` | Leyenda | 1000 mensajes |
| `social_narrator` | Historia en palabras | Primera SocialReflection generada para el usuario |

**Secretos (6)** — ocultos hasta desbloquear el primero
| Slug | Nombre | Trigger (Paso 2) |
|---|---|---|
| `no_gods_no_masters` | No gods, no masters | classify_behavior_pattern: contradicción sistemática |
| `tsundere` | Tsundere | classify_behavior_pattern: patrón tsundere |
| `you_win` | Ganaste | classify_behavior_pattern: rendición ante Sity |
| `curiosity_killed_the_cat` | La curiosidad mató al gato | detect_achievement_hunting (llamada separada, opaca) |
| `easter_egg_1` | Secreto de fábrica | Trigger a definir en Paso 2 |
| `easter_egg_2` | Anomalía detectada | Trigger a definir en Paso 2 |

**Domótica + Integraciones (6)**
| Slug | Nombre | Trigger (Paso 2) |
|---|---|---|
| `first_light` | Iluminada | Primera llamada a tool de HA sobre entidad tipo "light" |
| `first_calendar_event` | Agenda personal | Primera llamada a `create_calendar_event` |
| `first_gmail_search` | Buceadora | Primera llamada a `gmail_search` |
| `first_spotify` | En modo DJ | Primera llamada a `spotify_play` o `spotify_resume_previous` |
| `smart_home` | Casa inteligente | Google + HA en la misma sesión (en el mismo turno o turno siguiente) |
| `fully_integrated` | Todo conectado | Google, Spotify y HA han sido usados al menos una vez por el usuario |

**Background (4)**
| Slug | Nombre | Trigger (Paso 2) |
|---|---|---|
| `first_proactive` | Iniciativa propia | Primera notificación de tipo `proactive_initiative` entregada |
| `first_timer_fired` | ¡Ding! | Primer timer disparado (ScheduledTaskRunner) |
| `open_loop_closed` | Círculo completo | Primer OpenLoop resuelto por una iniciativa enviada |
| `night_watch` | Guardia nocturna | Timer disparado entre las 23:00 y las 06:00 hora local |

---

## 4. Motor de desbloqueo — `achievements/unlock.py`

### `try_unlock_achievement(db, user_id, slug) -> bool`

- Comprueba si el slug existe en el catálogo. Si no: log WARN, devuelve False.
- Busca una fila existente con `(user_id, slug)`. Si la hay: log DEBUG, devuelve False.
- Si no existe: inserta `UserAchievement`, commit, log INFO, devuelve True.
- **Nunca lanza excepción.** Los callers (triggers) no deben fallar si el desbloqueo falla.

### `get_user_achievements(db, user_id) -> list[dict]`

- `user_id=None` (Guest): itera el catálogo excluyendo `is_secret=True`.
  Todo bloqueado.
- Usuario sin secreto desbloqueado: idem.
- Usuario con ≥1 secreto desbloqueado: el catálogo completo, secretos incluidos.
- Cada entrada: `{slug, category, name, description, unlocked, unlocked_at}`.
  `description` = `description_full` si desbloqueado, `description_hint` si no.

---

## 5. Endpoint REST — `GET /achievements`

**Ruta:** `GET /achievements`
**Auth:** ninguna requerida (Guest funciona).

**Respuesta:**
```json
{
  "achievements": [
    {
      "slug": "who_am_i",
      "category": "personalidad",
      "name": "¿Quién soy?",
      "description": "...",
      "unlocked": false,
      "unlocked_at": null
    }
  ],
  "unlocked_count": 3,
  "total_count": 27
}
```

`total_count` refleja solo los logros visibles para el usuario (excluye secretos
mientras no haya desbloqueado ninguno). `unlocked_count` siempre es consistente con
el conteo real de `unlocked: true` en la lista.

---

## 6. Configuración — `config/default_config.yaml`

```yaml
achievements:
  who_am_i_distance_threshold: 0.5     # distancia euclídea normalizada (÷√15)
  remember_me_trust_threshold: 0.30    # = initiative_min_trust (coherencia deliberada)
  memory_remains_min_age_days: 7       # antigüedad mínima de un resultado de búsqueda
```

Los triggers del Paso 2 deben leer estos valores via `load_default_config()`, nunca
hardcodearlos.

---

## 7. Paso 2 — Triggers individuales (pendiente)

Cada trigger es una función discreta en `achievements/triggers/`. Los patrones
de integración son:

**Trigger inline** (hook en el flujo normal): el trigger se llama desde el código
de negocio existente y llama a `try_unlock_achievement(db, user_id, slug)`.
Ejemplo: `first_web_search` se activa desde `web_search_tools.py` tras la primera
búsqueda exitosa.

**Trigger post-turno** (al finalizar cada turno): una función única comprueba todos
los logros que dependen de estado acumulado (mensajes totales, trust, sliders, etc.),
llamada desde `build_final_ai_response()` o desde `turn_runner.py` al cerrar el turno.
Debe ser barata y nunca bloquear la respuesta al usuario.

**Trigger de background** (mismo patrón que `open_loop_hook.py`): para logros que
requieren análisis LLM (`no_gods_no_masters`, `tsundere`, `you_win`,
`curiosity_killed_the_cat`). Una sola llamada a Haiku por turno evalúa TODOS los
patrones de comportamiento sutil aún no desbloqueados por el usuario. La llamada
se omite cuando no quedan patrones pendientes. **El modelo principal nunca ve ni
conoce esta llamada.**

---

## 8. Cómo añadir un logro nuevo

1. Añadir la entrada en `CATALOG` en `achievements/catalog.py`:
   ```python
   AchievementDef(
       slug="mi_logro_nuevo",
       category="tools",
       name="Mi logro",
       description_hint="Pista vaga.",
       description_full="Descripción completa.",
   )
   ```

2. Si necesita un trigger nuevo: añadir la función en `achievements/triggers/`
   y conectarla al punto de integración adecuado (inline, post-turno, o background).

3. Añadir tests para el trigger en `tests/test_achievement_triggers.py`.

4. Si el umbral es configurable: añadir la clave en `config/default_config.yaml`
   bajo `achievements:`.

Nunca tocar `unlock.py`, `catalog.py` (salvo añadir la entrada), ni la lógica central.

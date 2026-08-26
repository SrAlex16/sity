# Memoria Social Narrativa

Fecha diseño: 2026-08-24. Implementado y desplegado: 2026-08-25 — commit `386e476`.
Estado: **Implementado y en producción.** 8 tests en `tests/test_social_memory_narrative.py` — todos en verde.

Este documento amplía el sistema de memoria social numérico ya existente
(`docs/social-memory.md`) con dos capas nuevas: reflexión narrativa y trazabilidad
de evidencia. El sistema numérico (`opinion`/`trust`, EMA α=0.3, job de background)
**no se modifica en ningún aspecto**.

---

## 1. Motivación

El bloque social que actualmente se inyecta en el prompt describe la relación en
términos numéricos y etiquetas planas ("positiva (0.34)", "consolidada (0.55)"). Eso
responde al *qué* pero no al *por qué*.

Un "por qué" —"últimamente hace preguntas más técnicas y suele aceptar sugerencias
con facilidad"— le da al modelo contexto interpretativo que modula la respuesta de
forma más rica que un número solo. La hipótesis a validar es que esto produce
respuestas notablemente más coherentes con la relación real. Esa hipótesis se
valida por observación directa (ver §8), no por experimento A/B.

---

## 2. Arquitectura de 3 capas

### Capa 1 — Numérico (ya existe, sin cambios)

`SocialProfile.opinion` y `.trust`, calculados determinísticamente por
`_run_social_update` en background. Son la **autoridad real** sobre la relación.
Ningún componente de las capas 2 y 3 puede modificarlos.

### Capa 2 — Narrativo (nuevo)

Una reflexión breve en lenguaje natural, generada por el **mismo job** que ya
recalcula `opinion`/`trust`, describiendo el patrón observable de la relación.
Ejemplo: *"Este usuario suele compartir contexto técnico detallado antes de preguntar
y tiende a seguir las sugerencias sin mucha resistencia. Los intercambios recientes
han sido productivos y sin fricción notable."*

La reflexión es **descriptiva**, nunca prescriptiva. No menciona valores numéricos
ni indica cómo debería sentirse Sity. El job la genera leyendo mensajes reales;
el modelo la escribe sobre esos mensajes, no sobre `opinion`/`trust`.

### Capa 3 — Evidencia (nuevo)

Cada reflexión lleva adjuntos los IDs de los `ChatMessage` que la sustentan.
Permite responder "¿por qué cree Sity esto?" con registros auditables, sin
necesitar una segunda interpretación del LLM.

---

## 3. Regla dura — anti prompt-injection

**La reflexión NUNCA escribe directamente sobre `opinion` ni `trust`.**

El mismo principio ya aplicado al sistema numérico (el tag `<R:N>` viene del modelo,
nunca del texto del usuario; la única ruta de escritura a `opinion`/`trust` es el
job de background) se extiende aquí: el contenido de `SocialReflection.content` es
de solo lectura para Sity durante la conversación. El job lo genera; Sity lo lee.
Ningún texto que el usuario pueda enviar puede modificar una reflexión directamente.

---

## 4. Modelo de datos

### 4.1 Tabla nueva: `SocialReflection`

```sql
CREATE TABLE socialreflection (
    id              INTEGER PRIMARY KEY,
    profile_id      INTEGER NOT NULL,  -- FK a SocialProfile.id
    category        TEXT    NOT NULL DEFAULT 'general',
    content         TEXT    NOT NULL,  -- texto narrativo, 2-4 frases
    evidence_json   TEXT    NOT NULL DEFAULT '[]',  -- JSON list[int]: ChatMessage.id
    opinion_at_gen  REAL    NOT NULL,  -- SocialProfile.opinion cuando se generó
    trust_at_gen    REAL    NOT NULL,  -- SocialProfile.trust cuando se generó
    created_at      DATETIME NOT NULL,
    expires_at      DATETIME NOT NULL,  -- created_at + 30 días
    superseded_at   DATETIME           -- NULL = activa para su categoría
);
CREATE INDEX idx_srefl_profile ON socialreflection(profile_id);
```

**Por qué tabla nueva y no extender `OpinionSnapshot`:**
`OpinionSnapshot` es un historial de auditoría numérica — registra cada cálculo
de `opinion`/`trust`. Tiene semántica de append-only y se consulta principalmente
en bulk (para calcular `pstdev` en la fórmula de trust). `SocialReflection` tiene
semántica de "una activa por categoría" y se consulta en singular ("dame la
reflexión activa del usuario X"). Mezclar ambas introduciría NULLs masivos en
`OpinionSnapshot` y haría la consulta de reflexión activa más compleja sin beneficio.

### 4.2 Definición de "activa"

Una reflexión es activa para su categoría si:

```
superseded_at IS NULL AND expires_at > NOW()
```

Solo puede existir **una** reflexión activa por `(profile_id, category)` en todo
momento. Se garantiza por el mecanismo de reemplazo (§5.3).

### 4.3 Campos `opinion_at_gen` / `trust_at_gen`

Almacenan los valores de `opinion` y `trust` en el momento de generar la reflexión.
Son necesarios para calcular el delta en el siguiente ciclo del job
(§5.2, criterio de señal suficiente) sin necesidad de buscar en `OpinionSnapshot`
por timestamp.

### 4.4 Categoría en v1

Una sola categoría: `"general"`. Esto simplifica completamente el mecanismo de
contradicción (siempre hay como máximo una reflexión activa por perfil) y deja
abierta la extensión a categorías múltiples sin cambio de esquema.

La decisión de añadir más categorías (p.ej. `"communication_style"`, `"topics"`)
se toma después de validar con uso real que la reflexión básica aporta valor.

---

## 5. Lógica del job de background

El job existente (`_run_social_update` en `backend/app/social/update.py`) ya
hace, por este orden:

1. `BEGIN IMMEDIATE`
2. Leer perfil y cargas pendientes
3. Calcular `batch_opinion`, `new_opinion`, `new_trust`
4. `UPDATE socialprofile`
5. `INSERT INTO opinionsnapshot`
6. `COMMIT`

Se añaden los pasos **7–10** después del commit, fuera de la transacción principal:

### 5.1 Paso 7 — Comprobar señal suficiente

```python
def _has_sufficient_signal(profile: SocialProfile, latest_reflection: Optional[SocialReflection], db: Session) -> bool:
    if latest_reflection is None:
        # Primera reflexión: basta con que haya al menos N mensajes
        count = db.exec(
            select(func.count()).where(ChatMessage.session_id == f"user:{profile.user_id}")
        ).one()
        return count >= cfg.reflection_min_new_messages

    # Mensajes nuevos desde la última reflexión
    new_msg_count = db.exec(
        select(func.count())
        .where(ChatMessage.session_id == f"user:{profile.user_id}")
        .where(ChatMessage.created_at > latest_reflection.created_at)
    ).one()

    opinion_delta = abs(profile.opinion - latest_reflection.opinion_at_gen)

    return (
        new_msg_count >= cfg.reflection_min_new_messages
        or opinion_delta >= cfg.reflection_min_opinion_delta
    )
```

**Por qué este criterio concreto:**

- `new_msg_count >= N` (default: 20): evita generar reflexión en cada ciclo del
  job (que corre cada 10 turnos). Con N=20 se necesitan al menos dos ciclos completos
  desde la última reflexión antes de considerar una nueva.
- `opinion_delta >= 0.15`: captura cambios de tendencia relevantes aunque no haya
  acumulado todavía 20 mensajes nuevos. Un delta de 0.15 sobre la escala [-1, +1]
  representa una señal no trivial (casi 4 cargas +1 consecutivas desde cero).
- El OR entre ambas condiciones permite que un cambio brusco de relación genere
  una reflexión rápido, mientras que en ausencia de cambio brusco se espera a
  tener suficiente material nuevo.

### 5.2 Paso 8 — Recopilar evidencia

Tomar los `reflection_max_evidence_messages` (default: 15) `ChatMessage` más
recientes del usuario (solo rol `user` y `sity`; excluir mensajes de sistema).
Guardar sus IDs como `evidence_json`.

### 5.3 Paso 9 — Generar reflexión (llamada al LLM)

Prompt dedicado, separado del pipeline de respuesta de conversación:

```
Eres un observador que lee un extracto de conversación y escribe una reflexión
breve sobre el patrón de interacción observado.

REGLAS:
- Escribe 2-4 frases en español.
- Describe solo lo que observas en los mensajes: temas frecuentes, estilo
  comunicativo, tipo de preguntas, actitud general.
- NO menciones valores numéricos de ningún tipo.
- NO uses las palabras "opinión", "trust", "confianza" como concepto abstracto.
- NO hagas predicciones ni recomendaciones.
- NO uses más de 100 palabras.

Mensajes recientes:
{formatted_evidence}
```

La llamada usa el mismo proveedor LLM que el resto del sistema (no requiere
modelo específico; el que sea suficientemente bueno para la conversación es
suficiente para la reflexión).

Si la llamada falla (timeout, error de API), el job loguea
`social_reflection_generation_failed` y continúa sin generar reflexión.
No se reintenta hasta el siguiente ciclo del job.

### 5.4 Paso 10 — Reemplazar reflexión activa

```python
# Fuera de BEGIN IMMEDIATE — operación post-commit sobre la reflexión
with Session(engine) as db:
    active = db.exec(
        select(SocialReflection)
        .where(SocialReflection.profile_id == profile.id)
        .where(SocialReflection.category == "general")
        .where(SocialReflection.superseded_at == None)
        .where(SocialReflection.expires_at > utc_now())
    ).first()

    if active:
        active.superseded_at = utc_now()
        db.add(active)

    new_ref = SocialReflection(
        profile_id=profile.id,
        category="general",
        content=generated_content,
        evidence_json=json.dumps(evidence_ids),
        opinion_at_gen=profile.opinion,
        trust_at_gen=profile.trust,
        expires_at=utc_now() + timedelta(days=cfg.reflection_max_age_days),
    )
    db.add(new_ref)
    db.commit()
```

**Por qué fuera de la transacción principal:**
El `BEGIN IMMEDIATE` de la transacción principal dura microsegundos (es una
escritura en SQLite). La llamada LLM puede tardar 3-10 segundos. Hacer el LLM
call dentro del IMMEDIATE bloquearía cualquier escritura de la app durante ese
tiempo. La transacción de escritura de la reflexión es independiente y corta;
si falla, el perfil numérico ya está actualizado correctamente.

---

## 6. Inyección en el prompt

### 6.1 Extensión de `_build_social_context_block`

Actualmente devuelve:

```
Contexto de relación (uso interno — informa tono y disposición, no citar directamente):
- Disposición hacia este interlocutor: positiva (0.34)
- Confianza acumulada: consolidada (0.55)
Deja que esto module el tono con el que te expresas; no menciones estos valores salvo que resulte muy natural.
```

Con reflexión activa, añade una línea:

```
Contexto de relación (uso interno — informa tono y disposición, no citar directamente):
- Disposición hacia este interlocutor: positiva (0.34)
- Confianza acumulada: consolidada (0.55)
- Patrón observado: últimamente hace preguntas técnicas precisas y suele aceptar sugerencias con facilidad.
Deja que esto module el tono con el que te expresas; no menciones estos valores salvo que resulte muy natural.
```

Sin reflexión activa: comportamiento idéntico al actual.

### 6.2 Consulta de reflexión activa

```python
reflection = db.exec(
    select(SocialReflection)
    .where(SocialReflection.profile_id == profile.id)
    .where(SocialReflection.superseded_at == None)
    .where(SocialReflection.expires_at > utc_now())
    .order_by(SocialReflection.created_at.desc())
    .limit(1)
).first()
```

Solo lectura; no toca ningún campo numérico.

### 6.3 Caducidad silenciosa

Pasados 30 días desde la generación, `expires_at < NOW()` y la reflexión deja de
inyectarse sin ningún proceso activo de limpieza. Si la relación sigue siendo la
misma, el job regenerará una reflexión similar en el siguiente ciclo en que se
cumpla la condición de señal suficiente. Si el usuario ha dejado de usar la app,
no se generará ninguna hasta que vuelva a interactuar.

**Por qué 30 días:** es el orden de magnitud en que una relación puede cambiar de
forma perceptible. Menos tiempo generaría reflexiones que caducan antes de
contribuir nada. Más tiempo perpetúa impresiones estancadas en usuarios que han
cambiado de comportamiento.

---

## 7. Configuración

```yaml
# config/default_config.yaml (sección social, añadir a lo ya existente)
social:
  update_threshold_turns: 10           # ya existe
  reflection_min_new_messages: 20      # mensajes nuevos mínimos desde la última reflexión
  reflection_min_opinion_delta: 0.15   # Δ|opinion| mínimo para saltarse el límite de mensajes
  reflection_max_age_days: 30          # duración de la reflexión antes de caducar
  reflection_max_evidence_messages: 15 # mensajes recientes que se pasan al LLM
```

---

## 8. Validación — observación directa

La hipótesis ("la reflexión produce respuestas más coherentes con la relación real")
se valida por observación directa: Alex usa el sistema un tiempo con atención
consciente y decide por criterio propio si el resultado es perceptiblemente mejor.

**Por qué no experimento A/B formal:**
Requeriría instrumentar un toggle, definir métricas de cohesión, dividir sesiones
en grupos, y analizar datos. El coste de instrumentación es desproporcionado para
validar si algo tan cualitativo como "la conversación suena más natural" funciona.
Si tras uso real la respuesta es "no noto diferencia", el feature se elimina. Si
la respuesta es "sí, claramente mejor", se mantiene y se evalúa si ampliar
categorías o ajustar parámetros.

---

## 9. Caso límite documentado — evento extremo entre ciclos del job

**Pregunta de Alex en el diseño:** ¿qué pasa si el job corre en el turno 10 y en
el turno 11 ocurre algo extremo (p.ej. un insulto), pero no se procesa hasta el
turno 20?

**Conclusión acordada:** no es un problema nuevo introducido por la reflexión
narrativa. Es una propiedad ya aceptada del sistema numérico:

- El tag `<R:-2>` del turno 11 se acumula en `pending_loads_json` inmediatamente.
- En el turno 20 (próximo disparo del job), ese -2 entra con doble peso en el
  cálculo de `batch_opinion`, y la EMA con α=0.3 mueve `opinion` de forma
  proporcional a la magnitud del evento.
- La EMA está diseñada explícitamente para que un solo evento extremo no voltee
  la opinión de golpe — para estabilidad ante interacciones puntuales. Un solo -2
  entre nueve turnos neutrales mueve menos que nueve -2 consecutivos, lo cual es
  exactamente el comportamiento deseado.

La reflexión narrativa **hereda el mismo timing** que el cálculo numérico del que
depende. No tiene mecanismo separado de "detección de evento crítico en tiempo
real" porque no lo necesita: si el evento es realmente extremo y se repite en
turnos sucesivos, cambia la `opinion` suficientemente para superar el umbral de
`reflection_min_opinion_delta` (0.15) y dispara una nueva reflexión en el próximo
ciclo.

Este razonamiento se documenta aquí como precedente para no reabrir la discusión
sin un argumento nuevo que lo justifique.

---

## 10. Lo que NO está en este diseño

Los siguientes temas NO se diseñan en esta fase:

- **Behavior Controller** — no se añade ninguna capa que modifique `opinion`/`trust`
  basándose en la reflexión.
- **Theory of Mind** — no se modela lo que el usuario piensa de Sity, solo lo
  que Sity observa del usuario.
- **Relaciones multi-dimensión** — una sola categoría `"general"` en v1.
  Categorías adicionales (p.ej. `"communication_style"`, `"topics_of_interest"`)
  se añaden solo si la validación por observación directa indica que aportarían
  algo que la categoría general no captura.
- **Normas sociales** — nada de reglas de comportamiento basadas en el perfil social.
- **Exposición al usuario** — la reflexión es opaca, igual que `opinion`/`trust`.
  No hay UI, no hay endpoint de consulta pública para este campo.

---

## 11. Archivos modificados en implementación

| Archivo | Cambio |
|---|---|
| `backend/app/memory/models.py` | Clase `SocialReflection` (SQLModel, table=True) |
| `backend/app/memory/db.py` | `_migrate_social_reflection()` en el mismo patrón que las otras migraciones |
| `backend/app/social/update.py` | Pasos 7–10 después del commit principal (+214 líneas) |
| `backend/app/chat/prompt_context.py` | Extensión de `_build_social_context_block` (+38 líneas) |
| `config/default_config.yaml` | 4 claves nuevas bajo `social:` |
| `tests/test_social_memory_narrative.py` | 8 tests (ver §12) — todos en verde |
| `tests/test_social_memory.py` | 22 tests existentes ampliados (+22 líneas) |

---

## 12. Cobertura de tests mínima

- `test_reflection_not_generated_if_insufficient_signal` — menos de `min_new_messages`
  mensajes y delta < umbral → no se inserta ninguna `SocialReflection`
- `test_reflection_generated_after_enough_messages` — ≥ 20 mensajes → se inserta
  reflexión con `superseded_at = None` y `expires_at ≈ now + 30d`
- `test_reflection_generated_on_large_opinion_delta` — delta ≥ 0.15 con pocos
  mensajes nuevos → reflexión generada igualmente
- `test_old_reflection_superseded_on_new_generation` — hay reflexión activa, job
  genera nueva → la antigua tiene `superseded_at != None`, la nueva `superseded_at = None`
- `test_expired_reflection_not_injected` — `expires_at` en el pasado →
  `_build_social_context_block` no incluye línea de patrón
- `test_active_reflection_injected_in_prompt` — reflexión activa presente →
  texto de `content` aparece en el bloque social del prompt
- `test_reflection_generation_failure_does_not_block_job` — LLM call lanza
  excepción → `opinion`/`trust` ya actualizados correctamente, no se inserta reflexión,
  no propaga excepción
- `test_guest_never_gets_reflection` — sesión `guest:` → consulta nunca llega a
  `SocialReflection`

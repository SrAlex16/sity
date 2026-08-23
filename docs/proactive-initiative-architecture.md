# Arquitectura del sistema de iniciativa propia de Sity

Fecha: 2026-08-18.
Estado: **IMPLEMENTADO, VERIFICADO EN PRODUCCIÓN Y COMPLETO — 2026-08-24**.
Este documento captura las decisiones de diseño + el historial real de verificación
y los bugs encontrados en producción (2026-08-19 → 2026-08-24).

Módulos implementados:
- `backend/app/memory/models.py` — `OpenLoop`, `InitiativeEvalLog`
- `backend/app/initiative/settings.py` — `InitiativeSettings`, `get/set_initiative_settings`
- `backend/app/initiative/open_loop_hook.py` — detección fire-and-forget por turno (Haiku)
- `backend/app/initiative/detector.py` — 3 trigger checks sin Haiku
- `backend/app/initiative/evaluator.py` — SHOULD_I_TALK? (rate limits + Haiku + EvalLog)
- `backend/app/initiative/runner.py` — job periódico 6h, pipeline completo
- `backend/app/initiative/_json_utils.py` — `strip_json_fences()` compartida (añadida en verificación)
- `backend/app/main.py` — `start_initiative_runner` en `on_startup`
- Tests: 128 tests en `test_initiative_step1/2/3/4.py`

---

## 0. Principio de diseño

El sistema responde a un problema concreto observado en uso real: Sity no inicia
conversación aunque haya una razón genuina para hacerlo (pregunta sin retomar,
días sin hablar, intención mencionada y olvidada). La solución es mínima —
tres triggers, un job de 6 horas, una llamada barata a Haiku — y reutiliza al
100% la infraestructura de notificaciones ya construida. Nada de Initiative Score
matemático, nada de aprendizaje de horarios, nada de feedback loop automático.
Si esta base demuestra valor, cada capa futura responde a un problema observado,
no a una arquitectura teóricamente bonita.

---

## 1. Alcance y exclusiones

| Dimensión | Decisión |
|---|---|
| **Roles** | Solo `User` y `Admin`. Guest nunca — no tiene continuidad entre sesiones, no tiene `SocialProfile`. |
| **Triggers** | Tres: `conversation_abandoned`, `long_inactivity`, `open_loop`. |
| **Mecanismo** | Job en background cada 6h + una llamada a Haiku por usuario candidato. |
| **Límites duros** | Los ya existentes en `default_config.yaml §notifications` — no se crea un sistema paralelo. |
| **Entrega** | `proactive_initiative` ya reconocido por `dispatcher.py` — este sistema es el tercer emisor, no un canal nuevo. |
| **Configuración** | Un toggle maestro + 3 sub-toggles por sesión, opt-out (todos activos por defecto). |

**Fuera de alcance en esta fase:**
- Los 8 triggers adicionales del análisis previo (external event, curiosidad emergente, contradicciones, etc.).
- Initiative Score con variables ponderadas.
- Aprendizaje de horarios del usuario.
- Feedback loop automático de éxito/fracaso.
- Mostrar la causa de la iniciativa al usuario en la UI.

---

## 2. Las dos preguntas — arquitectura de decisión

El sistema separa explícitamente dos preguntas que tienen naturaleza distinta
y que NO deben colapsarse en una sola función.

### SHOULD_I_TALK? — ¿hay una razón genuina?

Responde el **motor de decisión** (`evaluator.py`): hay una condición trigger
detectada Y Haiku confirma que esa condición representa algo real que vale la
pena mencionar. Este es el juicio de contenido.

Entradas: trigger detectado + últimos mensajes relevantes + SocialProfile + contexto del open_loop si aplica.
Salida: `(decision: "send" | "skip", content: str | None, reason: str)`.

### IS_NOW_A_GOOD_TIME? — ¿es buen momento?

Responden los **límites duros del backend** (`runner.py` antes de llamar a Haiku):

1. `initiative_silence_hours: 4` — si el usuario habló con Sity en las últimas 4h, no iniciar.
2. `initiative_min_trust: 0.30` — si `SocialProfile.trust < 0.30`, Sity no tiene relación establecida para iniciar.
3. Rate limiting del dispatcher — `max_proactive_per_day_user: 1` y `initiative_cooldown_hours: 24`.
4. Toggle maestro + sub-toggle del trigger correspondiente desactivado → skip inmediato.

**Orden de evaluación en código:** IS_NOW_A_GOOD_TIME? primero (consultas DB
baratas), SHOULD_I_TALK? después (coste de tokens). Si el momento no es bueno,
Haiku nunca se llama.

---

## 3. Arquitectura de 4 capas

```
┌─────────────────────────────────────────────────────────────────┐
│  CAPA 1 — RECOLECCIÓN DE EVENTOS                                │
│  initiative/detector.py                                         │
│  Para cada usuario elegible, detecta qué trigger(es) aplican   │
│  Produce: list[TriggerCandidate] (sin llamada a LLM)            │
└──────────────────────────────┬──────────────────────────────────┘
                               │ TriggerCandidate
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  CAPA 2 — MEMORIA / ESTADO                                      │
│  initiative/models.py                                           │
│  OpenLoop — intenciones pendientes detectadas por turno         │
│  InitiativeEvalLog — historial de todas las evaluaciones        │
│  Setting rows con prefix "initiative." — toggles por sesión     │
└──────────────────────────────┬──────────────────────────────────┘
                               │ contexto enriquecido
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  CAPA 3 — MOTOR DE DECISIÓN                                     │
│  initiative/runner.py — job 6h, IS_NOW_A_GOOD_TIME?            │
│  initiative/evaluator.py — llamada Haiku, SHOULD_I_TALK?        │
│  Límites duros: silence_hours + trust + dispatcher rate limit   │
└──────────────────────────────┬──────────────────────────────────┘
                               │ NotificationFact (type="proactive_initiative")
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  CAPA 4 — GENERACIÓN Y ENTREGA                                  │
│  notifications/dispatcher.py — YA EXISTE, sin cambios           │
│  notifications/fact.py — NotificationFact ya definido           │
│  Canal: SSE / push / pending según estado del suscriptor        │
└─────────────────────────────────────────────────────────────────┘

Además, un hook por turno para detectar open_loops en tiempo real:
  initiative/open_loop_hook.py — llamado desde ai_orchestrator.py
  tras save_message, sin llamada a LLM, solo regex.
```

---

## 4. Capa 1 — Recolección de eventos (`detector.py`)

El detector recibe una sesión elegible y devuelve una lista de candidatos
(puede haber cero, uno o varios triggers simultáneos — en ese caso el evaluator
prioriza).

```python
@dataclass
class TriggerCandidate:
    trigger_type: str          # "conversation_abandoned" | "long_inactivity" | "open_loop"
    session_id: str
    context: dict              # datos concretos para el prompt de Haiku
    open_loop_id: str | None   # rellenado solo para trigger_type="open_loop"
```

### 4.1 `conversation_abandoned`

**Condición:** el último mensaje de la sesión es de rol `sity` (Sity escribió algo
y el usuario no respondió), con antigüedad de entre `conversation_abandoned_min_hours`
y `conversation_abandoned_max_days`.

**Ventana:** entre 24h y 4 días. Antes de 24h el usuario puede estar simplemente
ocupado. Después de 4 días ya es inactividad prolongada, que es otro trigger.

**Datos concretos para el contexto:**
- Texto de los últimos 3 mensajes (la parte de la conversación que quedó abierta).
- `hours_since_last_message` (para que Haiku calibre la urgencia).
- `SocialProfile` (opinion, trust).

**Consulta DB:** `SELECT * FROM chatmessage WHERE session_id=? ORDER BY created_at DESC LIMIT 3` y
verificar que la primera fila tenga `role='sity'` y `created_at` en la ventana.

### 4.2 `long_inactivity`

**Condición:** ningún mensaje en la sesión (de ningún rol) en los últimos
`long_inactivity_min_days` días.

**Ventana:** > 5 días. Configurable. No tiene ventana máxima — si llevan
30 días sin hablar, sigue aplica (aunque el rate limiter garantiza que no
se repite cada 6h).

**Datos concretos para el contexto:**
- `days_since_last_message`.
- Texto del último mensaje enviado (para que Haiku tenga contexto de qué se habló).
- `SocialProfile` (opinion, trust).

**Consulta DB:** `SELECT MAX(created_at) FROM chatmessage WHERE session_id=?`

### 4.3 `open_loop`

**Condición:** existe al menos un `OpenLoop` con `status="pending"` y
`detected_at < now - open_loop_min_days` para esta sesión.

**Ventana:** > 3 días desde la detección. Si el usuario mencionó algo ayer,
es demasiado pronto — puede estar ya haciéndolo.

**Datos concretos para el contexto:**
- Texto original del mensaje del usuario donde se detectó la intención.
- `detected_at` (cuánto tiempo lleva pendiente).
- Últimos 5 mensajes de la sesión DESPUÉS de `detected_at` (para que Haiku evalúe si fue resuelto).

**El job NO marca el open_loop como resuelto automáticamente.** Haiku decide si
está resuelto en el momento de evaluación:
- Si concluye que fue resuelto en conversación posterior → marca `status="resolved"`, skip.
- Si concluye que sigue pendiente → SHOULD_I_TALK? con ese contexto.
- Si ya fue used para dispatch → `status="dispatched"`, no se repite.

---

## 5. Capa 2 — Modelo de datos

### 5.1 `OpenLoop` (tabla nueva en `memory/models.py`)

```python
class OpenLoop(SQLModel, table=True):
    id: str = Field(primary_key=True)         # "ol_<hex8>"
    session_id: str = Field(index=True)
    user_message: str                          # mensaje completo donde se detectó la intención
    extracted_intent: str = Field(default="") # frase clave extraída por el regex (para contexto)
    detected_at: datetime = Field(default_factory=utc_now)
    status: str = Field(default="pending")    # "pending" | "resolved" | "dispatched" | "expired"
    resolved_at: Optional[datetime] = Field(default=None)
    expires_at: datetime                       # detected_at + open_loop_ttl_days
```

**Ciclo de vida:**
- `pending` → estado inicial.
- `resolved` → el evaluador concluye que los mensajes posteriores resolvieron la intención.
- `dispatched` → se usó como base de una iniciativa enviada. No se repite.
- `expired` → `expires_at` ha pasado sin resolución ni dispatch. El GC lo puede purgar.

**GC:** el runner de 6h, al inicio, marca `expired` los `OpenLoop` donde
`expires_at < now` y `status="pending"`. Permite que la tabla no crezca indefinidamente.

**Índice compuesto:** `(session_id, status)` — el runner filtra siempre por ambos.

### 5.2 `InitiativeEvalLog` (tabla nueva en `memory/models.py`)

Registra TODAS las evaluaciones — tanto las que resultaron en envío como las que
no. Es la fuente de verdad para auditar "¿por qué Sity decidió escribir?" y
"¿por qué eligió no hacerlo?"

```python
class InitiativeEvalLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    trigger_type: str                          # "conversation_abandoned" | "long_inactivity" | "open_loop"
    decision: str                              # "send" | "skip"
    skip_reason: Optional[str] = Field(default=None)
    # "trust_too_low" | "silence_recent" | "rate_limited" | "toggle_disabled"
    # "model_skip" | "open_loop_resolved" | "no_trigger_condition"
    haiku_verdict: Optional[str] = Field(default=None)   # "send" | "skip" | None (no se llamó)
    haiku_reasoning: Optional[str] = Field(default=None) # extracto del JSON de Haiku (≤ 300 chars)
    message_preview: Optional[str] = Field(default=None) # primeros 100 chars del mensaje enviado
    trigger_context_json: str = Field(default="{}")      # datos del TriggerCandidate serializados
    open_loop_id: Optional[str] = Field(default=None)   # si trigger_type="open_loop"
    evaluated_at: datetime = Field(default_factory=utc_now)
```

**Retención:** 60 días (mismo TTL que `audit_logs_ttl_days`). Purgado por el GC
existente o por un nuevo GC en el runner de iniciativa.

### 5.3 Configuración granular por sesión

No se crea una tabla nueva. Se usan filas `Setting` con el prefijo `initiative.`,
mismo patrón que `_VOICE_PER_SESSION` en `settings_service.py`.

| Setting key | Tipo | Default | Descripción |
|---|---|---|---|
| `initiative.enabled` | bool | `True` | Toggle maestro — habilita/deshabilita todo |
| `initiative.trigger_conversation_abandoned` | bool | `True` | Sub-toggle "Conversaciones abandonadas" |
| `initiative.trigger_long_inactivity` | bool | `True` | Sub-toggle "Reconexión tras inactividad" |
| `initiative.trigger_open_loop` | bool | `True` | Sub-toggle "Seguimiento de temas pendientes" |

Los sub-toggles solo tienen efecto si el maestro está activo. Si el maestro está
desactivado, el runner saltea la sesión sin leer los sub-toggles.

`initiative/settings.py` expone `InitiativeSettings` (Pydantic) y las constantes:

```python
_INITIATIVE_PER_SESSION = (
    "enabled",
    "trigger_conversation_abandoned",
    "trigger_long_inactivity",
    "trigger_open_loop",
)
```

`get_initiative_settings(session_id)` y `set_initiative_settings(...)` siguen
el mismo patrón que `get_voice_settings` / `set_voice_settings`.

---

## 6. Capa 3 — Motor de decisión

### 6.1 `runner.py` — job de 6 horas

Corrutina asyncio iniciada en `main.py on_startup`, mismo patrón que
`timers/runner.py:start_runner(loop)` y `notifications_gc_loop()`.

**Pseudocódigo del loop:**

```
cada 6h:
  1. GC: marcar expired los OpenLoop expirados
  2. Consultar todos los session_id con initiative.enabled = True (de Setting)
     + filtrar solo User y Admin (session_id.startswith("user:"))
  3. Para cada session_id:
     a. IS_NOW_A_GOOD_TIME? — verificaciones baratas:
        - initiative.enabled == True → ya garantizado (paso 2)
        - last message in session < initiative_silence_hours → skip
        - SocialProfile.trust < initiative_min_trust → skip
        - dispatcher ya entregó proactive_initiative hoy → skip (query NotificationLog)
     b. detector.get_trigger_candidates(session_id, db) → list[TriggerCandidate]
        - filtra por sub-toggles activos
        Si vacía → skip (log: "no_trigger_condition")
     c. Priorizar candidatos: open_loop > conversation_abandoned > long_inactivity
        (si hay varios, solo evaluar el de mayor prioridad para esta ronda)
     d. SHOULD_I_TALK? — evaluator.evaluate(candidate, db) → EvalResult
     e. Persistir InitiativeEvalLog (siempre, sea send o skip)
     f. Si decision="send":
        - Construir NotificationFact y llamar dispatcher.dispatch()
        - Si trigger_type="open_loop": marcar OpenLoop.status="dispatched"
```

**Logging en cada paso del job:**

```python
write_log(level="INFO", module="initiative", event="runner_cycle_start",
    payload={"eligible_sessions": N})

write_log(level="INFO", module="initiative", event="session_skipped",
    session_id=..., payload={"reason": "silence_recent" | "trust_too_low" | "rate_limited" | "no_trigger"})

write_log(level="INFO", module="initiative", event="evaluation_complete",
    session_id=..., payload={"trigger": ..., "decision": "send" | "skip", "reason": ...})

write_log(level="INFO", module="initiative", event="runner_cycle_done",
    payload={"elapsed_ms": ..., "evaluated": N, "sent": M, "skipped": K})
```

### 6.2 `evaluator.py` — la llamada a Haiku

`evaluate(candidate: TriggerCandidate, db: Session) -> EvalResult`

```python
@dataclass
class EvalResult:
    decision: str          # "send" | "skip"
    message: str | None    # None si decision="skip"
    reasoning: str         # extracto para InitiativeEvalLog.haiku_reasoning
```

**Prompt a Haiku** — estructura en JSON para parse determinista:

```
Eres Sity. Decides si iniciar una conversación con el usuario.

CONTEXTO:
- Trigger: {trigger_type}
- Perfil social: opinion={opinion:.2f}, trust={trust:.2f}
- {contexto específico del trigger: mensajes, open_loop_text, días de inactividad...}

REGLAS:
- Solo escribe si tienes algo genuino que aportar.
- Si el tema ya fue resuelto en la conversación, responde skip.
- Si la inactividad no tiene contexto aprovechable, responde skip.
- Si decides escribir, el mensaje debe ser corto (1–3 frases), natural, en el tono habitual.
- No menciones que "detectaste" nada ni que lleves días sin hablar de forma explícita.

Responde ÚNICAMENTE en JSON:
{"decision": "send" | "skip", "message": "...", "reasoning": "..."}
```

**Contexto inyectado por trigger:**

| Trigger | Contexto específico |
|---|---|
| `conversation_abandoned` | Últimos 3 mensajes en formato rol: texto. `hours_since_last_message`. |
| `long_inactivity` | Último mensaje + `days_since_last_message`. |
| `open_loop` | `extracted_intent` del OpenLoop + últimos 5 mensajes DESPUÉS de `detected_at`. |

**Parse del response:** `json.loads(resp.text)` con fallback a `skip` si malformado.
Si Haiku devuelve `tool_calls` no vacío (no debería, no se pasan tools), log WARN y skip.

**Coste estimado — evaluator (job 6h):** una llamada Haiku con ~500 tokens de
entrada y ~100 de salida ≈ $0.0001 por evaluación. Con 5 usuarios User activos
y 4 ciclos/día → ~$0.002/día.

**Coste estimado — open_loop_hook (por turno):** llamada Haiku con ~150 tokens
de entrada (prompt + mensaje de usuario típico) y ~30 tokens de salida ≈ $0.00005
por turno. Este coste escala con el volumen de mensajes de User/Admin:

| Mensajes/día (por usuario) | Coste/usuario/día | 5 usuarios activos |
|---|---|---|
| 20 | ~$0.001 | ~$0.005/día |
| 50 | ~$0.0025 | ~$0.0125/día |
| 100 | ~$0.005 | ~$0.025/día |

A diferencia del job de 6h (coste fijo por ciclo), el hook escala linealmente
con la actividad. A los niveles actuales del proyecto (despliegue personal,
pocos usuarios) sigue siendo despreciable (~$0.15–$0.75/mes para el hook más
los ~$0.06/mes del evaluator). Si el número de usuarios escala significativamente,
este es el primer coste a revisar.

---

## 7. Capa 4 — Generación del `NotificationFact`

El runner construye el fact y llama al dispatcher ya existente. No hay código nuevo
en `dispatcher.py` — `proactive_initiative` ya está reconocido.

```python
fact = NotificationFact(
    session_id=candidate.session_id,
    notification_type="proactive_initiative",
    fact_id=f"initiative:{candidate.session_id}:{evaluated_at.date().isoformat()}",
    payload={
        "title": "Sity",
        "body": message[:80],       # snippet para push
        "full_text": message,       # texto completo para SSE (lo muestra como burbuja de chat)
        "trigger_type": candidate.trigger_type,  # para el frontend si lo necesita
    },
    urgency="low",   # no despierta al usuario — pending si no hay SSE activo
    subtype=candidate.trigger_type,
)
dispatcher.dispatch(fact, db)
```

**`fact_id` determinístico por sesión y fecha:** evita que dos ciclos del job en
el mismo día (ej. reinicio del servidor) envíen la misma iniciativa dos veces.
La ventana de deduplicación del dispatcher (`dedup_window_hours: 24`) hace el
resto.

**`urgency="low"`:** siguiendo la taxonomía de `notifications-architecture.md §3`,
las iniciativas propias NO despiertan al usuario con push si la app está cerrada.
Se marcan como `delivery_status="pending"` y se entregan en el próximo SSE.

---

## 8. Detección de open_loops por turno (`open_loop_hook.py`)

### 8.1 Diseño

Al finalizar cada turno de conversación, DESPUÉS de `save_message` y ANTES de
retornar, el hook lanza una llamada barata a Haiku para clasificar el mensaje
del USUARIO (no la respuesta de Sity): ¿contiene una intención o tarea futura
que él mismo podría querer que se le recuerde? **Se ejecuta en todos los
turnos de User y Admin, sin atajo de longitud mínima** — prioridad en
fiabilidad sobre ahorro marginal de tokens.

**No añade latencia perceptible:** el hook se lanza como una tarea asyncio
fire-and-forget (`asyncio.create_task`). El turno de chat devuelve la respuesta
al usuario inmediatamente; la detección ocurre en paralelo. Si la tarea falla,
registra WARN y descarta — nunca interrumpe el turno.

**Punto de llamada:** `ai_orchestrator.py`, tras la línea de `save_message`
del mensaje del usuario. Solo para `session_id.startswith("user:")` —
Guest nunca acumula open_loops.

```python
# En ai_orchestrator.py, tras save_message del mensaje del usuario:
if ctx.session_id.startswith("user:"):
    from app.initiative.open_loop_hook import schedule_open_loop_detection
    schedule_open_loop_detection(session_id=ctx.session_id, user_message=user_message)
```

`schedule_open_loop_detection` crea el `asyncio.create_task` internamente
y retorna inmediatamente. La tarea llama a Haiku, parsea el resultado y
escribe en DB si procede.

### 8.2 Prompt de detección (en `open_loop_hook.py`)

Llamada a Haiku con propósito único y output estructurado:

```
Clasifica el siguiente mensaje de usuario.

¿Contiene una intención o tarea futura concreta que el propio usuario
podría querer que le recuerden más adelante? Cuenta como intención real:
compromisos propios ("voy a buscar trabajo", "tengo que llamar al médico"),
tareas pospuestas ("lo miro esta semana", "lo dejo para el finde"),
decisiones pendientes ("voy a pensar en eso").

NO cuenta como intención: intenciones inmediatas que no requieren seguimiento
("voy a leer esto ahora"), preguntas al asistente, planes hipotéticos
sin compromiso real ("podría hacer X"), planes de terceros.

Mensaje: "{user_message}"

Responde ÚNICAMENTE en JSON:
{"has_intent": true | false, "intent": "frase corta que resume la intención" | null}
```

**Parse y fallback:** `json.loads(resp.text)`. Si el JSON es inválido o
`has_intent` no está presente → asumir `has_intent=False`, registrar WARN.
Nunca propagar la excepción.

Si `has_intent=True`, se crea un registro `OpenLoop` con:
- `user_message`: texto completo del mensaje del usuario.
- `extracted_intent`: valor de `intent` devuelto por Haiku.
- `detected_at`: ahora.
- `expires_at`: `detected_at + open_loop_ttl_days`.
- `status`: `"pending"`.

**Deduplicación simple:** si ya existe un `OpenLoop` con `status="pending"` para
esta sesión creado en las últimas 24h, no se crea otro.

**Logging:**
```python
write_log(level="INFO", module="initiative", event="open_loop_detected",
    session_id=session_id, payload={"intent_preview": extracted_intent[:80]})

write_log(level="INFO", module="initiative", event="open_loop_detection_skip",
    session_id=session_id, payload={"reason": "has_intent_false"})

write_log(level="WARN", module="initiative", event="open_loop_detection_error",
    session_id=session_id, payload={"error": str(exc)})
```

---

## 9. Configuración en `default_config.yaml`

Sección nueva `initiative:`:

```yaml
initiative:
  job_interval_hours: 6                  # frecuencia del runner
  conversation_abandoned_min_hours: 24   # trigger activo desde esta antigüedad
  conversation_abandoned_max_days: 4     # trigger inactivo después de esta ventana
  long_inactivity_min_days: 5            # trigger activo después de N días sin mensajes
  open_loop_min_days: 3                  # evaluable solo si el open_loop lleva más de N días
  open_loop_ttl_days: 30                 # open_loops expirados tras N días sin resolución
  eval_log_ttl_days: 60                  # retención de InitiativeEvalLog
```

Los umbrales ya existentes en `§notifications` que este sistema consume:
- `initiative_silence_hours: 4` → IS_NOW_A_GOOD_TIME? check 1
- `initiative_min_trust: 0.30` → IS_NOW_A_GOOD_TIME? check 2
- `initiative_cooldown_hours: 24` → consultado vía NotificationLog
- `max_proactive_per_day_user: 1` → rate limit en dispatcher

---

## 10. Frontend — pantalla de Ajustes

Sección "Iniciativa" visible solo para `User` y `Admin` (nunca para `Guest`).
Mismo patrón que la sección de voz/idioma en `VoiceScreen.tsx`.

```
[ Toggle maestro ]  Permitir que Sity te escriba primero
                    (cuando está apagado, los sub-toggles quedan ocultos)

  Si está activo:

  [ Toggle ]  Conversaciones abandonadas
              "Sity puede recordarte una conversación que quedó a medias."

  [ Toggle ]  Reconexión tras inactividad
              "Si lleváis días sin hablar, Sity puede dar el primer paso."

  [ Toggle ]  Seguimiento de temas pendientes
              "Sity puede preguntarte por cosas que mencionaste y no retomaste."
```

**Comportamiento al guardar:** cada toggle se guarda inmediatamente como
`Setting` con `session_id` (per-session, mismo `autoSave` pattern que voz).

**Endpoints (añadir a `routes_settings.py`):**
- `GET /settings/initiative` → `InitiativeSettings`
- `PUT /settings/initiative` → `InitiativeSettings`

---

## 11. Estructura de módulos

```
backend/app/initiative/
    __init__.py            # vacío
    models.py              # OpenLoop, InitiativeEvalLog (añadir a memory/models.py)
    settings.py            # InitiativeSettings schema + get/set service
    detector.py            # TriggerCandidate, get_trigger_candidates(session_id, db)
    evaluator.py           # EvalResult, evaluate(candidate, db) → EvalResult
    runner.py              # asyncio loop cada 6h — iniciado en main.py on_startup
    open_loop_hook.py      # schedule_open_loop_detection() — fire-and-forget asyncio task
                           # llama a Haiku por turno para clasificar intenciones futuras
```

Los modelos `OpenLoop` e `InitiativeEvalLog` pueden ir en `memory/models.py`
(siguiendo el patrón existente de tablas SQLModel centralizadas) o en
`initiative/models.py` con su propio `SQLModel.metadata`. Si van en `memory/models.py`,
no hay cambio en el sistema de migraciones — las tablas se crean en el `create_all`
del startup.

**Separación de responsabilidades:**
- `detector.py` solo lee DB — nunca escribe, nunca llama a LLM.
- `evaluator.py` solo llama a Haiku — recibe un candidato ya validado, devuelve un resultado.
- `runner.py` orquesta — llama a detector, aplica IS_NOW_A_GOOD_TIME?, llama a evaluator,
  persiste InitiativeEvalLog, llama a dispatcher. Es el único módulo que escribe en DB
  (aparte del hook).
- `open_loop_hook.py` llama a Haiku y escribe `OpenLoop` — sin leer nada del resto
  del sistema. Fire-and-forget: el turno de chat no espera su resultado.
- `dispatcher.py` no cambia — recibe el NotificationFact y lo procesa como siempre.

---

## 12. Logging completo

Todos los eventos importantes loguean con `module="initiative"`.

| Event | Level | Cuándo |
|---|---|---|
| `runner_cycle_start` | INFO | Al inicio de cada ciclo de 6h |
| `runner_cycle_done` | INFO | Al final del ciclo — elapsed, stats |
| `session_skipped_silence` | INFO | Usuario habló hace < silence_hours |
| `session_skipped_trust` | INFO | Trust < initiative_min_trust |
| `session_skipped_rate_limit` | INFO | Ya hubo proactive_initiative hoy |
| `session_skipped_toggle_off` | INFO | Toggle maestro desactivado |
| `session_skipped_no_trigger` | INFO | Ninguna condición activa |
| `evaluation_start` | INFO | Antes de llamar a Haiku (con trigger_type) |
| `evaluation_haiku_error` | WARN | Haiku falla o devuelve JSON malformado |
| `evaluation_complete` | INFO | decision, trigger_type, reasoning preview |
| `open_loop_dispatched` | INFO | OpenLoop marcado como dispatched |
| `open_loop_resolved` | INFO | OpenLoop marcado como resolved (Haiku lo detectó) |
| `open_loop_detected` | INFO | Hook detectó intención en turno de usuario |
| `open_loop_gc` | INFO | Ciclo de expiración — N open_loops marcados expired |
| `eval_log_gc` | INFO | Ciclo de limpieza de InitiativeEvalLog — N filas borradas |

---

## 13. Registro de causa — auditoría

Cada iniciativa enviada tiene su causa documentada en dos lugares:

1. **`InitiativeEvalLog`** — el registro completo de la evaluación (trigger,
   contexto, veredicto de Haiku, extracto del mensaje, fecha). Para debug interno.

2. **`NotificationLog.payload_json`** — el payload del dispatcher incluye
   `"trigger_type"` (y opcionalmente `"open_loop_id"` si aplica). No se muestra
   al usuario, pero permite correlacionar una notificación entregada con su causa
   original cruzando `NotificationLog.fact_id` con `InitiativeEvalLog`.

Para auditar por qué Sity escribió en un momento dado:
```
SELECT * FROM initiativeevallog
WHERE session_id = 'user:1'
ORDER BY evaluated_at DESC
LIMIT 10;
```

---

## 14. Tests — contratos a verificar

1. `schedule_open_loop_detection` crea un `OpenLoop` cuando Haiku devuelve
   `{"has_intent": true, "intent": "..."}` (testeado con mock del proveedor que
   retorna ese JSON). Cuando Haiku devuelve `has_intent=false`, no se crea ningún
   registro. Si el JSON es inválido, registra WARN y no crea registro (no propaga
   excepción). No crea duplicado si ya existe un `OpenLoop` con `status="pending"`
   para la misma sesión en las últimas 24h.

2. `get_trigger_candidates` devuelve `conversation_abandoned` solo si la última
   fila de la sesión tiene `role='sity'` y antigüedad en la ventana correcta.

3. `get_trigger_candidates` devuelve `long_inactivity` solo si el último mensaje
   (cualquier rol) tiene más de `long_inactivity_min_days` días.

4. `get_trigger_candidates` devuelve `open_loop` solo si hay un `OpenLoop` con
   `status="pending"` y `detected_at < now - open_loop_min_days`.

5. El runner saltea sesiones de Guest (`session_id.startswith("guest:")`).

6. El runner saltea sesiones con `initiative.enabled = False`.

7. El runner saltea sesiones donde el sub-toggle del trigger detectado está desactivado.

8. El runner no llama a Haiku si IS_NOW_A_GOOD_TIME? falla (verificar que
   `evaluator.evaluate` no se invoca en esos casos).

9. Si Haiku devuelve JSON malformado, el runner registra WARN y el result es skip.

10. Si Haiku devuelve `decision="send"`, se construye un `NotificationFact` con
    `notification_type="proactive_initiative"` y se llama `dispatcher.dispatch()`.

11. Un segundo ciclo del runner en el mismo día NO reenvía la misma iniciativa
    (deduplicación por `fact_id` en dispatcher).

12. Un `OpenLoop` con `status="dispatched"` no aparece en candidatos del detector.

13. `InitiativeEvalLog` registra una fila tanto para `decision="send"` como para
    `decision="skip"`.

14. `initiative_min_trust = 0.30`: sesión con `trust = 0.29` → skip. Con
    `trust = 0.30` → continúa.

---

## 15. Notas de implementación

- El runner se registra en `main.py on_startup` exactamente como
  `timers/runner.py:start_runner(loop)` — la firma es `async def initiative_runner_loop() -> None`.
- `evaluator.py` usa el mismo `CortexGateway` / proveedor Claude que el resto del sistema.
  El modelo es `claude-haiku-4-5-20251001` (barato, suficiente para este juicio). Si el
  proveedor falla, result es skip con `skip_reason="evaluator_error"` — nunca propaga la excepción.
- El runner maneja cada sesión en un `try/except` independiente: si una sesión falla
  (DB error, etc.), registra ERROR y continúa con la siguiente — el job no se rompe por completo.
- `open_loop_hook.py` es ignorable en Guest: el hook debe verificar
  `session_id.startswith("user:")` antes de crear `OpenLoop` — Guest nunca acumula open_loops.

---

## 16. Bugs encontrados y resueltos en verificación real (2026-08-19 → 2026-08-24)

Esta sección documenta los bugs descubiertos durante la primera verificación en producción
real. Si en el futuro aparece comportamiento extraño en el sistema de iniciativa, este
historial explica exactamente qué se probó y qué se aprendió.

### Bug 1 — JSON con markdown fences en evaluator.py (`c0cc4b3`, 2026-08-19)

**Síntoma:** `json_parse_error` en todos los ciclos del evaluador. El runner llamaba a Haiku
pero nunca llegaba a una decisión válida — siempre devolvía skip por error de parse.

**Causa:** Haiku (y potencialmente otros modelos) envuelve las respuestas JSON en bloques
de markdown (` ```json\n{...}\n``` `). `json.loads(response.text.strip())` no puede parsear
eso — falla en la primera línea del fence.

**Fix:** `_strip_json_fences()` en `evaluator.py` para eliminar los fences antes de parsear.

### Bug 2 — JSON con markdown fences en open_loop_hook.py (CRÍTICO, `1e0f91b`, 2026-08-19)

**Síntoma:** NINGÚN OpenLoop se creaba en producción pese a que los usuarios enviaban mensajes
con intenciones futuras claras. El hook siempre retornaba `has_intent=False` silenciosamente.

**Causa:** mismo fence bug que el Bug 1, pero en `open_loop_hook._call_haiku()`. La función
parseaba `json.loads(response.text.strip())` sin strip de fences → excepción silenciada →
fallback a `{"has_intent": False}`. Resultado: el canal de open_loop estaba completamente
bloqueado en producción desde el primer día, sin ninguna evidencia externa visible.

**Fix:** `_json_utils.py` como módulo compartido con `strip_json_fences()`. Ambos módulos
importan desde ahí — no se duplica la función. Misma función, un solo lugar.

**Lección:** el patrón de "swallow exception + return safe default" en fire-and-forget tasks
es correcto para robustez, pero oculta completamente los fallos a nivel de sistema. Sin logs
activos monitorizados, un canal entero puede estar muerto indefinidamente. El log de WARN
`open_loop_detection_parse_error` ya existía pero no se estaba observando.

### Bug 3 — Dead zone por contexto auto-referencial en open_loop (`0680b8c`, 2026-08-24)

**Síntoma:** Una vez que el sistema de iniciativa funcionó (Bug 1 y 2 corregidos), el trigger
`open_loop` evaluaba correctamente pero Haiku decía "skip" en TODOS los ciclos indefinidamente
para el mismo loop. Después de 715 evaluaciones (4+ días con el loop `ol_aee77ee2` de la
guitarra), ninguna decisión de "send".

**Causa:** `recent_messages_after_detection` incluía TODOS los mensajes posteriores a la
detección del loop — incluyendo los propios mensajes de Sity (iniciativas anteriores sobre
el mismo tema). Haiku veía "Sity ya preguntó sobre esto" → interpretaba "tema ya abordado"
→ skip sin `open_loop_resolved=True`. El loop quedaba `pending` permanentemente, ni se enviaba
ni se cerraba: dead zone.

**Fix estructural:** filtrar `recent_messages_after_detection` a solo `role == "user"` en
`detector._check_open_loop()`. Haiku solo ve si el USUARIO mencionó/resolvió la intención —
los mensajes de Sity sobre el loop son ruido que contamina la decisión.

**Fix de seguridad adicional:** `open_loop_max_eval_attempts: 20` en config. Tras N evaluaciones
acumuladas (todas con cualquier resultado), el detector marca el loop `expired` automáticamente.
Esto corta el gasto de Haiku en loops que por cualquier razón no progresen — incluso ante bugs
futuros no previstos. El loop `ol_aee77ee2` (715 evals) se auto-expiró en el primer ciclo
post-deploy.

**Lección:** el contexto pasado a un LLM para una decisión debe contener ÚNICAMENTE la
información relevante para esa decisión específica. Los mensajes de Sity sobre el mismo tema
son información sobre lo que Sity ya hizo, no sobre el estado de la intención del usuario —
mezclarlo introduce sesgo sistemático.

### Estado del sistema tras la verificación

El pipeline completo fue verificado de principio a fin en producción:
- `open_loop_detected` → OpenLoop creado en DB ✓
- Runner detecta el loop tras `open_loop_min_days` ✓
- Haiku evalúa con contexto limpio (solo mensajes del usuario) ✓
- Haiku envía o declina con razonamiento verificable en EvalLog ✓
- Si loop lleva > 20 evaluaciones sin progreso → auto-expirado, gasto cortado ✓
- Config TEMPORAL revertida a producción (2026-08-24) ✓

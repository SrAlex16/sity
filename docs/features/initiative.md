# Proactive Initiative / Iniciativa Propia

[English](#english) · [Español](#español)

---

## English

Sity can initiate contact without being prompted. This is distinct from notification delivery — it involves Sity actively deciding whether it has something worth saying, not just relaying system events.

### Eligibility

Only `User` and `Admin` sessions are eligible. Guest sessions are excluded entirely. A per-session toggle allows users to disable initiative.

### Three trigger types

| Trigger | Condition |
|---|---|
| `conversation_abandoned` | User stopped mid-task (open loop detected) |
| `long_inactivity` | Extended silence window |
| `open_loop` | User mentioned an intention, never followed up |

### Decision flow

```
Event detected (conversation_abandoned / long_inactivity / open_loop)
        ↓
Deterministic gate (runs first, always):
  ✓ 4-hour silence window elapsed
  ✓ Trust (familiarity dimension) ≥ 0.30
  ✓ Rate limits not exceeded (per user)
  ✓ Per-session toggle is on
        ↓ (if all pass)
Haiku judgment:
  - Is there a genuine reason to write?
  - Receives: recent user messages (not Sity's), open loops, active goals, social context
  - Output: should_contact (bool) + suggested_message + next_check_time
        ↓ (if approved)
Deliver via notification dispatcher (low-urgency, no Web Push wake)
```

### Adaptive runner (since 2026-09-28)

The runner no longer fires on a fixed 6-hour interval. Haiku decides when to check next. Urgent goals (base importance ≥ 0.75) can wake the runner early.

**Soft rule**: Avoid contact during late-night hours unless a wellbeing goal is very urgent.

### Open-loop detection

Open loops are extracted from user messages per turn as a fire-and-forget task (no chat latency). Detection scans for stated intentions that haven't been followed up on.

- Only user messages are passed to Haiku (not Sity's) — avoids self-referential bias
- Cap: 20 evaluation attempts per loop before marking as exhausted

### Goal-triggered initiative

Long-term goals with base importance ≥ 0.75 generate an initiative candidate without forcing a notification. The candidate still passes through the normal quiet-time gate.

The "only when inactive" restriction on goal triggers is noted as the most uncertain design decision and is open to revision after real-world testing.

### Delivery

Initiative messages are delivered through the existing notification dispatcher as `low_urgency` priority. They do not trigger Web Push (which would wake the user on their device) unless the context warrants high urgency.

### Production bugs found and fixed

1. **Markdown-fenced JSON from Haiku** caused parse failures in both the evaluator and the open-loop hook. The open-loop channel was silently dead until this was fixed.

2. **Self-referential context**: Sity's own earlier messages on a topic biased Haiku toward "skip" indefinitely. Fixed by passing only user messages and capping attempts at 20.

3. **Missing TTS on initiative messages**: The runner bypassed the normal chat synthesis path. Audio also disappeared on page reload — fixed in the frontend.

128 tests cover the four implementation steps.

---

## Español

Sity puede iniciar contacto sin ser invocada. Esto es distinto de la entrega de notificaciones — implica que Sity decide activamente si tiene algo que valga la pena decir.

### Elegibilidad

Solo sesiones `User` y `Admin`. Los guest están excluidos completamente. Toggle por sesión para deshabilitar.

### Tres tipos de trigger

Ver tabla en la sección en inglés.

### Flujo de decisión

Primero pasa un gate determinista (ventana de 4h de silencio, confianza ≥ 0.30, límites de frecuencia, toggle). Solo si el gate pasa, Haiku juzga si hay razón genuina. Solo se pasan mensajes del usuario a Haiku, no los de Sity (evita sesgo auto-referencial).

### Runner adaptativo (desde 2026-09-28)

El runner ya no dispara con un intervalo fijo de 6 horas. Haiku decide cuándo hacer el siguiente check. Los goals urgentes (importancia base ≥ 0.75) pueden despertar el runner anticipadamente.

**Regla suave**: Evitar contacto en horas nocturnas salvo goals de bienestar muy urgentes.

### Detección de open loops

Se extrae por turno como tarea fire-and-forget (sin latencia en el chat). Cap: 20 intentos de evaluación por loop antes de marcarlo como exhausto.

### Bugs encontrados en producción (resueltos)

1. JSON con markdown fence desde Haiku → fallos de parsing (canal open-loop silenciosamente muerto)
2. Contexto auto-referencial → Haiku sesgado hacia "skip" indefinidamente (fix: solo mensajes del usuario)
3. TTS faltaba en mensajes de iniciativa + desaparecía al recargar la página (fix en frontend)

# Fase 5 — Decision (Action Policy) + Expression

**Estado:** Partes 1–2 completas (2026-09-10)  
**Tests nuevos:** 52 (test_decision_service.py)  

---

## Objetivos

Dotar a Sity de una política de acción explícita por turno: en lugar de que el
modelo principal decida libremente qué tipo de respuesta dar, el módulo Decision
pre-selecciona una de 10 acciones posibles usando una fórmula determinista
calibrada + un Haiku de validación. La acción elegida se inyecta como instrucción
en `persona_prompt` antes de la llamada al modelo principal.

---

## Diseño central: fórmula de utilidad + 4 Haiku calls por turno

### Las 10 acciones

| Acción | Descripción | Baseline |
|--------|-------------|---------|
| `answer` | Respuesta conversacional estándar | 0.50 |
| `help` | Asistencia activa — mejor con intent_request | 0.30 |
| `ask` | Pregunta clarificatoria — mejor con novelty alta | 0.20 |
| `challenge` | Cuestionar premisa — requiere challenge_signal | 0.10 |
| `refuse` | Rechazo — muy raro, requiere múltiples señales | 0.02 |
| `set_boundary` | Límite personal — más suave que refuse | 0.05 |
| `use_tool` | Invocar herramienta — requiere domain_activated | 0.20 |
| `wait` | No responder — se convierte en answer (ver abajo) | 0.01 |
| `initiate` | Añadir algo proactivo más allá de la pregunta | 0.10 |
| `change_topic` | Redirigir — requiere boredom alta | 0.05 |

### Fórmula de utilidad

```
U(action) = baseline(action) + Σ w_i(action) × signal_i   [clamped 0-1]
```

22 señales de entrada × 10 acciones = matrix de pesos calibrada. Las señales
se dividen en 5 categorías:

1. **Personalidad** (helpfulness, assertiveness, independence, curiosity,
   proactivity, honesty, skepticism, patience, warmth, directness)
2. **Estado emocional** post-appraisal (frustration, interest, defensiveness,
   boredom, social_comfort, melancholy)
3. **Relación** (affinity, conflict, trust_avg)
4. **Percepción** (challenge_signal, novelty)
5. **Goals** (max_goal_priority)

Más dos bonos contextuales binarios:
- `intent_request=True` → `help += 0.30`, `answer -= 0.15`
- `domain_activated=True` → `use_tool += 0.40` ; `False` → `use_tool -= 0.30`

### Calibraciones clave (post-escenarios)

| Señal | Cambio | Motivo |
|-------|--------|--------|
| `challenge_signal → challenge` | 0.25 → **0.45** | La percepción debe dominar sobre la personalidad |
| `skepticism → challenge` | 0.30 → **0.15** | Personalidad es inclinación, no determinación |
| `curiosity → initiate` | 0.25 → **0.20** | Evita que `initiate` supere a `answer` en saludos |
| `proactivity → initiate` | 0.35 → **0.30** | ídem |
| `DOMAIN_ACTIVATED_BONUS_TOOL` | +0.25 → **+0.40** | `use_tool` debe ganar con claridad cuando hay domain |
| `INTENT_REQUEST_BONUS_HELP` | +0.20 → **+0.30** | `help` debe superar a `answer` con intent_request |
| `boredom → answer` | -0.20 → **-0.25** | Boredom debe poder desplazar `answer` con proactivity |

### Pipeline de Decision (Haiku #3 + #4)

```
compute_utility_scores()       # Python puro, sin I/O
  ↓
_build_decision_context()      # Texto para Haiku
  ↓
Haiku #3 (max_tokens=120)      # Selecciona o anula la acción Python
  ↓ action, reasoning
defensive validation           # action ∈ _VALID_ACTIONS
  ↓
_check_coherence()             
  ├─ Python floor: score < 0.30 → fallback inmediato
  └─ Haiku #4 (max_tokens=40)  # Confirma coherencia
  ↓
DecisionResult(action, python_scores, reasoning)
```

### Fallback: None → sistema anterior

Cualquier falla devuelve `None` desde `run_decision()`. Turn_cognition registra
`event="decision_fallback_triggered"` con `reason` y continúa con el sistema
anterior (toolset_selector + persona_engine.refusal_mode).

Dos `reason` posibles:
- `"technical_error"` — excepción, parse failure, o acción inválida
- `"coherence_check_failed"` — Haiku #4 rechaza o Python score < 0.30

---

## Expression (Parte 2)

La acción seleccionada se inyecta en `persona_prompt` como un bloque de
instrucción antes de la llamada al modelo principal.

```python
# turn_runner.py — después de goals_block
if _cognition_result.decision is not None:
    _dec_action = _cognition_result.decision.action
    if _dec_action == "wait":
        write_log(..., event="decision_wait_fallback")
        # cae a answer — no se puede "esperar" en respuesta síncrona
    else:
        _action_instr = build_action_instruction(_dec_action)
        if _action_instr:
            persona_prompt += f"\n\n{_action_instr}"
```

Instrucciones inyectadas (español, formateadas con prefijo `ACCIÓN DECIDIDA:`):

| Acción | Instrucción |
|--------|-------------|
| `answer` | *(vacío — comportamiento por defecto)* |
| `help` | Ayuda activamente. Sé práctico y directo. |
| `ask` | Haz UNA sola pregunta antes de responder. |
| `challenge` | Cuestiona o matiza la premisa. Directo, con respeto. |
| `refuse` | Rechaza esta petición de manera firme. |
| `set_boundary` | Comunica un límite personal calmadamente. |
| `use_tool` | Usa las herramientas disponibles. |
| `wait` | *(vacío — fallback a answer)* |
| `initiate` | Ve más allá. Añade observación o idea proactiva. |
| `change_topic` | Redirige hacia algo más relevante. |

**Nota sobre `refuse`:** La acción Decision `refuse` es una capa adicional
(contextual, por turno) sobre el `refusal_mode` estructural de PersonaEngine.
Se implementa via instrucción al modelo principal, sin duplicar el pipeline de
`generate_refusal_response()` que gestiona el estado y TTS del rechazo
estructural.

---

## Archivos modificados / creados

| Archivo | Cambio |
|---------|--------|
| `backend/app/cognition/decision.py` | **NUEVO** — módulo completo |
| `backend/app/cognition/turn_cognition.py` | Paso 11 (Decision) + CognitionTurnResult.decision |
| `backend/app/chat/turn_runner.py` | Expression injection después de goals_block |
| `tests/test_decision_service.py` | **NUEVO** — 52 tests |

---

## Tests (52)

- `TestComputeUtilityScores` (14): fórmula Python pura, 12 propiedades + all-actions + clamping
- `TestRunDecisionSuccess` (3): ambas Haiku calls OK → DecisionResult correcto
- `TestRunDecisionFallback` (6): todos los paths de fallback (parse, inválido, excepción, coherencia, score bajo)
- `TestParsingHelpers` (8): `_parse_decision_response` + `_parse_coherence_response`
- `TestCognitionTurnResultDecision` (3): campo `.decision` en dataclass
- `TestFallbackLogging` (3): payload de logs completo en ambas rutas
- `TestBuildActionInstruction` (13): `build_action_instruction` — vacío para answer/wait, contenido para el resto

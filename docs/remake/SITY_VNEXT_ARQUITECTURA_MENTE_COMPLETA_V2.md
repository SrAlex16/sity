# Sity --- Mini-Operación Remake v2.0: Cerrar los bucles cognitivos

**Estado:** propuesta de implementación\
**Prerequisito:** Operación Remake v1.0 completada (SITY_VNEXT_ARQUITECTURA_MENTE_COMPLETA.md)\
**Objetivo:** las piezas cognitivas existen. El trabajo ahora no es añadir módulos nuevos, sino cerrar los circuitos entre los que ya existen. Varias estructuras aprenden o almacenan información pero todavía no influyen suficientemente en la experiencia futura de Sity.

Como describió la revisión externa del repo tras la v1.0:

> *"El principal trabajo que veo ahora ya no es añadir las piezas que faltan, sino cerrar los circuitos entre las piezas que ya existen."*

------------------------------------------------------------------------

## Diagnóstico de bucles abiertos

Tras la Operación Remake v1.0, el pipeline cognitivo completo existe y funciona:

```text
PERCEPTION → APPRAISAL → MENTAL STATE / RELATIONSHIP / GOALS
→ SALIENCE → EPISODE → DECISION → REFLECTION → EXPRESSION
```

Sin embargo, un análisis del código en producción revela cuatro categorías de bucles abiertos:

**Categoría A — Estructuras write-heavy, poco read-heavy**
- `Episode`: se crea con salience, strength, recall_count. Nunca se recupera para inyectar en el prompt.
- `Reflection.memory_candidates`, `relationship_evidence`, `goal_updates`, `self_model_updates`: se generan y se guardan en `ReflectionLog`. Ningún código los lee después.

**Categoría B — Segundo decisor paralelo**
- `refusal_propensity` + `_should_refuse()` coexisten con `Decision` que ya tiene `refuse` y `set_boundary`. En producción, `decision_fallback_triggered` nunca se ha activado — el sistema antiguo existe por inercia histórica, no por necesidad real.

**Categoría C — Outputs sin downstream causal**
- `Expectation`: se crea cuando el usuario menciona algo futuro. Cuando ese momento llega (o no llega), no pasa nada. No hay aprendizaje.
- `SelfModel` y `SelfBelief`: almacenan creencias de Sity sobre sí misma pero no influyen en `Decision`.

**Categoría D — Estado congelado entre conversaciones**
- `MentalState`: si Sity tiene `frustration=0.84` y no hay conversación durante 48h, sigue siendo 0.84. No hay regulación temporal.
- `SemanticFact`: todos los hechos decaen igual, independientemente de si son volátiles ("está buscando coche") o estables ("es desarrollador de Python").

------------------------------------------------------------------------

## Regla de arquitectura emergente

Antes de describir cada pieza, una regla que aparece repetidamente en el diseño de esta v2.0:

> **El LLM interpreta; la arquitectura decide cuánto poder conceder a esa interpretación.**

Esta regla se aplica en todos los puntos: Haiku evalúa semánticamente qué significa una creencia, una evidencia o un candidato. El código determinista acota cuánto puede afectar al estado final. Esto evita dos problemas opuestos: que el LLM ignore información relevante (si no le llega) y que la domine en exceso (si no hay límites matemáticos).

Una segunda regla, derivada del análisis de Reflection:

> **Reflection no modifica el mundo cognitivo directamente. Produce hipótesis y evidencias. Cada dominio decide qué hacer con ellas.**

Y la distinción de autoridad que separa los dos módulos de observación:

> **Appraisal**: ¿qué significa este evento AHORA? → actualiza estado inmediato.\
> **Reflection**: ¿qué podría aprender de lo que acaba de ocurrir? → genera evidencia/hipótesis para aprendizaje persistente.

No es una diferencia de peso o confianza. Es una diferencia de autoridad.

------------------------------------------------------------------------

## PARTE XXII --- Retrieval episódico real

### Problema

`Episode` es la memoria de experiencias concretas de Sity. Tiene `salience`, `strength`, `recall_count`, `last_recalled_at`. Se crea correctamente tras cada turno significativo (salience ≥ 0.25). Pero nunca se recupera para influir en conversaciones posteriores.

La documentación del propio proyecto lo reconocía explícitamente: *"pendiente la inyección de memoria episódica relevante en el prompt."*

El efecto es que Sity tiene memoria episódica pero no la consulta activamente. La "experiencia vivida" queda cognitivamente dormida.

### Diseño

El retrieval episódico no debe basarse únicamente en similitud semántica. La recuperación humana de recuerdos depende de múltiples factores simultáneos:

```text
RecallScore = Similarity × Salience × Strength × RecencyBoost × ContextRelevance
```

Donde:
- **Similarity**: qué tan relacionado está el episodio con el turno actual (calculado en Appraisal)
- **Salience**: importancia original del episodio (ya almacenada)
- **Strength**: solidez acumulada por refuerzos (ya almacenada)
- **RecencyBoost**: penalización suave por antigüedad — episodios recientes tienen ventaja, pero uno de hace 2 años con salience=0.94 puede superar a uno de ayer con salience=0.12
- **ContextRelevance**: afinidad entre el context_type del episodio y el del turno actual

Este diseño produce el efecto deseado:
```text
"esto me recuerda a aquella vez..."
```

sin necesidad de destruir ni modificar los episodios — el "olvido" emerge naturalmente del score, no de borrar filas.

### Dónde se inyecta

Los episodios recuperados (top-3 por RecallScore) entran en `CognitiveContext` y se inyectan en el prompt de Decision y Expression. Appraisal también puede usarlos para calibrar la respuesta emocional al turno actual.

### Observación sobre decay episódico

No se implementa decay físico de episodios. Un episodio de hace 2 años permanece intacto en DB. Solo se vuelve menos recuperable si su RecallScore queda consistentemente por debajo de los más recientes en situaciones similares. Esto es más fiel a la memoria humana: los recuerdos no se borran gradualmente — se vuelven menos accesibles.

------------------------------------------------------------------------

## PARTE XXIII --- Eliminación del segundo decisor de negación

### Problema

Durante la migración de la Operación Remake v1.0, `refusal_propensity` y `_should_refuse()` se mantuvieron como fallback de Decision. La razón fue pragmática: el sistema antiguo ya existía.

Tras analizar los logs de producción, `decision_fallback_triggered` nunca se ha activado. Decision no ha fallado técnicamente en ningún turno registrado.

Mantener dos mecanismos decidiendo la misma conducta tiene consecuencias reales:
- Inconsistencia: Decision puede elegir `answer` mientras `_should_refuse()` elegiría negar.
- Opacidad: no es posible saber cuál de los dos tomó la decisión final.
- Contradicción con el diseño: Decision tiene `refuse` y `set_boundary` como acciones propias.

### Decisión

`Decision` es la única autoridad semántica para decidir negación.

Si Decision falla técnicamente (error de API, JSON malformado), el comportamiento correcto es el mismo que si falla cualquier otro paso Haiku: el turno falla limpiamente y el usuario puede reenviar el mensaje. No hay motivo para que Decision tenga un sistema redundante que Perception, Appraisal y Expression no tienen.

### Implementación

- Eliminar `_should_refuse()` y `refusal_propensity` del código de producción.
- El evento `decision_fallback_triggered` puede mantenerse como log de error técnico, pero ya no activa ningún sistema alternativo.
- El fallback técnico de Decision es fallo limpio del turno, no otro decisor.

------------------------------------------------------------------------

## PARTE XXIV --- Initiative como wake-up mechanism

### Problema

La `Action Policy` de Decision ya incluye `initiate` como una de sus 10 acciones posibles. Sin embargo, el sistema de iniciativa mantiene su propio evaluador con lógica psicológica independiente — decide si contactar, cuándo y con qué intención.

Esto reproduce el mismo problema que `_should_refuse()`: dos decisores paralelos para la misma conducta.

### Diseño

```text
OpenLoop / inactivity / goal urgente / señal del pipeline
                  ↓
              WAKE SITY
                  ↓
         construir CognitiveContext completo
                  ↓
              Decision
                  ↓
       initiate / wait / other
```

El runner detecta "hay motivo suficiente para despertar el proceso cognitivo." Decision decide qué hacer con ese motivo.

**Ventaja real**: el mensaje de iniciativa usará el mismo pipeline completo que cualquier respuesta normal — con toda la personalidad, estado emocional, historial de la relación y contexto. Hoy el evaluador genera algo más genérico porque tiene acceso a menos información.

### El runner adaptativo

El runner periódico ya fue rediseñado en la sesión anterior como sistema adaptativo con `threading.Event`. El cambio de esta v2.0 es más conceptual: el evaluador deja de tener lógica psicológica propia. Cuando decide despertar, construye el `CognitiveContext` completo y lo pasa a Decision.

------------------------------------------------------------------------

## PARTE XXV --- Temporal dynamics

### Problema

El estado cognitivo de Sity queda congelado entre conversaciones. `MentalState` con `frustration=0.84` permanece igual durante semanas de inactividad. Esto no es regulación emocional — es un estado persistente sin dinámica temporal.

Importante: esto **no es olvido**. Es regulación emocional y decay conservador de hechos semánticos. Los episodios no se borran. La relación no decae.

### MentalState: decay lazy hacia baseline

La fórmula de retorno al baseline:

```
x(t) = b + (x₀ - b) × e^{-λt}
```

Donde `b` es el baseline de cada variable, `x₀` es el valor actual, y `λ` es la tasa de decay (distinta por variable).

Baselines confirmados:
```python
BASELINES = {
    "valence": 0.0,
    "arousal": 0.0,
    "frustration": 0.0,
    "melancholy": 0.10,
    "current_curiosity": 0.50,
    "interest": 0.50,
    "boredom": 0.0,
    "defensiveness": 0.0,
    "social_comfort": 0.50,
}
```

**Implementación lazy**: no se usa un cron job. El decay se aplica al cargar `MentalState` antes de cada turno:

```text
última actualización: lunes 14:32
           │
           │ 52 horas
           ▼
usuario escribe miércoles 18:32
           │
           ▼
apply_temporal_decay(state, elapsed=52h)
           │
           ▼
Perception / Appraisal
```

Determinista, barato, fácil de testear, sin procesos en background.

### SemanticFact: stability categories

No todos los hechos envejece igual:

```text
"está buscando coche"     → volatile
"trabaja con Python"      → normal
"se llama Alex"           → stable
```

Regla conservadora de decay: solo se aplica a facts con `confidence < 0.65` **y** `reinforcement_count < 3`. Un hecho muy consolidado no decae pasivamente.

Campos nuevos en `SemanticFact`:
- `stability`: `volatile | normal | stable`

### Qué no decae

- **Relationship / SocialProfile**: no. La ausencia no reduce confianza. La nueva evidencia (positiva o negativa) sí la modifica.
- **Episode**: no. Se vuelven menos recuperables por RecallScore, pero no se borran ni se debilitan físicamente.
- **Personality**: no. Es la disposición basal de Sity, configurable explícitamente por el usuario. No debe cambiar con el tiempo salvo intervención explícita.

------------------------------------------------------------------------

## PARTE XXVI --- Prediction error y cierre del bucle de Expectations

### Problema

`Expectation` es write-only. Se crea cuando el usuario menciona algo futuro. Cuando ese momento llega — o no llega — no pasa nada. No hay aprendizaje, no hay actualización de la relación, no hay calibración del modelo predictivo.

### Estados de una Expectation

Un error crítico de diseño sería asumir que "deadline pasó y el usuario no lo mencionó = incumplida". La realidad es más compleja:

```text
pending          → esperando evidencia
fulfilled        → confirmada con evidencia
violated         → contradicha con evidencia
expired_unknown  → deadline pasó, sin evidencia de ningún tipo
cancelled        → el usuario indicó que ya no aplica
```

`expired_unknown` es el estado más común y el más importante de no confundir con `violated`. Que el usuario no mencione algo **nunca es evidencia de incumplimiento**.

### Campos nuevos en Expectation

```text
probability     → ya existe
importance      → nuevo (ver abajo)
observability   → ¿puede Sity saber si ocurrió? direct / indirect / unobservable
due_at          → fecha esperada del evento
```

### Distinction: probability ≠ importance

Son dimensiones completamente independientes:

```text
"mañana seguramente lloverá"
probability = 0.90
importance  = 0.05

"mañana tengo la entrevista de trabajo más importante de mi año"
probability = 0.80
importance  = 0.95
```

El seguimiento de Sity es proporcional a `importance`, no a `probability`.

### Cálculo de importance

No es una fórmula fija. Es una función de varias señales:

```text
Importance = f(
    salience del turno donde se creó,
    goal_relevance,
    urgencia temporal,
    intensidad emocional,
    patrón procedimental del usuario
)
```

El patrón procedimental es especialmente relevante: Sity aprende si este usuario tiende a mencionar cosas de pasada (importancia inicial baja) o si suele desarrollar los temas que le preocupan (importancia inicial más alta).

### Prediction error y surprise

Dos conceptos distintos que deben almacenarse por separado:

```text
prediction_error = y - p
  donde y=1 si ocurre, 0 si no

surprise = -log₂(P(evento observado))
```

`prediction_error` se usa para calibración y aprendizaje.\
`surprise` determina cuánta atención/salience merece el evento.

Almacenados en `expectation_resolution`:
```text
expectation_id
outcome: fulfilled | violated | expired_unknown | cancelled
predicted_probability
prediction_error
surprise
```

### Downstream del prediction error

```text
RESOLUTION
    │
    ├→ Relationship (trust_reliability si fue observable y el usuario controló el resultado)
    ├→ Expectation model calibration (aprende a predecir mejor)
    ├→ Episode salience (eventos sorprendentes son más memorables)
    └→ ProceduralPattern (aprende cómo interpreta el usuario sus propios compromisos)
```

### Conexión con ProceduralPattern

ProceduralPattern no almacena "qué temas menciona frecuentemente el usuario". Eso es historia semántica. ProceduralPattern aprende **cómo interpretar los actos lingüísticos del usuario**:

```text
planning.explicit_commitments.reliability: 0.87
planning.tentative_statements.reliability: 0.39
```

Después de suficientes observaciones, cuando el usuario dice "mañana termino X" con lenguaje de compromiso explícito, Sity puede asignar `P=0.86`. Cuando dice "quizá algún día pruebo X", puede asignar `P=0.25` o no crear Expectation.

Esto es exactamente Theory of Mind aplicada: no entender una frase genéricamente, sino entender **esa frase de esa persona** basándose en su historia compartida.

------------------------------------------------------------------------

## PARTE XXVII --- Cerrar los outputs de Reflection

### Problema

Cuatro de siete campos de `ReflectionResult` son "archivo muerto":

| Campo | Downstream actual |
|-------|------------------|
| `belief_updates` | ✅ → SelfBelief |
| `user_belief_updates` | ✅ → BeliefAttribution |
| `memory_candidates` | ❌ solo ReflectionLog |
| `relationship_evidence` | ❌ solo ReflectionLog |
| `goal_updates` | ❌ solo ReflectionLog |
| `self_model_updates` | ❌ solo ReflectionLog |

Haiku genera estos campos gastando tokens en cada turno reflexivo. Nadie los lee después.

### Regla de arquitectura

Reflection no modifica el mundo cognitivo directamente. Produce hipótesis y evidencias. Cada dominio decide qué hacer con ellas.

La distinción fundamental entre observación explícita e inferencia:

```text
observación explícita → puede crear/modificar con confidence más alta
inferencia            → siempre pasa por ciclo candidato/evidencia/consolidación
```

Esta distinción es la más importante de toda la v2.0. Aparece en todos los campos de Reflection.

### memory_candidates → SemanticFactCandidate

No directamente a `SemanticFact`. El ciclo correcto:

```text
Reflection.memory_candidate
        ↓
SemanticFactCandidate
    ├── proposition
    ├── confidence (según inference_type)
    ├── evidence_episode_id
    ├── inference_type: explicit | inferred
    └── status: pending
        ↓
futuros turnos (confirmación / contradicción)
        ↓
SemanticFact
```

Límite de confidence por fuente: una inferencia de Reflection nunca puede entrar con `confidence > 0.45`. Una observación explícita puede entrar más alta.

### relationship_evidence → evidencia trazable

No suma directamente a `SocialProfile`. El riesgo de double counting (mismo turno contado por Appraisal y por Reflection) es real.

La evidencia debe ser trazable:
```text
dimension: trust_honesty
direction: positive
strength: 0.32
source: reflection
turn_id: 8271
reason: "El usuario compartió algo personal, señal de confianza"
```

Al procesar evidencias de la misma dimensión para el mismo turno, Appraisal domina. Reflection solo añade si detectó algo cualitativamente diferente.

Beneficio adicional: `SocialProfile` deja de ser un conjunto de números modificados mágicamente y pasa a ser el resultado acumulado de evidencia relacional trazable y auditable.

### goal_updates → GoalCandidate (con excepción)

Por defecto, los goal_updates de Reflection crean `GoalCandidate`, no `Goal` directamente. Una inferencia como "el usuario parece haber abandonado Rust" es demasiado peligrosa para aplicar directamente.

Excepción: si hay evidencia explícita verificable en el mensaje original + confidence alta de Reflection, se puede crear `Goal` directamente, verificando contra el source antes de hacerlo.

### self_model_updates → SelfBelief evidence

Ya existe infraestructura parcial. El ciclo completo:

```text
Reflection
    ↓
SelfBelief candidate (confidence acumulada)
    ↓
evidencia de múltiples turnos
    ↓
SelfBelief consolidada
```

Esto es el prerrequisito del punto siguiente (SelfModel → autorregulación).

------------------------------------------------------------------------

## PARTE XXVIII --- SelfModel → autorregulación

### Problema

`SelfModel` y `SelfBelief` almacenan creencias de Sity sobre sí misma. No influyen en `Decision`. Si solo aparecen en el panel de debug, son almacenamiento autobiográfico, no autorregulación.

### Riesgo: feedback loops

Antes de diseñar la solución, el riesgo principal:

```text
Reflection: "Sity tiende a ser demasiado confrontacional"
            ↓
SelfBelief confidence=0.72
            ↓
Decision reduce CHALLENGE
            ↓
Sity desafía menos
            ↓
Reflection observa menos confrontación
            ↓
SelfBelief permanece (profecía autocumplida)
```

La solución no es evitar la autorregulación — es acotar matemáticamente su impacto.

### Opción C: ajuste metacognitivo estructurado

Ni puramente explícita (ontología predefinida de creencias → acciones) ni puramente emergente (SelfBeliefs en el prompt sin control). El diseño híbrido:

```text
Personality ──────────────────┐
MentalState ──────────────────┤
Relationship ─────────────────┤
Goals ────────────────────────┤
Values ───────────────────────┤
Expectations ─────────────────┤
ProceduralMemory ─────────────┤
                              ▼
                       Base utilities
                              │
SelfBeliefs ────┐             │
                ▼             │
Current Context → Metacognitive
                  Adjustment
                      │
                      ▼
               bounded modifiers
                      │
                      ▼
                Final utilities
                      │
                      ▼
                   Decision
```

El LLM (metacognitive evaluator) interpreta libremente qué significa una SelfBelief en este contexto específico. El código determinista acota cuánto puede afectar al resultado.

### El ajuste matemático

El evaluador metacognitivo devuelve:
```json
{
  "relevant_beliefs": ["belief_184"],
  "adjustments": {"challenge": -0.8, "ask": 0.3},
  "reason": "La creencia sobre confrontación aplica en este contexto técnico"
}
```

El `-0.8` no se aplica directamente. El código lo acota:

```python
MAX_METACOGNITIVE_BIAS = 0.05

modifier = proposed_adjustment * belief.confidence * MAX_METACOGNITIVE_BIAS
# -0.8 × 0.72 × 0.05 = -0.0288
```

Resultado: `U(challenge) -= 0.029`\
No: `U(challenge) -= 0.8`

### Threshold de activación

```text
confidence < 0.60  → almacenada, no regula todavía
confidence ≥ 0.60  → puede producir metacognitive adjustment
confidence ≥ 0.80  → mayor influencia, siempre bounded
```

Esto crea una transición natural:

```text
Reflection: "quizá soy demasiado confrontacional"
conf=0.40 (hipótesis)
    ↓
más evidencia
    ↓
conf=0.67 (hay suficiente evidencia para tenerlo en cuenta)
    ↓
autorregulación
```

### Relevancia contextual

No se cargan todas las SelfBeliefs al evaluador. Primero se recuperan las relevantes al contexto actual. Una creencia sobre comportamiento en debates técnicos no debe afectar a una recomendación de película.

### Ajustes positivos también

Autorregulación no significa solo corregir defectos:

```text
SelfBelief: "Gestiono bien desacuerdos técnicos cuando primero pido al usuario que explique su razonamiento."
confidence: 0.79
→ ASK +0.03 en contexto de technical_design con challenge alto
```

`SelfModel` es un modelo aprendido de tendencias, fortalezas y limitaciones — no una lista de defectos que Sity intenta suprimir.

### Jerarquía de influencia

```text
Personality   → disposición basal fuerte
Values        → principios fuertes
Current state → qué ocurre ahora
SelfModel     → pequeña corrección metacognitiva
```

`SelfModel` nunca reescribe `Personality`. Una reflexión sobre cómo se comportó Sity no debe modificar indirectamente quién es Sity.

------------------------------------------------------------------------

## PARTE XXIX --- Principios adicionales de la v2.0

Los principios de la PARTE XXI se amplían con los aprendizajes de esta segunda fase:

21. **Observation explícita ≠ inferencia.** Son calidades de evidencia distintas con limits de confidence distintos. Esta distinción debe ser explícita en el código, no implícita.

22. **Reflection produce hipótesis; los dominios deciden.** Ningún output de Reflection modifica directamente el mundo cognitivo. Cada dominio (memoria, relación, metas, self-model) tiene su propio ciclo de evaluación de evidencia.

23. **Double counting es un fallo de arquitectura.** Si Appraisal y Reflection pueden actualizar la misma dimensión del mismo turno, el sistema tiene un sesgo sistemático. La evidencia trazable con `source` + `turn_id` permite detectarlo y resolverlo.

24. **La frecuencia de mención no es un proxy de importancia.** "Mañana nace mi hijo" dicho una vez supera en importancia a cualquier cosa mencionada cien veces. La importancia emerge de salience, emoción, goal_relevance, énfasis explícito y calibración procedimental.

25. **Expired_unknown ≠ violated.** Que el usuario no mencione algo no es evidencia de incumplimiento. Confundir estos estados corrompería `trust_reliability` de forma injusta.

26. **ProceduralPattern aprende a interpretar actos lingüísticos, no a catalogar temas.** "Cuando este usuario dice 'mañana hago X' con lenguaje de compromiso, suele cumplirlo" es procedural. "Ha mencionado Evangelion 4 veces" es historia semántica.

27. **El LLM interpreta; la arquitectura decide cuánto poder conceder.** Válido para metacognición, evidencia relacional, candidatos de memoria y cualquier output LLM que afecte al estado persistente.

28. **La autorregulación debe ser acotada y auditable.** MAX_METACOGNITIVE_BIAS garantiza que ninguna SelfBelief pueda dominar Decision. El `reason` del evaluador metacognitivo garantiza que el ajuste sea auditable.

------------------------------------------------------------------------

## Conclusión de la v2.0

La Operación Remake v1.0 construyó las piezas. La v2.0 cierra los bucles.

La diferencia entre el sistema al inicio de v1.0 y el sistema al final de v2.0 puede describirse así:

```text
v1.0 (inicio):
LLM + personalidad configurable + memoria + relación básica

v1.0 (final):
pipeline cognitivo completo con estado persistente que afecta Decision

v2.0 (final):
pipeline cognitivo completo donde:
- los episodios se recuperan y afectan la respuesta presente
- la negación tiene un único decisor
- la iniciativa surge del mismo cerebro que responde
- el estado emocional regula hacia un baseline con el tiempo
- las expectations generan aprendizaje cuando se resuelven
- la reflexión alimenta dominios que aprenden progresivamente
- sity puede regular su propio comportamiento dentro de límites
```

El salto conceptual de v1.0 fue:
> *Sity debe ser distinta mañana no porque el prompt de mañana sea distinto, sino porque lo que le ocurrió hoy haya modificado de forma controlada y persistente el estado desde el que procesará el mundo mañana.*

El salto conceptual de v2.0 es:
> *No basta con que el estado cambie. El estado debe retroalimentarse: los episodios deben recuperarse, las expectativas deben resolverse, la reflexión debe generar aprendizaje real, y Sity debe poder corregirse a sí misma dentro de límites arquitectónicos que preserven quién es.*

---

## Estado post-implementación completa (2026-10-01)

Durante las revisiones de la implementación se identificaron siete ajustes al diseño original
que no estaban en la especificación v2.0. Implementados en commits `fb4678c` (primera ronda)
y `3bc69b8` (segunda ronda). **P0 conocidos: 0. Listo para beta pública.**

### Primera ronda — fb4678c

#### 1. Evidence trail como fuente de verdad

**Diseño original:** `reinforcement_count` y `contradiction_count` eran la fuente primaria
para recalcular confidence en el merge de consolidación. El trail era append-only pero nunca
se reproducía.

**Ajuste:** Todo candidato nace con una entrada inicial en su trail. Nueva función
`recalculate_confidence_from_trail(trail, initial)` que reproduce las entradas en orden
cronológico — el orden importa (`s→c→s ≠ s→s→c`). El merge usa esta función con
`initial=0.0`, por lo que fusionar tres candidatos sin reinforcements extra produce
confianza > initial.

#### 2. Separación de triggers SF y SB

**Diseño original:** `_count_active_candidates(user_id)` sumaba SemanticFacts del usuario
y SelfBeliefs globales. Una única llamada Haiku recibía items mezclados de ambas tablas.
IDs podían colisionar (SF.id=5 y SB.id=5 son entidades distintas).

**Ajuste:** Dos funciones de conteo independientes: `_count_active_semantic_facts(user_id)`
y `_count_active_self_beliefs()` (global). Dos funciones de consolidación:
`_run_sf_volume_consolidation(user_id)` y `_run_sb_volume_consolidation()`. Haiku
nunca recibe mezcla de SF y SB en el mismo prompt. `maybe_trigger_volume_consolidation()`
dispara ambas de forma independiente con umbrales separados.

#### 3. CONTRADICT en el consolidation job offline

**Diseño original:** El prompt de agrupación solo definía "match" y "related". El handler
ignoraba silenciosamente cualquier respuesta que no fuera "match".

**Ajuste:** El prompt incluye "contradict" como relación válida. El handler para grupos
CONTRADICT añade una entrada `{relation:"contradict"}` al trail de cada miembro del grupo
(cross-referenciando al otro), recalcula confidence via trail, y NO fusiona las entidades.

#### 4. Ontología semántica unificada online/offline

El resolver online (`semantic_resolver.py`) ya usaba MATCH / RELATED / CONTRADICT / NEW.
El job offline ahora usa las mismas cuatro relaciones. Un par de creencias contradictorias
se detecta igual en tiempo real que en el job batch nocturno.

---

### Segunda ronda — 3bc69b8

#### 5. CONTRADICT offline idempotente

**Problema:** El consolidation job podía añadir múltiples entradas contradict al mismo par
(SF-A → SF-B) en ejecuciones repetidas, acumulando evidencia fantasma.

**Ajuste:** Cada entrada contradict incluye `target_id` (ID del otro extremo). Antes de
añadir una entrada, se verifica `already_known`: si ya existe
`{relation:"contradict", target_id==bid, source=="semantic_consolidation"}` en el trail,
se omite. El trail se lee una vez por item outer (no dentro del loop inner).

#### 6. Strength con significado real en el reducer

**Problema:** `recalculate_confidence_from_trail` usaba `learning_rate` fijo sin importar
el campo `strength` de cada entrada. Una observación débil (strength=0.10) movía igual
que una observación sólida (strength=0.90).

**Ajuste (modelo epistemológico final):**
```
support:    rate = learning_rate * ev["strength"]
            confidence += (1 - confidence) * rate
contradict: rate = contradiction_rate * ev["strength"]
            confidence -= confidence * rate
```
`learning_rate` y `contradiction_rate` son límites arquitectónicos (cuánto puede mover
cualquier evidencia en un turno). `strength` es el peso epistémico de esa evidencia
concreta. Evidencia con strength=0 no produce movimiento.

#### 7. Relación "initial" en evidence trail

**Problema:** La primera entrada del trail usaba `relation="support"`, tratando la creación
del candidato de la misma forma que una confirmación posterior. Esto distorsionaba el
replay cronológico: el prior inicial se sumaba como si fuera evidencia adicional.

**Ajuste:** Primera entrada usa `relation="initial"`.

**Semántica en `recalculate_confidence_from_trail`:**
- Primera entrada `"initial"` → establece el prior: `confidence = strength`
- Entradas `"initial"` adicionales (en merges) → actúan como support ponderado
- `"support"` y `"contradict"` → comportamiento actual, ponderado por strength

`_normalize_trail_entry` preserva `"initial"` (no convierte a `"support"` durante merges).
`upsert_semantic_candidate()` escribe `{relation:"initial", source:"reflection_initial"}`.
`add_belief_candidate()` escribe `{relation:"initial"}` para entradas no-contradicción.

---

### Modelo epistemológico final del evidence trail

```
{
  "turn_id":    str,     # turno que generó la evidencia
  "relation":   str,     # "initial" | "support" | "contradict"
  "strength":   float,   # peso epistémico [0.0, 1.0]
  "source":     str,     # "reflection_initial" | "reflection" | "semantic_consolidation" | ...
  "target_id":  int,     # (solo en contradict) ID de la entidad que contradice
  "description": str,
  "timestamp":  str,     # ISO UTC, clave de ordenación para replay
}
```

El trail es la única fuente de verdad para confidence. Los contadores `reinforcement_count`
/ `contradiction_count` son caché para consultas rápidas, recalculados en cada merge.


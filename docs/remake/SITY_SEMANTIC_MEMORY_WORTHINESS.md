# Sity — Separación de Salience y Memory Worthiness

**Estado:** listo para implementación  
**Prerequisito:** Mini-Remake v2.0 completada  
**Revisado con:** ChatGPT (cuatro rondas de feedback)  
**Problema raíz:** salience y memorabilidad semántica son variables distintas pero actualmente se usan como si fueran la misma.

---

## El problema

La arquitectura actual usa `salience_total >= 0.30` como único gate para que Reflection corra y consolide `SemanticFacts`.

Esto mezcla dos preguntas conceptualmente distintas:

```text
Pregunta A: ¿Importa este evento para el estado cognitivo AHORA?
→ Responde: Event Salience
→ Unidad evaluada: turno/evento
→ Determina: si se crea Episode, si corre Reflection profunda

Pregunta B: ¿Contiene una proposición información durable sobre el usuario?
→ Responde: Memory Worthiness
→ Unidad evaluada: proposición semántica
→ Determina: si se consolida, refuerza o revisa un SemanticFact
```

El síntoma más claro: "Odio el café" puede tener `salience ≈ 0.15` pero Memory Worthiness alta. Con la arquitectura actual, ese hecho nunca se consolida — y Sity puede responder "Anotado, no lo olvidaré" aunque ningún mecanismo haya persistido realmente esa información.

### Casos que ilustran la separación

| Turno | Salience | Memory Worthiness | Comportamiento correcto |
|---|---:|---:|---|
| "Odio el café" | baja (~0.15) | alta (~0.85) | No Reflection, sí SemanticFact |
| "¡ME CAGO EN TODO, SE ME HA CAÍDO EL CAFÉ!" | alta (~0.78) | baja (~0.09) | Sí Reflection, no SemanticFact |
| "Hoy no me apetece café" | baja (~0.12) | baja (~0.24) | Nada |
| "Nunca tomo café, prefiero el té" | baja (~0.14) | alta (~0.91) | No Reflection, sí SemanticFact |
| "Últimamente le estoy pillando el gusto al café" | media (~0.35) | media (~0.55) | Reflection posible + revisión de creencia |

---

## Principio fundamental: turno vs proposición

> **Salience es principalmente una propiedad del evento.**  
> **Memory Worthiness es una propiedad de la proposición.**

Un único turno puede contener información con valores de memoria completamente distintos:

> "Odio el café, hoy estoy cansado y mi perro se llama Toby."

Produce al menos:

```text
P1: user dislikes coffee     → alta MW → consolidar/reforzar
P2: user is tired today      → baja MW → ignorar
P3: user's dog is named Toby → alta MW → consolidar/reforzar
```

Por tanto `memory_operation` no puede ser un valor global del turno — debe ser por proposición.

---

## Diseño: dos rutas independientes

```text
                                   ┌─ Event Appraisal → Salience → Reflection
Turn ──> Perception / Interpretation
                                   └─ SemanticProposition[] → Memory Worthiness → Consolidation
```

Ambas rutas pueden ejecutarse independientemente dentro del mismo turno.

---

## SemanticProposition

```python
@dataclass
class SemanticProposition:
    id: str
    content: str
    properties: SemanticProperties
```

`PerceptionResult` contiene:

```python
semantic_propositions: list[SemanticProposition]
```

La evaluación de MW se realiza por cada elemento independientemente.

---

## SemanticProperties

Propiedades abstractas aplicables a cualquier dominio — sin taxonomías manuales:

```python
@dataclass
class SemanticProperties:
    personal_relevance: float    # 0.0=externo, 1.0=directamente sobre el usuario
    temporal_scope: str          # "persistent"|"habitual"|"transient"|"situational"
    context_dependency: float    # 0.0=general, 1.0=depende del contexto actual
    assertion_strength: float    # 0.0=hipotético, 1.0=afirmación clara
    expected_duration: float     # 0.0=momentáneo, 1.0=permanente
    behavioral_relevance: float  # 0.0=no cambia decisiones de Sity, 1.0=sí cambia
```

### personal_relevance como escala continua

```text
"Soy vegetariano"           → 1.00
"Mi perro se llama Toby"    → 0.85
"Mi compañero usa Linux"    → 0.45
"Einstein nació en Alemania"→ 0.00
```

### context_dependency como penalización parcial

```text
"No me gusta el café"                               → 0.05
"No me gusta el café de este sitio"                 → 0.80
"No quiero conducir esta noche porque estoy cansado"→ 0.85
```

---

## Memory Worthiness (MW)

### Cálculo

```python
MW_base = (
    expected_duration    * 0.30 +
    behavioral_relevance * 0.25 +
    personal_relevance   * 0.25 +
    assertion_strength   * 0.20
)

MW_effective = MW_base * (1 - CONTEXT_PENALTY * context_dependency)
```

Configuración inicial (hiperparámetros v1, calibrar con datos reales):

```python
CONTEXT_PENALTY = 0.5
MW_GATE = 0.40
```

### Gate

```python
if MW_effective < MW_GATE:
    operation = IGNORED
else:
    continue_to_semantic_resolver()
```

**Nota:** `novelty` no forma parte de MW. El Semantic Resolver (NEW/MATCH/RELATED/CONTRADICT) ya la contiene implícitamente.

---

## Pipeline de consolidación

El Semantic Resolver corre **antes** de cualquier evaluación Haiku cara:

```text
SemanticProposition
        ↓
SemanticProperties
        ↓
MW_effective >= MW_GATE?
        ↓
Semantic Resolver
        ↓
NEW / MATCH / RELATED / CONTRADICT
        ↓
consolidate / reinforce / linked consolidate / revise
        ↓
persist → MemoryResult
        ↓
Expression
```

### NEW
Información no existente. Evaluación Haiku detallada antes de consolidar.

### MATCH
Coincide con un SemanticFact existente. No requiere evaluación LLM completa.
```text
calculate evidence_value → append evidence → recalculate confidence → persist
operation = reinforce
```

### CONTRADICT
Evidencia incompatible con una creencia existente. No se sobrescribe directamente.
```text
append contradictory evidence → recalculate_confidence_from_trail() → belief revision → persist
operation = revise
```

### RELATED
Información relacionada pero distinta. Requiere interpretación adicional:
```text
relation confidence suficiente?
    Sí → nuevo SemanticFact + related_fact_ids + persist
    No → detailed assessment → decidir path definitivo
```
Haiku se usa para NEW y para RELATED cuando la relación necesite interpretación. MATCH no requiere evaluación completa.

---

## Evidence Value vs Novelty

```text
T1:  "No me gusta el café."      → NEW, confidence inicial
T20: "Ya sabes que odio el café."→ MATCH, evidence_value alto
```

La segunda afirmación tiene baja novelty pero alto evidence_value. Son conceptos distintos — la baja novelty no implica baja utilidad para el sistema de creencias.

---

## MemoryResult

```python
@dataclass
class MemoryResult:
    proposition_id: str
    operation: MemoryOperation  # resultado semántico final
    persisted: bool
    fact_id: str | None
    related_fact_ids: list[str]

class MemoryOperation(Enum):
    """Operación semántica de memoria — resultado final del procesamiento."""
    IGNORED     = "ignored"
    CONSOLIDATE = "consolidate"
    REINFORCE   = "reinforce"
    REVISE      = "revise"

class MemoryProcessingState(Enum):
    """Estado interno del pipeline — no expuesto en MemoryResult."""
    CANDIDATE   = "candidate"
    RESOLVING   = "resolving"
    PERSISTING  = "persisting"
    COMPLETED   = "completed"
```

`CognitionTurnResult` contiene:

```python
memory_results: list[MemoryResult]
memory_any_persisted: bool  # resumen para Expression
```

### Ejemplo multi-proposición

```python
# "Odio el café, hoy estoy cansado y mi perro se llama Toby."
memory_results = [
    MemoryResult("p1", REINFORCE,   persisted=True,  fact_id="fact_coffee", ...),
    MemoryResult("p2", IGNORED,     persisted=False, fact_id=None, ...),
    MemoryResult("p3", CONSOLIDATE, persisted=True,  fact_id="fact_dog_name", ...),
]
```

---

## Expression y memoria

Expression basa sus afirmaciones **únicamente en `persisted`**:

```text
persisted=False            → no prometer memoria futura
persisted=True, CONSOLIDATE→ "Lo tendré en cuenta."
persisted=True, REINFORCE  → Expression puede comportarse como si la información ya formara parte de su modelo, sin necesidad de explicitar que la recuerda
persisted=True, REVISE     → responder según creencia actualizada
operation=IGNORED          → no mencionar almacenamiento
```

Esto elimina el desacoplamiento entre lo que Sity dice y lo que el sistema ha hecho realmente.

---

## Orden de implementación

1. `SemanticProposition` y `SemanticProperties`
2. `PerceptionResult.semantic_propositions: list[SemanticProposition]`
3. `evaluate_memory_worthiness(proposition)` en turn_cognition.py
4. Parámetros configurables: `MW_GATE`, `CONTEXT_PENALTY`, pesos de MW
5. Conectar cada proposición viable al Semantic Resolver existente
6. Implementar los cuatro paths: NEW / MATCH / RELATED / CONTRADICT
7. `MemoryResult` y `memory_results` en `CognitionTurnResult`
8. Inyectar resultados de memoria en Expression
9. Instrumentación de MW scores para calibración futura
10. Tests unitarios y de comportamiento

---

## Tests mínimos

- "Odio el café" → MW >= gate → consolidate/reinforce → persisted=True
- "Hoy estoy cansado" → MW < gate → ignored → persisted=False
- "¡ME CAGO EN TODO!" → salience alta → Reflection=True → memory persisted=False
- "Mi perro se llama Toby" → MW >= gate → consolidate → persisted=True
- "No me gusta el café de este sitio" → context_dependency alta → MW penalizada
- "Ya sabes que odio el café" (existente: dislikes coffee) → MATCH → reinforce
- "Últimamente le estoy pillando el gusto al café" → CONTRADICT → revise
- "Prefiero el té" (existente: dislikes coffee) → RELATED → evaluar relation confidence → consolidate → link solo si confidence suficiente
- "Odio el café, hoy estoy cansado y mi perro se llama Toby" → tres MemoryResult independientes
- Expression con persisted=False → no afirma "lo recordaré"
- Expression con persisted=True, CONSOLIDATE → puede afirmar que lo tendrá en cuenta

---

## Observabilidad para calibración

Registrar en cada turno:
```text
proposition, expected_duration, behavioral_relevance, personal_relevance,
assertion_strength, context_dependency, MW_base, MW_effective,
resolver_result, memory_operation, persisted, fact_id
```

Los pesos iniciales no deben ajustarse por intuición — calibrar con datos reales observados.

---

## Separación conceptual final

| Mecanismo | Unidad | Pregunta |
|---|---|---|
| **Salience** | evento/turno | ¿Esto merece atención cognitiva inmediata? |
| **Memory Worthiness** | proposición | ¿Esto merece persistencia semántica? |
| **Semantic Resolver** | proposición vs memoria | ¿Qué relación tiene con lo que ya sé? |
| **Evidence Value** | nueva evidencia | ¿Cuánto modifica/refuerza lo que creo? |
| **Evidence Trail** | creencia | ¿Qué evidencias sustentan esta creencia? |
| **MemoryResult.persisted** | operación | ¿Ha quedado realmente almacenado? |

---

## Principios preservados

- Salience y Memory Worthiness tienen autoridades distintas
- Salience evalúa eventos; MW evalúa proposiciones
- Sin taxonomías manuales de dominio
- El LLM interpreta; la arquitectura decide cuánto poder conceder
- Los thresholds y pesos son configurables e instrumentables
- Semantic Resolver se ejecuta antes de evaluaciones LLM caras
- MATCH reutiliza el sistema de evidencia existente sin evaluación completa
- CONTRADICT usa belief revision, no sobrescritura directa
- RELATED no implica automáticamente un enlace semántico
- Evidence trail continúa siendo la fuente de verdad de las creencias
- Expression solo puede afirmar persistencia cuando existe persistencia real
- Un turno puede producir múltiples operaciones de memoria independientes

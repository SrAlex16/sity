# Sity — Separación de Salience y Memory Worthiness

**Estado:** propuesta de implementación  
**Prerequisito:** Mini-Remake v2.0 completada  
**Problema raíz:** salience y memorabilidad semántica son variables distintas pero actualmente se usan como si fueran la misma.

---

## El problema

La arquitectura actual usa `salience_total >= 0.30` como único gate para que Reflection corra y consolide SemanticFacts. Esto mezcla dos preguntas conceptualmente distintas:

```
Pregunta A: ¿Importa este evento para el estado cognitivo AHORA?
→ Responde: Event Salience
→ Determina: si se crea Episode, si corre Reflection profunda

Pregunta B: ¿Contiene este turno información durable sobre el usuario?
→ Responde: Memory Worthiness
→ Determina: si se consolida un SemanticFact
```

El síntoma más claro: "Odio el café" tiene salience ~0.15 (evento poco relevante para el estado cognitivo de Sity) pero memory worthiness alta (preferencia estable, personal, reutilizable en futuras conversaciones). Con la arquitectura actual, nunca se consolida — y Sity puede decir "anotado, no lo olvidaré" sin que ningún mecanismo haya respaldado esa promesa.

### Casos que ilustran la separación

| Turno | Salience | Memory Worthiness | Comportamiento correcto |
|-------|----------|-------------------|------------------------|
| "Odio el café" | baja (0.15) | alta (0.85) | No Reflection, sí SemanticFact |
| "¡ME CAGO EN TODO, SE ME HA CAÍDO EL CAFÉ!" | alta (0.78) | baja (0.09) | Sí Reflection, no SemanticFact |
| "Hoy no me apetece café" | baja (0.12) | baja (0.24) | Nada |
| "Nunca tomo café, prefiero el té" | baja (0.14) | alta (0.91) | No Reflection, sí SemanticFact |
| "Últimamente le estoy pillando el gusto al café" | media (0.35) | media (0.55) | Sí Reflection, revision de creencia anterior |

---

## Diseño: dos rutas independientes

```
                         ┌─ Event Salience ──> Reflection (episodic, metacognition)
Turn ──> Interpretation ─┤
                         └─ Memory Worthiness ──> Semantic consolidation
```

Estas rutas no se excluyen — pueden correr en el mismo turno o por separado.

---

## Memory Worthiness (MW)

### Dimensiones

```
MW(p) = f(persistence, future_utility, personal_specificity, novelty, confidence)
```

| Dimensión | Pregunta | Ejemplo alto | Ejemplo bajo |
|-----------|----------|--------------|--------------|
| `persistence` | ¿Seguirá siendo cierto dentro de semanas/meses? | "Odio el café" | "Hoy estoy cansado" |
| `future_utility` | ¿Podría cambiar una respuesta/decisión futura de Sity? | "Soy vegetariano" | "Tengo una taza azul" |
| `personal_specificity` | ¿Describe específicamente al usuario? | "Me llamo Alex" | "El café es amargo" |
| `novelty` | ¿Sity ya lo sabía? | Primera mención | Repetición |
| `confidence` | ¿Está expresado como hecho/preferencia o es ambiguo? | "Odio el café" | "Quizás me guste el café" |

### Cálculo

MW se calcula en un nuevo paso ligero de evaluación semántica — sin llamada Haiku por defecto, usando las señales ya disponibles de Perception y Appraisal. Solo si MW supera un threshold intermedio se hace una evaluación Haiku más detallada.

```
MW_quick = (persistence_signal × 0.30) +
           (future_utility_signal × 0.25) +
           (personal_specificity × 0.25) +
           (novelty × 0.20)

if MW_quick >= MW_QUICK_THRESHOLD (0.40):
    → evaluación Haiku detallada
    → crear/reforzar SemanticFactCandidate

if MW_quick < MW_QUICK_THRESHOLD:
    → descartar sin llamada Haiku
```

### Señales disponibles sin Haiku

- **persistence_signal**: inferida de Perception (context_type=planning → baja, preferencia en casual_chat → alta)
- **personal_specificity**: ¿el sujeto es el usuario? (detectado en Perception)
- **novelty**: comparación con SemanticFacts existentes del usuario
- **future_utility**: parcialmente derivable del tipo de proposición (preferencia → alta, estado emocional transitorio → baja)

---

## Integración con la arquitectura existente

### Lo que ya existe y se reutiliza

- `SemanticFactCandidate` con `confidence`, `inference_type`, `evidence_trail` — ya implementado
- Semantic resolver (MATCH/RELATED/CONTRADICT/NEW) — ya implementado
- Consolidation job por volumen — ya implementado
- `explicit_importance` en AppraisalResult — ya existe, se reutiliza como señal

### Lo que se añade

1. **Nuevo paso en turn_cognition.py**: `evaluate_memory_worthiness()` después de Appraisal, antes de Reflection
2. **Nuevo campo en CognitionTurnResult**: `memory_candidates: list[SemanticFactCandidate]`
3. **memory_status en el turno**: `ignored | candidate | consolidated | reinforced | revised`

---

## El bug de Expression

Actualmente Sity puede responder "anotado, no lo olvidaré" aunque ningún mecanismo haya consolidado nada. Expression no tiene acceso al resultado de memoria del turno.

### Fix

`memory_status` del turno se inyecta en el contexto de Expression:

```
memory_status: candidate
→ Expression puede afirmar que lo ha tomado nota

memory_status: ignored
→ Expression NO debe prometer que lo recordará
→ Puede decir "entendido" pero no "lo recordaré"

memory_status: consolidated
→ Expression puede confirmar con plena seguridad
```

Esto elimina el desacoplamiento entre lo que Sity dice y lo que el sistema hace.

---

## Estados de memoria

```
ignored     → MW < threshold, descartado
candidate   → MW >= threshold, pendiente de consolidación
consolidated → promovido a SemanticFact activo
reinforced  → SemanticFact existente reforzado con nueva evidencia
revised     → SemanticFact existente modificado por evidencia contradictoria
```

---

## Belief revision

Cuando un nuevo candidato contradice un SemanticFact existente:

```
old belief: "user dislikes coffee" confidence=0.91
new evidence: "User increasingly likes coffee"

→ NO sobrescribir directamente
→ crear evidencia contradictoria
→ revision: confidence ajustada según peso de evidencias
→ si confidence < threshold: marcar como "under revision"
```

El semantic resolver existente (CONTRADICT) ya maneja parte de esto — la integración con MW añade el paso de evaluación previo.

---

## Orden de implementación

1. `evaluate_memory_worthiness()` con señales rápidas (sin Haiku) — primer gate
2. Evaluación Haiku detallada para candidatos que superan el primer gate
3. `memory_status` en CognitionTurnResult
4. Inyección de `memory_status` en Expression
5. Tests de comportamiento: "odio el café" → SemanticFactCandidate creado

---

## Principios que preserva

- **El LLM interpreta; la arquitectura decide cuánto poder conceder** — MW_quick es determinista; Haiku solo evalúa los candidatos que superan el threshold rápido
- **Reflection y Memory Worthiness son autoridades diferentes** — no se mezclan
- **Sin hardcoding de patrones de lenguaje** — MW emerge de propiedades semánticas de la proposición, no de strings específicos

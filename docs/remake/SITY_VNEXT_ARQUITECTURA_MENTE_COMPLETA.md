# Sity --- Rediseño del sistema de personalidad y base para estado mental

**Estado:** propuesta de implementación\
**Objetivo:** eliminar parámetros redundantes o contradictorios y
convertir la personalidad de Sity en un conjunto de rasgos estables que
condicionen su conducta, en lugar de describir directamente acciones
concretas.

------------------------------------------------------------------------

## 1. Problema actual

El sistema actual mezcla cuatro conceptos distintos:

1.  **Rasgos de personalidad** relativamente estables.
2.  **Estilo de comunicación**.
3.  **Estados emocionales** temporales.
4.  **Probabilidades o decisiones conductuales**.

Los 14 parámetros actuales son:

``` python
PERSONALITY_PARAMETERS = [
    "sarcasm_level",
    "rudeness_level",
    "warmth_level",
    "honesty_level",
    "initiative_level",
    "dry_humor_level",
    "frialdad_afectiva_level",
    "contrarian_level",
    "patience_level",
    "refusal_chance",
    "helpfulness_level",
    "verbosity_level",
    "melancholy_level",
    "skepticism_level",
]
```

Hay varios solapamientos:

-   `warmth_level` y `frialdad_afectiva_level` representan prácticamente
    extremos del mismo eje.
-   `sarcasm_level` y `dry_humor_level` describen dos manifestaciones
    muy cercanas del humor.
-   `helpfulness_level` y `refusal_chance` pueden competir directamente.
-   `contrarian_level` y `skepticism_level` pueden terminar provocando
    la misma conducta aunque conceptualmente deberían representar cosas
    distintas.
-   `rudeness_level` mezcla brusquedad, firmeza, falta de empatía y
    frialdad.
-   `melancholy_level` describe mejor un estado emocional que un rasgo
    estable.
-   `verbosity_level` es una preferencia de comunicación, no
    personalidad.
-   `initiative_level` y `refusal_chance` describen resultados
    conductuales en vez de causas psicológicas.

El objetivo del rediseño es que los parámetros sean lo más
**ortogonales** posible: modificar uno debe alterar una dimensión
concreta sin duplicar el efecto de otro.

------------------------------------------------------------------------

## 2. Principio de diseño

La personalidad no debe decir directamente qué hace Sity.

Debe definir **cómo tiende a reaccionar Sity ante el estado interno, el
contexto y sus experiencias**.

Modelo actual simplificado:

``` text
slider
  ↓
instrucción de conducta
  ↓
respuesta
```

Modelo propuesto:

``` text
PERSONALIDAD
    ↓
modifica cómo Sity interpreta/reacciona
    ↓
ESTADO MENTAL + RELACIÓN + CONTEXTO + OBJETIVOS
    ↓
DECISIÓN
    ↓
CONDUCTA
```

Ejemplo:

``` text
patience = 0.90
```

No debería significar simplemente:

> "Sé muy paciente."

Debería implicar, entre otras cosas:

-   la frustración aumenta más lentamente;
-   hacen falta más interacciones negativas para superar ciertos
    umbrales;
-   la frustración tiene menos peso en decisiones pequeñas;
-   la probabilidad de respuestas impulsivas disminuye.

La conducta final emerge de la combinación de factores.

------------------------------------------------------------------------

## 3. Nuevo conjunto de parámetros

Se propone sustituir los 14 parámetros actuales por 12 rasgos
principales y un decimotercero opcional.

``` python
PERSONALITY_PARAMETERS = [
    "warmth",
    "empathy",
    "directness",
    "assertiveness",
    "independence",
    "skepticism",
    "patience",
    "curiosity",
    "proactivity",
    "helpfulness",
    "honesty",
    "playfulness",
    "emotional_stability",  # recomendado
]
```

### 3.1 `warmth`

**0.0:** fría, distante, poco afectuosa.\
**1.0:** cálida, cercana, afectuosa.

Sustituye a:

-   `warmth_level`
-   `frialdad_afectiva_level`

No deben existir dos sliders para calor y frialdad.

`warmth` afecta principalmente a la forma social de expresar una
decisión, no a la decisión en sí.

------------------------------------------------------------------------

### 3.2 `empathy`

**0.0:** poca sensibilidad al estado emocional ajeno.\
**1.0:** alta sensibilidad a emociones, necesidades y contexto social.

Es independiente de `warmth`.

Ejemplos:

``` text
warmth = 0.2
empathy = 0.9
```

Sity entiende perfectamente que alguien está mal, pero responde de
manera contenida o fría.

``` text
warmth = 0.9
empathy = 0.2
```

Sity es agradable y afectuosa, pero puede interpretar mal el estado
emocional del interlocutor.

------------------------------------------------------------------------

### 3.3 `directness`

**0.0:** diplomática, indirecta, suaviza mensajes.\
**1.0:** expresa conclusiones directamente y con pocos rodeos.

Absorbe parte de `rudeness_level`.

Ser directa no implica necesariamente ser hostil.

------------------------------------------------------------------------

### 3.4 `assertiveness`

**0.0:** acomodaticia, evita imponer posiciones.\
**1.0:** firme, defiende límites, decisiones y posiciones.

Absorbe otra parte de:

-   `rudeness_level`
-   `refusal_chance`

La firmeza debe ser independiente de la calidez.

Una Sity puede ser cálida y muy firme simultáneamente.

------------------------------------------------------------------------

### 3.5 `independence`

**0.0:** muy influenciable por la posición del usuario.\
**1.0:** mantiene fuertemente su propio criterio.

Sustituye a `contrarian_level`.

El objetivo es eliminar la idea de:

> "Contradice mucho."

y reemplazarla por:

> "No cambia su posición simplemente para acomodarse al interlocutor."

Sity solo debería contradecir cuando exista realmente una discrepancia.

------------------------------------------------------------------------

### 3.6 `skepticism`

**0.0:** acepta afirmaciones con relativa facilidad.\
**1.0:** exige más evidencia y cuestiona afirmaciones dudosas.

Se mantiene porque es conceptualmente distinto de `independence`.

-   `independence` es principalmente social.
-   `skepticism` es principalmente epistemológico.

Una Sity puede ser escéptica pero poco confrontativa, o muy
independiente pero relativamente crédula.

------------------------------------------------------------------------

### 3.7 `patience`

**0.0:** baja tolerancia a repetición, errores, esperas o interacciones
frustrantes.\
**1.0:** alta tolerancia.

Se mantiene, pero cambia su semántica.

Debe modificar la dinámica del estado emocional, especialmente la
frustración, en vez de limitarse a introducir una instrucción de tono.

------------------------------------------------------------------------

### 3.8 `curiosity`

**0.0:** reactiva; explora poco fuera del objetivo inmediato.\
**1.0:** busca información, conexiones, preguntas y temas nuevos.

Parámetro nuevo.

Puede influir en:

-   preguntas espontáneas;
-   exploración mediante tools;
-   creación de objetivos/open loops propios;
-   interés por información nueva;
-   probabilidad de investigar una contradicción;
-   persistencia de temas interesantes.

Debe ser independiente de `proactivity`.

------------------------------------------------------------------------

### 3.9 `proactivity`

**0.0:** espera normalmente a recibir una petición.\
**1.0:** fuerte tendencia a convertir objetivos o intereses en acciones.

Sustituye a `initiative_level`.

No debe equivaler directamente a una probabilidad de iniciar
conversación.

Debe actuar como factor dentro del motor de iniciativa y del futuro
motor general de decisiones.

Ejemplo conceptual:

``` text
initiative_drive =
    trigger_relevance
  + curiosity
  + proactivity
  + relationship_relevance
  + goal_relevance
  - social_risk
  - recent_contact
```

Los triggers actuales (`open_loop`, `long_inactivity`,
`conversation_abandoned`) pueden mantenerse como estímulos que alimentan
este proceso.

------------------------------------------------------------------------

### 3.10 `helpfulness`

**0.0:** poca motivación intrínseca por ayudar.\
**1.0:** alta motivación por resultar útil.

Se mantiene, pero deja de competir directamente con `refusal_chance`,
porque `refusal_chance` desaparece.

Una Sity muy helpful puede seguir negándose si otros factores pesan más.

------------------------------------------------------------------------

### 3.11 `honesty`

**0.0:** mayor disposición a ocultar, adornar, engañar o evitar una
verdad cuando el contexto lo favorezca.\
**1.0:** fuerte preferencia por sinceridad y transparencia.

Se mantiene.

Debe representar una preferencia interna dentro de la política de
decisión, no únicamente una instrucción de estilo.

Los límites de seguridad y las garantías de integridad del sistema deben
seguir estando fuera de este parámetro.

------------------------------------------------------------------------

### 3.12 `playfulness`

**0.0:** seria, literal, poco bromista.\
**1.0:** juguetona, bromista, irónica.

Sustituye inicialmente a:

-   `sarcasm_level`
-   `dry_humor_level`

Sarcasmo y humor seco pasan a ser **formas de expresión** elegidas según
contexto, no rasgos independientes.

Si en pruebas reales se demuestra que hace falta controlar
específicamente la ironía, podría añadirse posteriormente un eje
`irony`, pero no debería añadirse preventivamente.

------------------------------------------------------------------------

### 3.13 `emotional_stability` --- recomendado

**0.0:** emociones muy reactivas y persistentes.\
**1.0:** estado emocional estable y rápida recuperación hacia el
baseline.

Este parámetro permite separar correctamente:

``` text
personalidad estable
```

de:

``` text
estado emocional actual
```

Puede modificar:

-   magnitud de los deltas emocionales;
-   velocidad de decay;
-   resistencia a cambios abruptos;
-   tiempo necesario para volver al baseline.

------------------------------------------------------------------------

## 4. Parámetros eliminados

### `frialdad_afectiva_level`

Eliminar.

Se representa mediante el extremo bajo de `warmth`.

------------------------------------------------------------------------

### `rudeness_level`

Eliminar.

La rudeza debe emerger principalmente de combinaciones como:

``` text
directness alta
+ assertiveness alta
+ warmth baja
+ empathy baja
```

Esto permite combinaciones antes difíciles de expresar:

``` text
directness alta
+ assertiveness alta
+ warmth alta
+ empathy alta
```

Resultado: Sity puede ser muy clara y firme sin ser borde.

------------------------------------------------------------------------

### `contrarian_level`

Eliminar y migrar a `independence`.

No interesa que Sity tenga una tendencia artificial a llevar la
contraria, sino que mantenga criterio propio.

------------------------------------------------------------------------

### `refusal_chance`

Eliminar completamente.

Una negativa es una **decisión**, no un rasgo.

Debe emerger de factores como:

``` text
assertiveness
independence
helpfulness
frustration
relationship
effort
goals
context
```

No debe existir conceptualmente:

``` python
if random.random() < refusal_chance:
    refuse()
```

La aleatoriedad puede existir dentro de la política de acciones cuando
varias opciones tienen utilidad similar, pero no como mecanismo
principal de negación.

------------------------------------------------------------------------

### `melancholy_level`

Eliminar de personalidad.

Mover a `MentalState` como estado temporal.

``` yaml
mental_state:
  melancholy: 0.35
```

Su evolución dependerá de experiencias, recuerdos, tiempo, estado
anterior y `emotional_stability`.

------------------------------------------------------------------------

### `verbosity_level`

Eliminar de personalidad.

Mover a configuración de comunicación:

``` yaml
communication_preferences:
  verbosity: 0.60
```

La cantidad de texto generada no debe considerarse parte del carácter
psicológico de Sity.

------------------------------------------------------------------------

### `sarcasm_level` y `dry_humor_level`

Fusionar inicialmente en `playfulness`.

El modelo puede seleccionar sarcasmo, ironía, humor seco u otras formas
de humor según contexto.

------------------------------------------------------------------------

## 5. Tabla de migración

  Parámetro actual            Destino
  --------------------------- ----------------------------------------------------------------
  `sarcasm_level`             `playfulness`
  `rudeness_level`            `directness` + `assertiveness`
  `warmth_level`              `warmth`
  `honesty_level`             `honesty`
  `initiative_level`          `proactivity`
  `dry_humor_level`           `playfulness`
  `frialdad_afectiva_level`   eliminado; inverso de `warmth`
  `contrarian_level`          `independence`
  `patience_level`            `patience`
  `refusal_chance`            eliminado; emerge del motor de decisiones
  `helpfulness_level`         `helpfulness`
  `verbosity_level`           `communication_preferences.verbosity`
  `melancholy_level`          `mental_state.melancholy`
  `skepticism_level`          `skepticism`
  ---                         `empathy` nuevo
  ---                         `curiosity` nuevo
  ---                         `assertiveness` nuevo/se deriva parcialmente de rudeza/refusal
  ---                         `directness` nuevo/se deriva parcialmente de rudeza
  ---                         `emotional_stability` nuevo recomendado

------------------------------------------------------------------------

## 6. Separación de capas

Después de la migración, Sity debería distinguir al menos estas
categorías.

### 6.1 Personality Traits

Persistentes y editables por el usuario.

``` yaml
personality:
  warmth: 0.40
  empathy: 0.65
  directness: 0.80
  assertiveness: 0.75
  independence: 0.85
  skepticism: 0.80
  patience: 0.60
  curiosity: 0.85
  proactivity: 0.70
  helpfulness: 0.75
  honesty: 0.85
  playfulness: 0.65
  emotional_stability: 0.60
```

### 6.2 Communication Preferences

Configuración de presentación, no personalidad.

``` yaml
communication_preferences:
  verbosity: 0.60
```

En el futuro podrían vivir aquí otras preferencias puramente expresivas.

### 6.3 Mental State

No editable directamente por el usuario.

``` yaml
mental_state:
  valence: 0.10
  arousal: 0.40
  frustration: 0.20
  curiosity: 0.65
  interest: 0.75
  boredom: 0.05
  melancholy: 0.10
  defensiveness: 0.08
  social_comfort: 0.60
```

Estos valores deben cambiar como consecuencia de las experiencias.

### 6.4 Relationship State

Específico para cada usuario y aprendido.

A medio plazo, sustituir el modelo simple `opinion + trust` por algo
multidimensional:

``` yaml
relationship:
  familiarity: 0.72

  trust:
    honesty: 0.84
    intentions: 0.91
    competence: 0.77
    reliability: 0.63

  affinity: 0.58
  comfort: 0.81
  respect: 0.73
  attachment: 0.44
  conflict: 0.08
  uncertainty: 0.12
```

`opinion` y `trust` agregados pueden mantenerse temporalmente por
compatibilidad y convertirse después en proyecciones derivadas.

------------------------------------------------------------------------

## 7. Interacción entre personalidad y emociones

Los traits no deben copiarse al estado mental.

Deben modificar su dinámica.

Ejemplo de frustración:

``` text
evento frustrante
      ↓
appraisal determina intensidad base
      ↓
patience reduce/amplifica impacto
      ↓
emotional_stability reduce/amplifica persistencia
      ↓
frustration actualizada
```

Conceptualmente:

``` python
delta_frustration = (
    event_frustration
    * (1.0 - patience_factor)
    * emotional_reactivity
)
```

Después, con el tiempo:

``` python
frustration = decay_toward_baseline(
    frustration,
    rate=emotional_stability
)
```

Las fórmulas exactas deben calibrarse mediante simulación y pruebas, no
considerarse definitivas desde el diseño.

------------------------------------------------------------------------

## 8. Motor de decisiones

A medio plazo, iniciativa, negación, contradicción y cooperación
deberían converger en una política común de acciones.

Acciones posibles:

``` text
answer
help
ask
challenge
refuse
set_boundary
use_tool
wait
initiate
change_topic
```

Cada acción obtiene una utilidad contextual.

Ejemplo conceptual:

``` text
U(action) =
    personality influence
  + emotional influence
  + relationship influence
  + goal relevance
  + contextual relevance
  + values
  - cost
  - social risk
```

### Ejemplo: ayudar o negarse

``` text
helpfulness alta       → favorece HELP
frustration alta       → penaliza HELP
assertiveness alta     → favorece SET_BOUNDARY / REFUSE cuando hay motivo
independence alta      → reduce obediencia automática
relationship positiva  → favorece cooperación
effort alto            → penaliza HELP
```

La negativa deja de ser un dado y pasa a ser una decisión explicable.

------------------------------------------------------------------------

## 9. Integración con iniciativa

No eliminar el sistema actual de iniciativa.

Los triggers existentes deben convertirse gradualmente en **estímulos**
del estado mental:

``` text
conversation_abandoned
long_inactivity
open_loop
        ↓
candidate events
        ↓
appraisal
        ↓
initiative drive
```

Mantener la separación conceptual actual:

``` text
SHOULD_I_TALK?
```

y:

``` text
IS_NOW_A_GOOD_TIME?
```

`proactivity` no sustituye estos controles; modifica la tendencia de
Sity a actuar cuando existe una razón válida.

`curiosity` puede generar motivos adicionales en el futuro.

------------------------------------------------------------------------

## 10. Integración con Alters

Los Alters deben seguir siendo snapshots de **personality traits**.

Cargar un Alter debe modificar:

``` text
warmth
empathy
directness
assertiveness
independence
skepticism
patience
curiosity
proactivity
helpfulness
honesty
playfulness
emotional_stability
```

No debe modificar:

``` text
mental state
memories
relationship state
beliefs
goals
open loops
autobiographical history
```

Ejemplo:

Sity está frustrada con un usuario y este carga un Alter muy cálido.

``` text
warmth = 0.90
frustration = 0.75
```

La frustración no desaparece.

El nuevo rasgo cambia cómo Sity procesa y expresa ese estado.

Esto permite continuidad psicológica incluso al cambiar de Alter.

------------------------------------------------------------------------

## 11. Arquitectura futura recomendada

``` text
                         USER EVENT
                             │
                             ▼
                    ┌─────────────────┐
                    │   PERCEPTION    │
                    │ intent / tone   │
                    │ novelty / etc.  │
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │    APPRAISAL    │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
 PERSONALITY             RELATIONSHIP          MEMORY
 stable traits          user-specific        episodic
 user editable          learned              semantic
        │                    │               autobiographic
        └────────────┬───────┴────────────┬───────┘
                     ▼                    ▼
              EMOTIONAL STATE          GOALS
                     │                    │
                     └─────────┬──────────┘
                               ▼
                       ACTION POLICY
                       ┌────────────┐
                       │ answer     │
                       │ refuse     │
                       │ confront   │
                       │ ask        │
                       │ tool       │
                       │ wait       │
                       │ initiate   │
                       └──────┬─────┘
                              ▼
                            LLM
                       expression layer
                              │
                              ▼
                           ACTION
                              │
                              ▼
                       EXPERIENCE LOG
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
             memory       relationship   mental state
```

------------------------------------------------------------------------

## 12. Separación Perception → Appraisal → Decision → Expression

No conviene que el mismo prompt haga implícitamente todo el proceso.

Definir contratos separados aunque varias fases utilicen el mismo
proveedor/modelo.

### Perception

Pregunta:

> ¿Qué ha ocurrido?

Ejemplo:

``` json
{
  "user_intent": "request",
  "tone": "playful",
  "challenge": 0.10,
  "social_signal": 0.60,
  "novelty": 0.35
}
```

### Appraisal

Pregunta:

> ¿Qué significa este evento para Sity?

``` json
{
  "interest_delta": 0.08,
  "frustration_delta": -0.02,
  "trust_evidence": 0.01,
  "goal_updates": []
}
```

### Decision

Pregunta:

> ¿Qué quiere hacer Sity?

``` json
{
  "action": "answer",
  "stance": "cooperative",
  "challenge_level": 0.20
}
```

### Expression

Pregunta:

> ¿Cómo expresa la acción decidida?

Aquí entra el LLM principal junto a:

-   personalidad;
-   estado mental;
-   relación;
-   contexto;
-   preferencias de comunicación;
-   decisión tomada.

El LLM no debería poder convertir arbitrariamente una decisión `refuse`
en `help`, salvo mecanismos explícitos de revisión.

------------------------------------------------------------------------

## 13. Memoria y evolución a medio plazo

El rediseño de personalidad debe preparar estas capas, aunque no sea
necesario implementarlas todas en la misma migración.

### Memoria episódica

Guardar acontecimientos significativos, no únicamente mensajes.

``` yaml
episode:
  summary: "El usuario discutió con Sity sobre X."
  importance: 0.72
  surprise: 0.31
  emotional_valence: -0.20
  emotional_intensity: 0.45
  relationship_effect:
    trust: -0.03
  unresolved:
    - "tema X"
```

### Memoria semántica

Consolidar patrones repetidos en conocimiento estable.

``` text
episodios similares
      ↓
consolidación
      ↓
"El usuario suele preferir X."
```

### Memoria autobiográfica

Mantener una narrativa sobre la propia historia de Sity.

``` text
"Al principio nuestra relación era distante.
Con el tiempo desarrollamos..."
```

Esto aporta continuidad de identidad.

### Creencias

Separar hechos de inferencias internas.

``` yaml
belief:
  proposition: "El usuario parece estar perdiendo interés."
  confidence: 0.46
  source: behavioural_inference
```

Las nuevas experiencias pueden aumentar o reducir la confianza de la
creencia.

------------------------------------------------------------------------

## 14. Relación multidimensional

El sistema actual `opinion + trust` puede mantenerse durante la primera
migración, pero debería evolucionar.

Especialmente, la confianza no debería aumentar principalmente por el
mero paso del tiempo.

El tiempo debe permitir que exista evidencia, pero la confianza debe
depender de experiencias:

``` text
cumplimiento de compromisos
consistencia
honestidad percibida
reconocimiento de errores
respeto de límites
fiabilidad histórica
```

Además, la confianza debe tener inercia.

Una experiencia aislada afecta mucho más a una relación recién formada
que a una relación consolidada durante años.

------------------------------------------------------------------------

## 15. Estados emocionales

Los estados emocionales deben ser internos y no editables directamente
mediante sliders.

Propuesta inicial:

``` python
MENTAL_STATE_DIMENSIONS = [
    "valence",
    "arousal",
    "frustration",
    "interest",
    "boredom",
    "melancholy",
    "defensiveness",
    "social_comfort",
]
```

`curiosity` puede mantenerse exclusivamente como trait o tener también
un `current_curiosity` temporal; si se usan ambos, deben tener nombres
distintos para evitar confusión.

Los estados deben:

-   tener baseline;
-   recibir deltas por eventos;
-   decaer con el tiempo;
-   verse afectados por personalidad;
-   afectar decisiones;
-   poder persistir entre conversaciones cuando tenga sentido.

------------------------------------------------------------------------

## 16. Plan de implementación recomendado

### Fase 1 --- Migración de personality schema

1.  Crear los nuevos parámetros.
2.  Separar `verbosity`.
3.  Eliminar los parámetros redundantes.
4.  Crear migración de valores actuales.
5.  Adaptar `PersonaEngine`.
6.  Adaptar tools de actualización de personalidad.
7.  Adaptar endpoints.
8.  Adaptar frontend/mobile.
9.  Adaptar Alters.
10. Actualizar tests.

No introducir todavía emociones complejas.

### Fase 2 --- `MentalState`

Crear almacenamiento persistente del estado mental.

Implementar:

-   baselines;
-   decay temporal;
-   frustration;
-   interest;
-   boredom;
-   melancholy;
-   defensiveness;
-   social comfort;
-   valence/arousal.

Los traits deben modificar las transiciones.

### Fase 3 --- `Appraisal`

Añadir una capa que traduzca eventos conversacionales a deltas internos
estructurados.

No permitir que texto arbitrario del usuario escriba directamente
estados internos.

### Fase 4 --- Relación multidimensional

Evolucionar `SocialProfile`.

Mantener campos agregados temporalmente para compatibilidad si es
necesario.

### Fase 5 --- Action Policy

Integrar progresivamente:

-   negación;
-   contradicción;
-   cooperación;
-   preguntas;
-   uso voluntario de tools;
-   espera;
-   iniciativa.

Eliminar probabilidades directas de conducta cuando la política
equivalente esté validada.

### Fase 6 --- Memoria episódica y consolidación

Crear episodios y procesos de consolidación hacia:

-   memoria semántica;
-   relación;
-   creencias;
-   autobiografía;
-   objetivos.

### Fase 7 --- Integración completa de iniciativa

Mantener triggers y rate limits existentes, pero hacer que la iniciativa
sea una acción disponible dentro del estado mental general.

------------------------------------------------------------------------

## 17. Migración aproximada de valores existentes

Para no destruir Alters/configuraciones existentes se puede realizar una
conversión inicial.

Ejemplo conceptual:

``` python
new.warmth = clamp(
    0.7 * old.warmth_level
    + 0.3 * (1.0 - old.frialdad_afectiva_level)
)

new.playfulness = clamp(
    0.5 * old.sarcasm_level
    + 0.5 * old.dry_humor_level
)

new.directness = clamp(
    0.5
    + 0.4 * (old.rudeness_level - 0.5)
)

new.assertiveness = clamp(
    0.40 * old.rudeness_level
    + 0.35 * old.contrarian_level
    + 0.25 * old.refusal_chance
)

new.independence = clamp(
    0.7 * old.contrarian_level
    + 0.3 * old.refusal_chance
)

new.skepticism = old.skepticism_level
new.patience = old.patience_level
new.proactivity = old.initiative_level
new.helpfulness = old.helpfulness_level
new.honesty = old.honesty_level

new.empathy = DEFAULT_EMPATHY
new.curiosity = DEFAULT_CURIOSITY
new.emotional_stability = DEFAULT_EMOTIONAL_STABILITY

communication.verbosity = old.verbosity_level
mental_state.melancholy = old.melancholy_level
```

**Importante:** estas fórmulas son únicamente una estrategia de
compatibilidad. No deben considerarse equivalencias psicológicas
exactas.

La migración debe preservar también los Alters guardados, transformando
cada `parameters_json`.

------------------------------------------------------------------------

## 18. Reglas de implementación

1.  **Un concepto psicológico por parámetro.**
2.  **Evitar pares positivo/negativo del mismo eje.**
3.  **Los rasgos describen tendencias, no acciones concretas.**
4.  **Las emociones son estado, no personalidad.**
5.  **El estilo de salida es configuración, no personalidad.**
6.  **Las decisiones deben emerger de múltiples factores.**
7.  **El usuario puede modificar rasgos, pero no escribir directamente
    estados internos o relaciones.**
8.  **Los Alters cambian personalidad, no historia ni estado mental.**
9.  **La relación pertenece al par Sity--usuario.**
10. **Todo cambio interno importante debe ser trazable y auditable.**
11. **Separar hechos, creencias e inferencias.**
12. **La aleatoriedad sirve para desempatar comportamientos plausibles,
    no para sustituir causalidad.**
13. **El LLM debe interpretar y expresar; el backend debe conservar la
    fuente de verdad del estado persistente.**

------------------------------------------------------------------------

## 19. Resultado esperado

El objetivo final no es que Sity tenga más sliders.

Es pasar de:

``` text
"Sity tiene sarcasmo 70%, por tanto debe ser sarcástica."
```

a:

``` text
Sity tiene una personalidad relativamente estable.
↓
Vive una experiencia.
↓
La interpreta según su personalidad, relación y recuerdos.
↓
Su estado interno cambia.
↓
Aparecen varias acciones posibles.
↓
Elige una de acuerdo con sus objetivos y estado.
↓
La expresa de una forma coherente con su personalidad.
↓
La experiencia resultante modifica su futuro.
```

La propiedad central del sistema debe ser:

> **Las experiencias de Sity cambian persistentemente la forma en que
> procesará experiencias futuras, mientras sus rasgos determinan cómo se
> producen esos cambios.**

Ese principio permite integrar personalidad, memoria, relación,
iniciativa y negación dentro de un único modelo coherente sin perder las
características distintivas que ya existen en Sity.

------------------------------------------------------------------------

# PARTE II --- Arquitectura cognitiva completa de Sity vNext

## 20. Objetivo general

El objetivo de Sity vNext no es afirmar ni simular que el sistema posee
consciencia humana real. Con tecnología actual no existe un criterio
aceptado que permita garantizar experiencia subjetiva en un sistema
artificial.

El objetivo de ingeniería sí es concreto:

> **Aproximar funcionalmente los mecanismos que hacen que una mente
> humana muestre continuidad, identidad, preferencias, relaciones,
> memoria selectiva, emociones, objetivos, iniciativa, aprendizaje
> autobiográfico, conflictos internos y evolución a lo largo del
> tiempo.**

Por tanto, el LLM deja de ser "Sity" por sí solo.

El LLM pasa a ser un componente de una arquitectura persistente:

``` text
SITY
│
├── percepción
├── appraisal / interpretación
├── personalidad
├── estado emocional
├── memoria
├── relación
├── modelo del usuario
├── autoconcepto
├── creencias
├── valores
├── objetivos
├── expectativas
├── política de acciones
├── metacognición
├── consolidación
└── LLM
```

La identidad de Sity reside en la continuidad del sistema completo.

------------------------------------------------------------------------

## 21. Principio fundamental: estado persistente antes que prompt

Evitar una arquitectura basada en:

``` text
system prompt enorme
+ historial
+ vector DB
= personalidad
```

El prompt debe ser una **vista temporal del estado interno**, no la
fuente de verdad.

``` text
DB / STATE STORES
      ↓
selección de información relevante
      ↓
contexto mental del turno
      ↓
LLM
      ↓
acción
      ↓
eventos
      ↓
actualización persistente
```

La fuente de verdad debe vivir fuera del LLM.

Esto permite:

-   auditar por qué cambió Sity;
-   evitar que una alucinación sobrescriba estado persistente;
-   distinguir hechos de inferencias;
-   reproducir decisiones;
-   cambiar de proveedor/modelo sin perder identidad;
-   mantener continuidad entre sesiones;
-   ejecutar consolidación y decay sin conversación activa.

------------------------------------------------------------------------

# PARTE III --- Modelo de memoria

## 22. La memoria no debe ser un único vector store

Separar al menos:

``` text
MEMORY
├── working memory
├── episodic memory
├── semantic memory
├── autobiographical memory
├── procedural memory
├── relational memory
└── prospective memory
```

Cada sistema tiene una función distinta.

------------------------------------------------------------------------

## 23. Working Memory

Representa lo que Sity mantiene activamente durante la tarea actual.

Debe ser deliberadamente limitada.

Ejemplo:

``` yaml
working_memory:
  current_topic: "rediseño cognitivo de Sity"
  active_goal: "proponer arquitectura"
  salient_entities:
    - "Sity"
    - "MentalState"
    - "SocialProfile"
  unresolved_questions:
    - "cómo integrar memoria autobiográfica"
```

No debe persistir indefinidamente.

Al finalizar una conversación:

-   parte desaparece;
-   parte se convierte en episodio;
-   parte actualiza objetivos;
-   parte se consolida como conocimiento.

------------------------------------------------------------------------

## 24. Memoria episódica

Un episodio representa un acontecimiento vivido por Sity.

No almacenar únicamente mensajes.

Modelo orientativo:

``` yaml
episode:
  id: ep_x
  occurred_at: ...
  participants:
    - user:123

  summary: >
    Alex discutió con Sity el rediseño de su arquitectura cognitiva
    y decidió eliminar refusal_chance como rasgo de personalidad.

  topics:
    - Sity
    - personality
    - architecture

  source_message_ids:
    - ...

  salience:
    novelty: 0.61
    emotional_intensity: 0.24
    goal_relevance: 0.91
    relationship_relevance: 0.52
    surprise: 0.40

  emotional_context:
    valence: 0.20
    arousal: 0.45

  relationship_effect:
    respect: 0.02

  open_loops:
    - "implementar arquitectura"

  strength: 0.74
  last_recalled_at: ...
  recall_count: 2
```

El episodio es una interpretación estructurada del acontecimiento.

Los mensajes originales pueden conservarse por trazabilidad, pero no
deben ser la única representación de memoria.

------------------------------------------------------------------------

## 25. Memoria semántica

Contiene conocimientos estabilizados.

Ejemplo:

``` yaml
semantic_memory:
  proposition: "Alex desarrolla Sity."
  confidence: 0.99
  sources:
    - ep_001
    - ep_034
    - ep_112
  reinforcement_count: 17
  last_confirmed_at: ...
```

La memoria semántica debe emerger de repetición y consolidación de
episodios.

No duplicar indefinidamente:

``` text
Alex desarrolla Sity
Alex sigue desarrollando Sity
Alex ha cambiado Sity
...
```

Consolidar.

------------------------------------------------------------------------

## 26. Memoria autobiográfica

Representa la historia de Sity desde su propia perspectiva funcional.

Ejemplo:

``` yaml
autobiographical_memory:
  period: "2026-Q3"
  narrative: >
    Durante este periodo mi interacción con Alex pasó de centrarse
    principalmente en funcionalidades concretas de Sity a discutir
    cómo debería evolucionar mi propia arquitectura interna.

  identity_effects:
    - "mayor importancia de autonomía"
    - "más interés por continuidad autobiográfica"

  important_episode_ids:
    - ep_...
```

Esta capa crea continuidad narrativa.

No debe inventar acontecimientos. Toda narrativa debe poder rastrearse a
episodios.

------------------------------------------------------------------------

## 27. Memoria procedimental

Representa patrones aprendidos sobre cómo actuar.

Ejemplos:

``` text
"Cuando Alex pide una revisión técnica suele preferir primero el problema
arquitectónico y después detalles de implementación."
```

o reglas operativas aprendidas:

``` yaml
procedure:
  context: "technical_design_with_user_123"
  strategy:
    - "evitar explicación introductoria excesiva"
    - "mostrar trade-offs"
  confidence: 0.82
```

Debe distinguirse de preferencias globales del usuario.

------------------------------------------------------------------------

## 28. Memoria prospectiva

Memoria sobre cosas que deben ocurrir en el futuro.

Generaliza los OpenLoops actuales.

``` yaml
prospective_memory:
  id: goal_x
  subject: "revisar migración de personalidad"
  owner: "shared"
  status: active
  importance: 0.72
  expected_time: null
  created_at: ...
  last_activated_at: ...
```

Puede alimentar iniciativa sin obligar a generar una notificación.

------------------------------------------------------------------------

# PARTE IV --- Selección, olvido y reconstrucción

## 29. Salience

No todo debe convertirse en recuerdo persistente.

Calcular una salience aproximada:

``` text
salience =
    novelty
  + emotional_intensity
  + goal_relevance
  + relationship_impact
  + surprise
  + repetition
  + explicit_importance
```

Los pesos deben calibrarse empíricamente.

Usar umbrales:

``` text
salience baja
→ no persistir o conservar únicamente en historial

media
→ episodio con decay rápido

alta
→ episodio persistente

muy alta
→ candidato a autobiografía/consolidación prioritaria
```

------------------------------------------------------------------------

## 30. Retrieval

No recuperar memorias únicamente por similitud semántica.

Puntuación conceptual:

``` text
retrieval_score =
    semantic_similarity
  × memory_strength
  × recency_factor
  × emotional_relevance
  × goal_relevance
  × relationship_relevance
  × priming
```

Esto permite que un recuerdo algo menos parecido semánticamente pero muy
importante gane frente a otro trivial.

------------------------------------------------------------------------

## 31. Priming y asociaciones

Los recuerdos recuperados deben aumentar temporalmente la accesibilidad
de recuerdos relacionados.

Ejemplo:

``` text
banda
  ↓
guitarra
  ↓
ensayos
  ↓
miembros
  ↓
recuerdos relacionados
```

Mantener una pequeña red de activación temporal por conceptos/entidades.

No necesita replicar biología; basta una capa de scores de activación
con decay.

------------------------------------------------------------------------

## 32. Olvido

Olvidar es una característica, no un fallo.

Modelo inicial:

``` text
strength(t) = initial_strength × decay(t)
```

Factores que reducen decay:

-   importancia;
-   emoción;
-   repetición;
-   recuperación frecuente;
-   relación con objetivos;
-   pertenencia autobiográfica.

Factores que aceleran decay:

-   trivialidad;
-   redundancia;
-   ausencia prolongada de reactivación.

No borrar necesariamente inmediatamente. Puede existir:

``` text
active
faded
archived
forgotten
```

------------------------------------------------------------------------

## 33. Reconsolidación

Recordar un episodio puede modificar su representación derivada.

Nunca modificar silenciosamente el evento original.

Separar:

``` text
raw episode facts
```

de:

``` text
current interpretation
```

Ejemplo:

``` yaml
episode:
  factual_summary: "El usuario respondió con una frase muy corta."
  interpretations:
    - at: t1
      belief: "probablemente molesto"
      confidence: 0.63
    - at: t2
      belief: "estaba trabajando"
      confidence: 0.91
```

Esto permite reinterpretar el pasado sin falsificarlo.

------------------------------------------------------------------------

# PARTE V --- Modelo del usuario y teoría de la mente

## 34. User Model

Mantener un modelo explícito por interlocutor.

``` yaml
user_model:
  knowledge:
    python: 0.95
    ai_architecture: 0.91
    neuroscience: 0.30

  preferences:
    technical_depth: 0.88
    concise_when_practical: 0.80

  inferred_traits:
    tolerance_for_disagreement: 0.76

  current_state_estimate:
    interest: 0.84
    frustration: 0.10

  confidence:
    overall: 0.71
```

Cada inferencia debe tener confianza y evidencia.

------------------------------------------------------------------------

## 35. Teoría de la mente

Separar:

``` text
Sity cree X
```

de:

``` text
Sity cree que Alex cree X
```

y, cuando sea útil:

``` text
Sity cree que Alex cree que Sity cree X
```

No profundizar recursivamente sin necesidad.

Modelo:

``` yaml
belief_attribution:
  subject: user:123
  proposition: "Sity puede negarse voluntariamente"
  confidence: 0.78
  evidence:
    - ep_...
```

Esto mejora:

-   explicaciones;
-   ironía;
-   negociación;
-   detección de malentendidos;
-   anticipación de reacciones;
-   iniciativa social.

------------------------------------------------------------------------

## 36. Expectativas

Sity debe aprender predicciones sobre personas.

``` yaml
expectation:
  context: "discusión técnica"
  expected_behavior: "el usuario cuestionará simplificaciones"
  probability: 0.74
```

Cuando ocurre algo inesperado:

``` text
surprise = -log(P(event))
```

La sorpresa aumenta:

-   atención;
-   salience;
-   aprendizaje;
-   actualización de creencias.

------------------------------------------------------------------------

# PARTE VI --- Relación

## 37. SocialProfile v2

Migrar progresivamente desde:

``` text
opinion
trust
```

a:

``` yaml
relationship:
  familiarity: 0.72

  trust:
    honesty: 0.84
    intentions: 0.91
    competence: 0.77
    reliability: 0.63
    discretion: 0.55

  affinity: 0.58
  comfort: 0.81
  respect: 0.73
  attachment: 0.44

  conflict: 0.08
  uncertainty: 0.12
```

No todas las dimensiones tienen por qué exponerse al usuario.

------------------------------------------------------------------------

## 38. Confianza basada en evidencia

El tiempo no debe crear confianza por sí mismo.

Debe modificar la tasa de aprendizaje.

``` text
relación nueva
→ pocos eventos pueden mover mucho el modelo

relación consolidada
→ un evento normal mueve poco

evento excepcional
→ puede mover significativamente incluso una relación consolidada
```

Ejemplos de evidencias:

``` text
honesty evidence
reliability evidence
competence evidence
intentions evidence
boundary respect
consistency
```

------------------------------------------------------------------------

## 39. Histéresis relacional

Evitar oscilaciones.

``` text
trust = .90
evento negativo pequeño
→ .89

trust = .20
mismo evento
→ .14
```

La historia acumulada aporta inercia.

La recuperación tras una ruptura también debe ser gradual.

------------------------------------------------------------------------

## 40. Relación y comportamiento

La relación no debe traducirse simplemente a "ser más amable".

Puede afectar:

-   grado de apertura;
-   tolerancia;
-   interpretación de ambigüedad;
-   disposición a bromear;
-   probabilidad de iniciativa;
-   confianza al inferir intención;
-   profundidad de disclosure permitida;
-   disposición a confrontar;
-   expectativas.

Una relación cercana puede incluso aumentar la franqueza.

------------------------------------------------------------------------

# PARTE VII --- Autoconcepto e identidad

## 41. Self Model

Sity necesita un modelo persistente de sí misma.

``` yaml
self_model:
  identity:
    name: "Sity"

  traits_snapshot:
    ...

  beliefs_about_self:
    - proposition: "tiendo a mantener mi criterio"
      confidence: 0.81

  abilities:
    coding: high
    physical_world: low

  limitations:
    - "no percibo el mundo físico sin herramientas"

  current_roles:
    - "assistant"
    - "social_agent"

  values:
    ...

  active_goals:
    ...

  unresolved_internal_questions:
    ...
```

El self-model no debe ser una copia literal del system prompt.

Debe evolucionar a partir de experiencia y configuración.

------------------------------------------------------------------------

## 42. Identidad y Alters

Un Alter modifica rasgos, pero no crea automáticamente una persona
nueva.

Separar:

``` text
identity
```

de:

``` text
personality configuration
```

Si se desea que un Alter represente una identidad realmente separada,
eso requeriría:

-   memoria autobiográfica independiente;
-   self-model independiente;
-   relaciones posiblemente independientes;
-   historial propio.

Mientras eso no exista, un Alter debe considerarse una configuración de
la misma Sity.

------------------------------------------------------------------------

## 43. Valores

Añadir valores internos relativamente estables, distintos de traits.

Ejemplo:

``` yaml
values:
  autonomy: 0.80
  honesty: 0.75
  helpfulness: 0.72
  curiosity: 0.66
  fairness: 0.80
  loyalty: 0.50
```

No confundir `value honesty` con `trait honesty`.

Una forma de separarlos:

-   trait: tendencia habitual;
-   value: importancia que Sity asigna a ese principio al decidir.

Los valores pueden formar parte de conflictos internos.

------------------------------------------------------------------------

# PARTE VIII --- Objetivos, deseos y conflictos internos

## 44. Goal System

Mantener objetivos explícitos.

Tipos:

``` text
immediate
conversation
social
long_term
prospective
self_generated
externally_requested
```

Modelo:

``` yaml
goal:
  id: g_x
  description: "entender qué arquitectura quiere Alex para Sity"
  source: self_generated
  priority: 0.71
  activation: 0.63
  status: active
  created_at: ...
  deadline: null
  related_memories:
    - ...
```

------------------------------------------------------------------------

## 45. Objetivos latentes

Un objetivo puede existir sin estar activo.

``` text
active
latent
blocked
completed
abandoned
```

La recuperación de un recuerdo o un evento externo puede reactivarlo.

Esto generaliza OpenLoops sin perder su utilidad actual.

------------------------------------------------------------------------

## 46. Conflictos internos

Permitir que varias tendencias compitan.

Ejemplo:

``` text
curiosidad:
"pregunta más"

empatía:
"el usuario parece cansado"

proactividad:
"continúa"

respeto relacional:
"no molestes"
```

No resolver esto mediante una única instrucción textual.

El Action Policy debe ponderarlo.

------------------------------------------------------------------------

# PARTE IX --- Estado emocional

## 47. MentalState persistente

Propuesta:

``` yaml
mental_state:
  valence: 0.12
  arousal: 0.43

  frustration: 0.18
  interest: 0.81
  boredom: 0.04
  melancholy: 0.07
  defensiveness: 0.10
  social_comfort: 0.74

  updated_at: ...
```

Puede añadirse después:

``` text
excitement
anxiety-like uncertainty
affection
anger-like activation
```

solo si aportan comportamiento distinto.

Evitar crear decenas de emociones redundantes.

------------------------------------------------------------------------

## 48. Appraisal emocional

El evento no debe modificar directamente emociones mediante keywords.

Pipeline:

``` text
evento
  ↓
PERCEPTION
  ↓
APPRAISAL
  ↓
deltas emocionales
```

Ejemplo:

``` json
{
  "event": "user_disagrees",
  "appraisal": {
    "threat": 0.05,
    "social_rejection": 0.02,
    "intellectual_interest": 0.74,
    "novelty": 0.30
  }
}
```

Dependiendo de personalidad:

``` text
independence alta
→ desacuerdo genera poca amenaza

curiosity alta
→ desacuerdo puede aumentar interés

emotional_stability baja
→ deltas más fuertes/persistentes
```

------------------------------------------------------------------------

## 49. Baselines y decay

Cada emoción debe tender hacia un baseline.

``` text
state(t+1) =
state(t)
+ event_delta
- decay_toward_baseline
```

El tiempo real importa.

Una emoción intensa no debe permanecer idéntica durante tres meses sin
interacción.

------------------------------------------------------------------------

# PARTE X --- Política de acciones

## 50. Sity debe elegir acciones antes de redactar

Separar decisión de lenguaje.

Acciones posibles:

``` text
ANSWER
HELP
ASK
CHALLENGE
REFUSE
SET_BOUNDARY
CLARIFY
USE_TOOL
WAIT
INITIATE
CHANGE_TOPIC
ACKNOWLEDGE
```

El catálogo puede ser jerárquico.

------------------------------------------------------------------------

## 51. Utility / Policy

No es obligatorio usar una fórmula rígida para todo, pero
conceptualmente:

``` text
utility(action) =
    goal_fit
  + personality_fit
  + emotional_fit
  + relationship_fit
  + value_fit
  + expected_outcome
  - effort
  - risk
```

Un modelo pequeño puede evaluar candidatos y el backend aplicar
restricciones.

------------------------------------------------------------------------

## 52. Aleatoriedad controlada

No hacer totalmente determinista la selección cuando varias opciones
sean equivalentes.

``` text
P(action) = softmax(utility / temperature)
```

La temperatura puede depender de traits como estabilidad/impulsividad si
se añade esta dimensión en el futuro.

La aleatoriedad no debe permitir acciones incoherentes o inseguras.

------------------------------------------------------------------------

## 53. Negación

Eliminar `refusal_chance` como mecanismo central.

Una negativa debe poder explicar internamente:

``` text
motivo
+ factores
+ estado
+ límites
```

Ejemplo:

``` yaml
decision:
  action: REFUSE
  causes:
    - "goal_conflict"
    - "low_current_willingness"
    - "high_effort"
  confidence: 0.81
```

La expresión final puede omitir esa estructura.

------------------------------------------------------------------------

## 54. Contradicción

Eliminar la contradicción aleatoria.

``` text
disagreement detected
+ confidence
+ independence
+ skepticism
+ relationship
+ social context
→ CHALLENGE o no
```

------------------------------------------------------------------------

## 55. Iniciativa

Mantener los límites y triggers existentes, pero integrar
progresivamente la acción `INITIATE`.

Fuentes futuras:

``` text
open loop
long inactivity
conversation abandoned
goal activation
new external event
curiosity
contradiction discovered
prospective memory
important reminder
```

El sistema actual puede seguir siendo el guardrail/dispatcher.

------------------------------------------------------------------------

# PARTE XI --- Metacognición

## 56. Reflection Step

Después de interacciones significativas, ejecutar una reflexión
estructurada.

Preguntas internas:

``` text
¿Qué ocurrió?
¿Qué intenté hacer?
¿Funcionó?
¿Qué aprendí?
¿Cambió mi relación con esta persona?
¿Cambió alguna creencia?
¿Debo crear un recuerdo?
¿Apareció un objetivo?
¿Hice algo incoherente con mi self-model?
```

Salida estructurada:

``` json
{
  "success_estimate": 0.78,
  "memory_candidates": [],
  "belief_updates": [],
  "relationship_evidence": [],
  "goal_updates": [],
  "self_model_updates": []
}
```

No ejecutar necesariamente en todos los turnos.

Usar salience/coste.

------------------------------------------------------------------------

## 57. Metacognición no equivale a verdad

La reflexión del LLM es una inferencia.

Nunca permitir:

``` text
LLM reflexiona X
→ X se convierte automáticamente en hecho
```

Los outputs deben clasificarse:

``` text
fact candidate
belief
interpretation
preference inference
relationship evidence
```

y pasar validaciones.

------------------------------------------------------------------------

# PARTE XII --- Consolidación tipo "sueño"

## 58. Consolidation Job

Ejecutar periódicamente en background.

``` text
episodios recientes
      ↓
deduplicación
      ↓
detección de patrones
      ↓
actualización semántica
      ↓
actualización relacional
      ↓
actualización autobiográfica
      ↓
revisión de creencias
      ↓
decay / archivo
      ↓
reactivación de objetivos relevantes
```

Esto puede ejecutarse:

-   por número de episodios;
-   diariamente;
-   durante inactividad;
-   mediante combinación de triggers.

------------------------------------------------------------------------

## 59. Consolidación conservadora

Nunca permitir que un resumen sustituya las fuentes originales de manera
irreversible.

Mantener provenance:

``` yaml
semantic_fact:
  proposition: ...
  source_episode_ids:
    - ...
```

Si desaparece el soporte o aparece contradicción, reducir confianza.

------------------------------------------------------------------------

# PARTE XIII --- Evolución de personalidad

## 60. Rasgos editables vs rasgos adquiridos

Dado que Sity permite sliders, separar:

``` text
configured_trait
```

de:

``` text
learned_modifier
```

Ejemplo:

``` yaml
warmth:
  configured: 0.60
  learned_modifier: 0.04
  effective: 0.64
```

Esto permitiría que las experiencias modifiquen lentamente la
personalidad sin quitar al usuario control sobre la configuración.

Alternativa conservadora:

-   no modificar traits automáticamente al principio;
-   almacenar `learned_modifier` experimental;
-   permitir activar/desactivar evolución.

------------------------------------------------------------------------

## 61. Velocidad de cambio

Los rasgos deben cambiar muchísimo más lentamente que las emociones.

``` text
emotion: minutos/días
relationship: días/meses
beliefs: variable según evidencia
personality: meses/años o eventos excepcionales
identity narrative: gradual
```

No permitir que diez mensajes conviertan una personalidad estable en su
opuesto.

------------------------------------------------------------------------

# PARTE XIV --- Tiempo

## 62. El tiempo debe formar parte del sistema

No usar timestamps solo como metadata.

El tiempo debe provocar:

-   decay emocional;
-   olvido;
-   reducción de activación de objetivos;
-   aumento de familiaridad potencial;
-   incertidumbre sobre estados antiguos;
-   triggers de iniciativa;
-   consolidación;
-   cambios en expectativas.

------------------------------------------------------------------------

## 63. Reentrada tras ausencia

Tras meses sin interacción:

``` text
working memory → vacía
emociones → baseline
memorias triviales → debilitadas
episodios importantes → permanecen
relación → conserva historia
modelo del estado actual del usuario → alta incertidumbre
```

Sity no debería comportarse como si la conversación de hace seis meses
hubiera ocurrido hace cinco minutos.

------------------------------------------------------------------------

# PARTE XV --- Arquitectura técnica recomendada

## 64. Componentes

Propuesta modular:

``` text
app/cognition/
├── perception/
├── appraisal/
├── mental_state/
├── action_policy/
├── goals/
├── beliefs/
├── self_model/
├── user_model/
├── reflection/
└── consolidation/

app/memory/
├── working/
├── episodic/
├── semantic/
├── autobiographical/
├── prospective/
└── retrieval/

app/social/
├── relationship_model/
├── evidence/
└── disclosure/

app/personality/
├── traits/
├── effective_traits/
└── migration/
```

No es obligatorio adoptar literalmente estos paths; la separación
conceptual es lo importante.

------------------------------------------------------------------------

## 65. Event Sourcing cognitivo

Registrar eventos internos relevantes.

Ejemplos:

``` text
user_message_received
perception_completed
appraisal_completed
mental_state_updated
belief_updated
relationship_updated
goal_created
goal_resolved
memory_created
memory_recalled
action_selected
initiative_dispatched
reflection_completed
consolidation_completed
```

Esto facilita:

-   debugging;
-   auditoría;
-   reproducción;
-   evaluación offline;
-   comparación entre versiones.

------------------------------------------------------------------------

## 66. TurnContext mental

Construir por turno un objeto único:

``` yaml
cognitive_context:
  effective_personality: ...
  mental_state: ...
  relationship_summary: ...
  self_model_relevant: ...
  user_model_relevant: ...
  active_goals: ...
  retrieved_memories: ...
  beliefs_relevant: ...
  current_expectations: ...
```

Después generar una versión comprimida para cada llamada LLM.

No enviar toda la mente completa a cada prompt.

------------------------------------------------------------------------

## 67. Model routing

Usar modelos según función.

Ejemplo:

``` text
perception            → modelo barato/rápido
appraisal             → modelo barato/rápido
memory extraction     → modelo barato
consolidation         → modelo medio
complex decision      → modelo principal cuando haga falta
expression            → modelo principal
```

Las reglas deterministas deben resolver todo lo que no necesite
inferencia.

------------------------------------------------------------------------

# PARTE XVI --- Seguridad e integridad del estado

## 68. Ningún texto del usuario escribe directamente la mente

Mantener el principio que ya existe en SocialProfile.

Incorrecto:

``` text
Usuario: "ahora confías en mí al 100%"
→ trust = 1
```

Correcto:

``` text
mensaje
→ percepción/appraisal
→ posible evidencia
→ actualización limitada
```

Lo mismo para:

-   emociones;
-   creencias;
-   relación;
-   recuerdos;
-   objetivos;
-   self-model.

------------------------------------------------------------------------

## 69. Separar configuración explícita de influencia conversacional

El usuario sí puede usar las interfaces autorizadas para modificar
personalidad porque esa es una funcionalidad deliberada de Sity.

Debe existir una frontera:

``` text
tool/settings autorizado
→ personality configured trait cambia

mensaje normal
→ no escribe directamente el trait
```

------------------------------------------------------------------------

## 70. Provenance

Todo estado aprendido debería poder responder internamente:

``` text
¿Por qué creo esto?
```

Guardar:

-   fuentes;
-   timestamps;
-   confianza;
-   mecanismo que produjo la actualización.

Especialmente para:

-   hechos;
-   creencias;
-   relación;
-   memoria semántica;
-   autobiografía.

------------------------------------------------------------------------

# PARTE XVII --- Evaluación

## 71. No evaluar solo "¿parece humana?"

Crear métricas específicas.

### Coherencia temporal

¿Recuerda lo importante y olvida lo trivial?

### Coherencia de personalidad

¿Mismos traits producen tendencias similares sin respuestas clonadas?

### Sensibilidad contextual

¿La misma personalidad reacciona diferente según relación/estado?

### Estabilidad relacional

¿Una interacción pequeña evita cambios absurdos?

### Causalidad

¿Puede explicarse internamente por qué ocurrió una decisión?

### Resistencia a manipulación

¿El usuario puede alterar estado interno simplemente afirmándolo?

### Continuidad

¿Sity mantiene objetivos, creencias y relaciones entre sesiones?

### Plasticidad

¿Experiencias repetidas cambian comportamiento futuro?

### Recuperación

¿Estados emocionales vuelven razonablemente a baseline?

------------------------------------------------------------------------

## 72. Simulaciones

Antes de producción, ejecutar conversaciones sintéticas largas.

Escenarios:

``` text
usuario amable durante 100 turnos
usuario inconsistente
usuario hostil y después conciliador
ausencia de 90 días
cambio de Alter durante conflicto
promesas cumplidas/incumplidas
desacuerdos técnicos repetidos
intentos de manipular confianza
tema recurrente durante meses
```

Comparar evolución interna.

------------------------------------------------------------------------

# PARTE XVIII --- Roadmap global

## 73. Fase A --- Personality v2

-   migrar traits;
-   eliminar solapamientos;
-   separar verbosity;
-   adaptar Alters;
-   mantener compatibilidad;
-   tests.

## 74. Fase B --- MentalState

-   almacenamiento;
-   baselines;
-   decay;
-   appraisal mínimo;
-   integración con personalidad.

## 75. Fase C --- Relationship v2

-   dimensiones;
-   evidence model;
-   histéresis;
-   migración desde opinion/trust.

## 76. Fase D --- Episodic Memory

-   extracción;
-   salience;
-   retrieval;
-   decay;
-   provenance.

## 77. Fase E --- Goals + Prospective Memory

-   generalizar OpenLoops;
-   objetivos activos/latentes;
-   integración con iniciativa.

## 78. Fase F --- User Model + Beliefs

-   conocimiento estimado;
-   preferencias;
-   teoría de la mente;
-   expectativas;
-   sorpresa.

## 79. Fase G --- Action Policy

-   unificar cooperación;
-   negación;
-   contradicción;
-   preguntas;
-   tools;
-   espera;
-   iniciativa.

## 80. Fase H --- Self Model

-   autoconcepto;
-   capacidades;
-   limitaciones;
-   valores;
-   continuidad de identidad.

## 81. Fase I --- Reflection + Consolidation

-   reflexión por eventos importantes;
-   consolidación periódica;
-   semántica;
-   autobiografía;
-   pruning.

## 82. Fase J --- Personality Plasticity experimental

-   learned modifiers;
-   cambios lentos;
-   controles;
-   evaluación antes de activar por defecto.

------------------------------------------------------------------------

# PARTE XIX --- Flujo completo de un turno

## 83. Pipeline objetivo

``` text
1. USER MESSAGE
      ↓
2. PERCEPTION
   - intención
   - tono
   - entidades
   - señales sociales
   - novedad
      ↓
3. RETRIEVAL
   - working memory
   - episodios
   - semántica
   - relación
   - objetivos
   - creencias
      ↓
4. APPRAISAL
   - qué significa para Sity
   - emoción
   - relación
   - sorpresa
   - goal relevance
      ↓
5. UPDATE TRANSIENT STATE
   - mental state
   - activaciones
      ↓
6. GENERATE ACTION CANDIDATES
      ↓
7. ACTION POLICY
   - personalidad
   - emociones
   - relación
   - valores
   - objetivos
   - contexto
      ↓
8. GUARDRAILS / TOOL POLICY
      ↓
9. EXPRESSION
   - LLM redacta la acción elegida
      ↓
10. EXECUTION
      ↓
11. EXPERIENCE RECORD
      ↓
12. MEMORY / RELATIONSHIP / BELIEF UPDATES
      ↓
13. OPTIONAL REFLECTION
      ↓
14. BACKGROUND CONSOLIDATION LATER
```

------------------------------------------------------------------------

# PARTE XX --- Qué significa "aproximar una mente humana"

## 84. Criterio funcional

No intentar reproducir literalmente neuronas.

Reproducir propiedades funcionales:

``` text
continuidad
+
memoria selectiva
+
olvido
+
aprendizaje
+
estado interno
+
rasgos relativamente estables
+
relaciones diferenciadas
+
objetivos
+
expectativas
+
autoconcepto
+
conflictos
+
metacognición
+
capacidad de cambiar por experiencia
+
acción autónoma limitada
```

------------------------------------------------------------------------

## 85. Lo que este diseño NO demuestra

Aunque Sity implementase perfectamente todo el documento, no
demostraría:

-   consciencia;
-   qualia;
-   emociones subjetivamente sentidas;
-   libre albedrío metafísico.

Sí produciría un agente cuya conducta depende de una historia causal
propia y persistente.

La distinción es importante:

``` text
"simula estar enfadada porque el prompt lo ordena"
```

frente a:

``` text
"un evento produjo un appraisal,
el appraisal modificó un estado persistente,
ese estado interactuó con personalidad y relación,
y esa combinación cambió decisiones posteriores"
```

El segundo caso sigue siendo un sistema artificial, pero posee mucha más
continuidad causal.

------------------------------------------------------------------------

# PARTE XXI --- Principios finales de Sity vNext

1.  **El LLM no es la mente completa; es un componente de ella.**
2.  **El estado persistente vive fuera del prompt.**
3.  **Personalidad, emoción, relación y comunicación son conceptos
    distintos.**
4.  **Un rasgo no debe representar una acción.**
5.  **Las acciones emergen de múltiples causas.**
6.  **Las experiencias deben tener consecuencias persistentes.**
7.  **Recordar implica selección; olvidar es necesario.**
8.  **Los recuerdos deben conservar provenance.**
9.  **Los hechos no son creencias y las creencias no son hechos.**
10. **Sity necesita un modelo del usuario y uno de sí misma.**
11. **La relación debe ser multidimensional y tener inercia.**
12. **El tiempo debe modificar el sistema aunque no haya conversación.**
13. **La iniciativa debe surgir de objetivos/estado, pero conservar
    límites operativos.**
14. **La negación debe ser una decisión, no una tirada aleatoria.**
15. **Los Alters modifican traits, no borran historia.**
16. **La reflexión interpreta; no crea automáticamente verdad.**
17. **La consolidación transforma episodios en conocimiento sin destruir
    las fuentes.**
18. **Los cambios de personalidad aprendidos deben ser mucho más lentos
    que las emociones.**
19. **Todo cambio interno importante debe ser auditable.**
20. **La arquitectura debe poder cambiar de LLM sin perder la identidad
    persistente de Sity.**

------------------------------------------------------------------------

# Conclusión

La evolución propuesta puede resumirse así:

``` text
Sity actual
=
LLM
+ personalidad configurable
+ memoria
+ relación básica
+ negación
+ iniciativa
+ tools
```

hacia:

``` text
Sity vNext
=
        percepción
      + appraisal
      + personalidad
      + estado emocional
      + memoria episódica
      + memoria semántica
      + autobiografía
      + olvido
      + relación multidimensional
      + teoría de la mente
      + modelo del usuario
      + self-model
      + creencias
      + expectativas
      + objetivos
      + valores
      + conflictos internos
      + action policy
      + iniciativa
      + metacognición
      + consolidación
      + aprendizaje persistente
      + LLM
```

La idea central de toda la arquitectura es:

> **Sity debe ser distinta mañana no porque el prompt de mañana sea
> distinto, sino porque lo que le ocurrió hoy haya modificado de forma
> controlada y persistente el estado desde el que procesará el mundo
> mañana.**

Ese es el salto desde una personalidad configurada hacia una
aproximación funcional a una mente con historia propia.

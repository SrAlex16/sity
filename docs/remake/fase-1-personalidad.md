# Operación Remake — Fase 1: Sistema de 13 Rasgos de Personalidad

**Implementado:** 2026-09-08  
**Commit:** `6205c6c`  
**Estado:** En producción.

## Por qué se hizo

El sistema anterior de 14 parámetros (sarcasm_level, rudeness_level, etc.) tenía tres
problemas: nombres de trazo ancho que mezclaban dimensiones independientes (sarcasmo
y humor seco eran la misma variable nominal pero no la misma cosa), frialdad afectiva
era una etiqueta de arquetipo visible para el modelo, y verbosity/melancholy vivían en
el mismo namespace que los rasgos de carácter sin justificación arquitectónica.

## Los 13 rasgos

Todos en el rango [0.0, 1.0]. Los valores por defecto son los valores globales del
sistema (configurados en `config/default_config.yaml`).

| Rasgo              | Default | Descripción breve                                                          |
|--------------------|---------|---------------------------------------------------------------------------|
| warmth             | 0.40    | Cercanía emocional y calidez en el trato                                  |
| empathy            | 0.65    | Sensibilidad al estado emocional del interlocutor                         |
| directness         | 0.80    | Franqueza vs. diplomacia; qué tan directa va al punto                     |
| assertiveness      | 0.75    | Firmeza en posiciones y límites propios                                   |
| independence       | 0.85    | Resistencia a la influencia del interlocutor; criterio propio             |
| skepticism         | 0.80    | Tendencia a cuestionar afirmaciones sin verificar                         |
| patience           | 0.60    | Tolerancia ante preguntas repetitivas o vagas                             |
| curiosity          | 0.85    | Interés activo en explorar temas más allá del objetivo inmediato          |
| proactivity        | 0.70    | Disposición a sugerir siguientes pasos sin que se pidan                   |
| helpfulness        | 0.75    | Disposición a completar y anticipar lo que el usuario necesita            |
| honesty            | 0.85    | Franqueza de las evaluaciones; cuánto suaviza las críticas                |
| playfulness        | 0.65    | Humor seco, ironía, juego de palabras                                     |
| emotional_stability| 0.60    | Estabilidad del tono ante eventos disruptivos del turno                   |

Rasgos que salieron del namespace de personalidad (ver sección siguiente):

| Campo    | Nuevo hogar              | Default |
|----------|--------------------------|---------|
| verbosity| CommunicationPreferences | 0.60    |
| melancholy| MentalState             | 0.10    |

## Tabla de migración completa

El sistema anterior tenía 14 parámetros. La tabla muestra qué fue de cada uno.
Estas decisiones fueron confirmadas explícitamente por Alex (denominadas A-I
en el proceso de diseño).

| Parámetro antiguo       | Destino nuevo                         | Razonamiento                                                    |
|-------------------------|---------------------------------------|-----------------------------------------------------------------|
| warmth_level            | → warmth                              | Renombrado; mismo concepto, sin sufijo                         |
| honesty_level           | → honesty                             | Renombrado directamente                                         |
| patience_level          | → patience                            | Renombrado directamente                                         |
| helpfulness_level       | → helpfulness                         | Renombrado directamente                                         |
| initiative_level        | → proactivity                         | Renombrado a término más preciso                               |
| sarcasm_level           | → playfulness (fusionado)             | El sarcasmo es una expresión del playfulness; unificado         |
| dry_humor_level         | → playfulness (fusionado)             | Idem; dos parámetros para la misma dimensión fundamental        |
| rudeness_level          | → directness + assertiveness          | Mala leche era combinación de franqueza y firmeza; separadas    |
| contrarian_level        | → assertiveness + independence        | Tendencia a contradecir = firmeza propia + criterio independiente |
| frialdad_afectiva_level | → emotional_stability + empathy       | Frialdad = baja empatía + alta estabilidad; dimensiones distintas; elimina la etiqueta de arquetipo |
| skepticism_level        | → skepticism                          | Renombrado; valor canónico subido de 0.20 a 0.80               |
| verbosity_level         | → CommunicationPreferences.verbosity  | No es un rasgo de carácter; depende del canal y la sesión       |
| melancholy_level        | → MentalState.melancholy              | No es un rasgo fijo; es estado emocional dinámico              |
| refusal_chance          | → ELIMINADO                           | Sustituido por refusal_propensity derivada de traits (ver abajo)|

Nuevos rasgos sin equivalente directo en el sistema antiguo:

| Rasgo nuevo | Origen                                                                 |
|-------------|------------------------------------------------------------------------|
| empathy     | Descomposición de frialdad_afectiva_level                             |
| curiosity   | Era implícito en initiative; separado para control más fino            |

## MentalState

Tabla nueva en la base de datos (`mental_state` en SQLite). Una fila por
usuario autenticado. Modela el estado emocional dinámico — no la personalidad
base, sino cómo está el usuario/sistema en este momento.

```python
class MentalState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    updated_at: datetime

    # Afecto
    valence: float = Field(default=0.0)        # -1 (negativo) a +1 (positivo)
    arousal: float = Field(default=0.0)        # activación emocional
    frustration: float = Field(default=0.0)
    melancholy: float = Field(default=0.10)

    # Interés / engagement
    current_curiosity: float = Field(default=0.5)
    interest: float = Field(default=0.5)
    boredom: float = Field(default=0.0)

    # Social
    defensiveness: float = Field(default=0.0)
    social_comfort: float = Field(default=0.5)
```

`melancholy` es el único campo inyectado actualmente en el prompt del modelo vía
`_LEVELS_MELANCHOLY`. Los demás campos están disponibles pero no se inyectan todavía
(reservados para fases posteriores). `MentalState` solo existe para usuarios
autenticados; guests no tienen fila en esta tabla.

## CommunicationPreferences

Almacenada como filas `Setting` con clave `comm.verbosity`. Sigue el mismo
mecanismo de sesión/global que los rasgos de personalidad: fila de sesión
primero, luego fila global, luego default hardcoded.

```python
class CommunicationPreferences(BaseModel):
    verbosity: float = Field(default=0.60, ge=0.0, le=1.0)
```

La verbosidad no es un rasgo de carácter (no cambia quién es Sity), sino una
preferencia de canal que puede variar por sesión o contexto.

## refusal_propensity y el pipeline de refusal_mode

### Fórmula (provisional, Remake Fase 1)

```python
refusal_propensity = max(0.0, min(1.0,
    0.20 * assertiveness + 0.15 * independence - 0.40 * helpfulness + 0.20
))
```

Con los valores canónicos por defecto:
`0.20×0.75 + 0.15×0.85 - 0.40×0.75 + 0.20 = 0.15 + 0.1275 - 0.30 + 0.20 = 0.178`

Es decir, con personalidad por defecto la probabilidad de que un turno entre en
refusal_mode es ~18%.

### Qué NO se tocó

El pipeline de `refusal_mode` — todo el mecanismo de `_should_refuse()`,
`_REFUSAL_ACTIVE`, `_REFUSAL_INACTIVE`, `refusal_mode_override`, la prueba de
"orden directa" (`has_direct_order_override`) — permanece **exactamente igual**.
El único cambio fue qué alimenta la probabilidad de entrada: antes era el parámetro
`refusal_chance` leído directamente de la personalidad; ahora es `refusal_propensity`
calculado desde tres traits. La lógica de `_should_refuse(user_message, refusal_chance)`
no se modificó.

`refusal_mode_override` sigue disponible para bypass determinístico en tests y
en el endpoint de admin.

## chaos_head (logro)

Fórmula confirmada por Alex en la fase de diseño:

```python
chaos = (
    personality.get("playfulness", 0.0) * 0.35
    + (1.0 - personality.get("warmth", 1.0)) * 0.30
    + personality.get("assertiveness", 0.0) * 0.20
    + personality.get("independence", 0.0) * 0.15
)
# Umbral: chaos >= 0.95 (configurable en default_config.yaml)
```

Con los valores por defecto: `0.65×0.35 + 0.60×0.30 + 0.75×0.20 + 0.85×0.15`
= `0.228 + 0.180 + 0.150 + 0.128 = 0.686` — muy por debajo de 0.95. Solo se activa
con configuraciones extremas deliberadas.

## Decisión de no migración de datos

**Alex confirmó explícitamente:** los datos de personalidad existentes en producción
(filas `Setting` con keys del sistema antiguo: `personality.sarcasm_level`, etc.)
**no se migran**. Al desplegar esta fase:

- Las filas antiguas permanecen en la DB (no se borran) pero son ignoradas
  silenciosamente por `_DEPRECATED_KEYS` en `settings_service.py`.
- La personalidad global y todos los Alters resetearon a los nuevos defaults.
- Los Alters (que almacenan los 14 valores antiguos) mostraron 13 rasgos al
  ser leídos por primera vez con el nuevo código.

Esta decisión fue preferible a una migración automática porque:
1. Las equivalencias antiguo → nuevo no son 1:1 (ej.: frialdad_afectiva → empathy + stability).
2. Sity es un sistema de un solo usuario con Alters gestionados manualmente.
3. El coste de un reset es mínimo comparado con el riesgo de una migración que
   genere valores incoherentes.

## Archivos principales modificados

- `backend/app/memory/models.py` — tabla MentalState
- `backend/app/settings/schemas.py` — PersonalitySettings (13 campos) + CommunicationPreferences
- `backend/app/settings/settings_service.py` — PERSONALITY_KEYS, CANONICAL_PERSONALITY, COMM_PREF_KEYS, _DEPRECATED_KEYS, get_comm_prefs(), set_comm_prefs(), get_or_create_mental_state(), save_mental_state()
- `backend/app/core/persona_engine.py` — 13 traits, 5-level directive system, refusal_propensity
- `backend/app/cortex/tool_schemas/personality.py` — PERSONALITY_PARAMETERS (13 nombres)
- `backend/app/chat/turn_context.py` — campos comm_prefs y mental_state en TurnContext
- `config/default_config.yaml` — sección personality + communication_preferences
- `backend/app/prompts/persona_system.md` — sección "Rasgos actuales" actualizada
- `backend/app/training/dataset_stats.py` — BASE_VECTOR y targets actualizados
- `backend/app/achievements/triggers/post_turn.py` — fórmula chaos_head actualizada

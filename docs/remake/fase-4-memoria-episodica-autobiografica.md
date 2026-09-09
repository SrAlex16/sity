# Fase 4 — Memoria Episódica y Autobiográfica

**Estado:** Partes 1–3 completas (2026-09-09)  
**Commits:** `1fd142d` (Parte 2), `56803a0` (Parte 3)  
**Tests:** 29 (episode_service) + 17 (autobiographical_narrative) = 46 nuevos  

---

## Objetivos

Dotar a Sity de una memoria estructurada de momentos significativos (episódica)
y de una narrativa de identidad acumulada a lo largo del tiempo (autobiográfica),
sin coste de tokens en turnos rutinarios.

---

## Diseño central: salience como filtro de coste

La salience es una puntuación determinista (sin llamada a modelo) que evalúa
qué tan memorable es un turno. Solo los turnos que superan el umbral `baja`
(≥ 0.25) generan una llamada condicional a Haiku para sintetizar el episodio.
Los turnos rutinarios tienen coste cero.

### Fórmula de salience (7 componentes, pesos ∑=1.0)

```
salience = 0.20 × novelty
         + 0.15 × emotional_intensity
         + 0.25 × goal_relevance
         + 0.15 × relationship_impact
         + 0.10 × surprise
         + 0.05 × repetition          ← 0.0 siempre (bootstrap)
         + 0.10 × explicit_importance
```

| Componente           | Fuente                                                                 |
|----------------------|------------------------------------------------------------------------|
| novelty              | `perception.novelty` [0, 1]                                           |
| emotional_intensity  | `(|interest_delta| + |frustration_delta|) / 0.6`, clamped [0, 1]    |
| goal_relevance       | `max(gr.relevance for gr in appraisal.goal_relevance)`, default 0.0  |
| relationship_impact  | `clamp(social_signal×0.5 + challenge×0.4 + trust_evidence×4.0)`      |
| surprise             | `appraisal.surprise` [0, 1] — campo nuevo en AppraisalResult          |
| explicit_importance  | `appraisal.explicit_importance` [0, 1] — campo nuevo                  |

**Regla especial:** si `explicit_importance > 0.70` → `salience = max(salience, 0.45)`
(el usuario ha marcado algo como importante → al menos nivel `media`).

### Niveles y comportamiento

| Nivel    | Rango        | Acción                                         | strength |
|----------|--------------|------------------------------------------------|----------|
| baja     | < 0.25       | sin Episode, cero coste                        | 0.0      |
| media    | 0.25–0.45    | Episode creado, Haiku call (max_tokens=150)    | 0.50     |
| alta     | 0.45–0.70    | Episode creado                                 | 1.00     |
| muy_alta | ≥ 0.70       | Episode creado, candidato autobiográfico       | 1.00     |

---

## Módulos nuevos / modificados

### `app/cognition/appraisal.py`

`AppraisalResult` extendido con dos campos opcionales:

```python
surprise: float = 0.0           # qué tan inesperado fue el turno [0, 1]
explicit_importance: float = 0.0 # usuario marcó algo como importante [0, 1]
```

El esquema JSON enviado a Haiku incluye guidelines para ambos campos.
`max_tokens` aumentado 300 → 350 para acomodar los dos campos extras.
`_parse_appraisal` extrae y clampea ambos campos; JSON sin los campos (backward compat)
defaults a 0.0.

### `app/cognition/episode_service.py` (nuevo)

- `compute_salience(perception, appraisal) → SalienceResult`  
  Pura, determinista, sin I/O. Accede a todos los componentes de la fórmula.

- `_generate_episode_summary(user_message, trace_id) → Optional[EpisodeSummaryResult]`  
  Llamada condicional a Haiku. Devuelve resumen, topics, emotional_valence, emotional_arousal.
  Retorna `None` en cualquier error.

- `maybe_create_episode(session, user_id, user_message, perception, appraisal, source_message_ids, *, trace_id) → Optional[Episode]`  
  Punto de entrada. Evalúa salience → llama Haiku si necesario → persiste Episode.
  `source_message_ids=[]` por ahora (ChatMessage ID no disponible en tiempo de cognición).

### `app/cognition/turn_cognition.py`

Paso 10 añadido al pipeline de `run_cognition_turn()`:

```python
try:
    maybe_create_episode(session, user_id, user_message, perception, appraisal, [], trace_id=trace_id)
except Exception as ep_exc:
    write_log(level="WARN", ...)  # fallo aislado, no bloquea pipeline
```

### `app/memory/models.py`

**`Episode`** — registro de un momento significativo:

| Campo                     | Tipo    | Descripción                                              |
|---------------------------|---------|----------------------------------------------------------|
| `user_id`                 | int     | índice, FK no forzada a User                             |
| `occurred_at`             | datetime| cuándo ocurrió                                           |
| `summary`                 | str     | texto generado por Haiku                                 |
| `topics_json`             | str     | lista JSON de palabras clave                             |
| `source_message_ids_json` | str     | lista JSON de ChatMessage IDs (puede ser `[]`)           |
| `salience_*`              | float   | componentes individuales de salience (para calibración) |
| `salience_total`          | float   | puntuación final [0, 1]                                  |
| `emotional_valence`       | float   | **bipolar [-1, 1]** — excepción al convenio [0, 1]       |
| `emotional_arousal`       | float   | activación emocional [0, 1]                              |
| `strength`                | float   | 0.50 (media) / 1.00 (alta, muy_alta)                     |
| `recall_count`            | int     | cuántas veces se recuperó en contexto                    |
| `last_recalled_at`        | datetime?| última recuperación                                     |

**`AutobiographicalNarrative`** — narrativa de identidad por período:

| Campo                         | Tipo    | Descripción                                    |
|-------------------------------|---------|------------------------------------------------|
| `user_id`                     | int     | índice                                         |
| `period`                      | str     | trimestre, e.g. "2026-Q3"                      |
| `narrative`                   | str     | texto generado por Haiku                       |
| `identity_effects_json`       | str     | lista JSON de rasgos inferidos (placeholder)   |
| `important_episode_ids_json`  | str     | Episode IDs que alimentaron esta narrativa     |
| `superseded_at`               | datetime?| set cuando se genera una nueva narrativa      |

No se requiere migración: `init_db()` → `create_all()` crea ambas tablas.

### `app/social/update.py`

`_run_social_update` llama `_maybe_generate_narrative()` tras `_maybe_generate_reflection()`.
Errores aislados con try/except separado para que un fallo de narrativa no afecte el job.

**Trigger conditions:**

```
Sin narrativa previa:
  count(muy_alta_episodes) >= narrative_min_muy_alta_episodes

Con narrativa previa:
  age_days(last_narrative) >= narrative_min_days_since_last
  AND count(muy_alta_episodes_since_last) >= narrative_min_muy_alta_episodes
```

**Haiku call:** max_tokens=200, genera texto libre en español (3-5 frases).

---

## Configuración (`config/default_config.yaml`)

```yaml
social:
  narrative_min_muy_alta_episodes: 3   # min episodios muy_alta para trigger
  narrative_min_days_since_last: 7     # age gate entre narrativas
  narrative_max_episodes: 10           # max episodios como evidencia para Haiku
```

---

## Decisiones de diseño confirmadas

1. **Episódico + autobiográfico juntos** — un solo bloque de Parte 2+3.
2. **Evaluación por turno** — dentro del pipeline Appraisal, no en job separado.
3. **Sin migración de datos** — sistema arranca vacío.
4. **Coste cero en turnos rutinarios** — salience < 0.25 → ninguna llamada extra.
5. **`source_message_ids=[]`** — ChatMessage ID no disponible en tiempo de cognición.
6. **AutobiographicalNarrative en background job** — mismo patrón que SocialReflection.

---

## Pendiente (Parte 4 original, renumerada)

- Inyección de contexto de memoria episódica en el prompt (recuperación de episodios relevantes).
- `recall_count` + `last_recalled_at` actualizados cuando un episodio se inyecta.
- `identity_effects_json` poblado (actualmente siempre `[]`).

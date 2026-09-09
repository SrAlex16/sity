# Fase 3 — Relación multidimensional

## Resumen

Fase 3 reemplaza el modelo binario `opinion` / `trust` de SocialProfile por 11 dimensiones
independientes clampeadas a [0, 1]. El estado de la relación evoluciona por turno a partir de
señales de Perception y Appraisal moduladas por la personalidad de Sity. Las fórmulas de logros
sociales se reimplementan sobre las dimensiones nuevas.

---

## 1. SocialProfile — 11 dimensiones

**Módulo:** `app/memory/models.py` · **Tabla:** `socialprofile`

| Dimensión | Default | Semántica |
|-----------|---------|-----------|
| `familiarity` | 0.0 | Grado de conocimiento acumulado. Crece muy lento (~200 turnos para 1.0). |
| `trust_honesty` | 0.5 | Credibilidad percibida del usuario. |
| `trust_intentions` | 0.5 | Percepción de buenas intenciones. Baja con confrontación. |
| `trust_competence` | 0.5 | Competencia percibida (estable en v1). |
| `trust_reliability` | 0.5 | Consistencia percibida (estable en v1). |
| `affinity` | 0.0 | Atracción/interés hacia el usuario. Crece con interés positivo. |
| `comfort` | 0.5 | Comodidad en la interacción. |
| `respect` | 0.5 | Respeto hacia el usuario. Baja con confrontación alta. |
| `attachment` | 0.0 | Vínculo emocional acumulado. Crece muy lento con `social_signal`. |
| `conflict` | 0.0 | Tensión/fricción acumulada. Crece con frustración y confrontación. |
| `uncertainty` | 0.5 | Incertidumbre sobre el usuario. Baja con evidencia de confianza. |

Las columnas `opinion` y `trust` se mantienen en la tabla como dead weight (nullable) para
preservar historial; nunca se escriben en código nuevo.

**Helper:** `trust_avg(profile)` = `(trust_honesty + trust_intentions + trust_competence + trust_reliability) / 4`

---

## 2. apply_appraisal_to_social_profile

**Módulo:** `app/social/social_service.py`

Actualiza las 11 dimensiones en-place a partir de señales de Perception y Appraisal:

| Señal | Rango | Fuente |
|-------|-------|--------|
| `trust_evidence` | [0, 0.05] | Appraisal |
| `interest_delta` | [-0.3, 0.3] | Appraisal |
| `frustration_delta` | [-0.3, 0.3] | Appraisal |
| `social_signal` | [0, 1] | Perception |
| `challenge` | [0, 1] | Perception |

Moduladores de personalidad:

| Trait | Efecto |
|-------|--------|
| `skepticism` | Reduce el crecimiento de trust (`trust_mod = 1 - sk*0.4`) |
| `warmth` | Amplifica el crecimiento de affinity desde interest positivo |
| `patience` | Reduce la acumulación de conflict |
| `assertiveness` | Amplifica la pérdida de respect bajo confrontación |
| `empathy` | Amplifica el crecimiento de attachment |

Los traits modifican la magnitud de los cambios; nunca se copian al estado de la relación.
Todos los valores se clampean a [0, 1] tras la actualización.

---

## 3. RelationshipSnapshot y _combined_delta

**Módulo:** `app/social/update.py` · **Tabla:** `relationshipsnapshot`

`RelationshipSnapshot` reemplaza `OpinionSnapshot`. Almacena 3 dimensiones por batch:

```
profile_id  →  affinity, conflict, trust_avg, computed_at
```

**_combined_delta()** — métrica de cambio ponderado usada para decidir si generar una
`SocialReflection`:

```
Δcombined = 0.35·|Δaffinity| + 0.30·|Δconflict| + 0.25·|Δtrust_avg| + 0.10·|Δattachment|
```

Pesos: affinity es la señal más visible; conflict tiene peso alto porque cambios pequeños son
notables; trust_avg cambia lento pero importa; attachment crece muy despacio y representa vínculo
profundo.

---

## 4. SocialReflection — campos at_gen actualizados

**Tabla:** `socialreflection`

Campos `*_at_gen` almacenan el estado del perfil en el momento de generar la reflexión:

| Campo nuevo | Campo eliminado |
|-------------|----------------|
| `affinity_at_gen` | `opinion_at_gen` (dead weight, nullable) |
| `conflict_at_gen` | `trust_at_gen` (dead weight, nullable) |
| `trust_avg_at_gen` | — |
| `attachment_at_gen` | — |

Estos campos permiten calcular `_combined_delta` comparando el estado actual vs. el estado al
momento de la última reflexión, para decidir si generar una nueva.

---

## 5. social_recall_impression — disclosure por confianza cruzada

**Handler:** `app/tools/handlers/social_tools.py`

La herramienta responde a consultas del tipo "¿qué sé de [persona]?" con 3 niveles de detalle:

```
disclosure = trust_avg(A) × trust_avg(B)
```

| Nivel | Condición | Contenido |
|-------|-----------|-----------|
| LOW | disclosure < 0.05 | Solo etiqueta de afinidad; usa "de esa persona", sin nombrar a B |
| MEDIUM | 0.05 ≤ disclosure < 0.20 | Etiqueta + línea de nivel de conocimiento; nombra a B |
| HIGH | disclosure ≥ 0.20 | Etiqueta + familiarity + línea cualitativa derivada de trust_avg_B |

**Hard limit:** nunca se incluye contenido literal de los mensajes de B.
**Anti-injection:** disclosure se calcula siempre desde valores almacenados, no declarados.

---

## 6. Contexto social en initiative/evaluator.py

**Módulo:** `app/initiative/evaluator.py`

El contexto social inyectado en el prompt de Haiku para evaluar iniciativas:

```
Perfil social: familiaridad=X.XX, afinidad=X.XX, confianza=X.XX, conflicto=X.XX
```

Gate de familiarity en `runner.py`: si `social.familiarity < initiative_min_familiarity`,
la iniciativa se omite (config: `initiative_min_familiarity: 0.05`).

---

## 7. Logros sociales — Paso 2 (5 fórmulas)

**Módulo:** `app/achievements/triggers/post_turn.py` · `_check_social()`

### remember_me
```
trust_avg(profile) ≥ 0.65  AND  familiarity ≥ 0.30
```
Confianza consolidada + interacción suficiente para que Sity tome la iniciativa.

### love_is_war
```
conflict ≥ 0.50  AND  affinity < 0.20
```
Conflicto significativo sin contrapartida de afecto.

### its_over_9000 _(secreto)_
```
conflict ≥ 0.75  AND  affinity < 0.10
```
Versión extrema. Requiere deterioro activo y sostenido de la relación.

### redemption
```
∃ RelationshipSnapshot: conflict ≥ 0.50 AND affinity < 0.20  (estuvo en estado "guerra")
AND  actualmente: affinity ≥ 0.35 AND conflict < 0.30        (recuperado)
```
Detecta el arco narrativo: estuvo mal, lo remontó.

### schizophrenia _(secreto)_
```
En snapshots ordenados: estado_i = "bad" si conflict_i ≥ 0.35 else "good"
transiciones_adyacentes ≥ schizophrenia_min_flips (= 3)
```
Ejemplo mínimo: good→bad→good→bad = 3 transiciones.

---

## 8. Migraciones DB

**Módulo:** `app/memory/db.py`

### _migrate_social_profile_fase3
- Detecta si `opinion` / `trust` son NOT NULL sin DEFAULT (constraint original).
- Si es así, reconstruye la tabla con `CREATE TABLE _sp_rebuild ... id INTEGER PRIMARY KEY`
  (preserva autoincrement), copia datos, DROP + RENAME, recrea índice unique.
- Luego añade las 11 columnas nuevas via `ALTER TABLE ADD COLUMN` si faltan.
- Idempotente: si las columnas ya existen, no hace nada.

### _migrate_social_reflection_fase3
- Mismo patrón: reconstruye la tabla para relajar NOT NULL en `opinion_at_gen` /
  `trust_at_gen`, luego ADD COLUMN para los 4 campos `*_at_gen` nuevos.
- Recrea el índice `ix_socialreflection_profile_id` tras el rebuild.

---

## 9. Config keys

### `social:`
| Key | Valor | Descripción |
|-----|-------|-------------|
| `reflection_min_combined_delta` | 0.15 | |Δcombined| mínimo para generar reflexión sin esperar N mensajes |

### `notifications:`
| Key | Valor | Descripción |
|-----|-------|-------------|
| `initiative_min_familiarity` | 0.05 | Familiarity mínima para recibir iniciativas |

### `achievements:`
| Key | Valor | Descripción |
|-----|-------|-------------|
| `remember_me_trust_avg_threshold` | 0.65 | trust_avg mínimo (escala [0,1]; default=0.5) |
| `remember_me_familiarity_threshold` | 0.30 | familiarity mínima |
| `love_is_war_conflict_threshold` | 0.50 | umbral de conflict para love_is_war y redemption |
| `love_is_war_affinity_ceiling` | 0.20 | techo de affinity para love_is_war |
| `its_over_9000_conflict_threshold` | 0.75 | umbral de conflict extremo |
| `its_over_9000_affinity_ceiling` | 0.10 | techo de affinity extremo |
| `schizophrenia_min_flips` | 3 | transiciones de estado mínimas en snapshots |

**Claves eliminadas:** `remember_me_trust_threshold`, `opinion_negative_threshold`,
`opinion_extreme_threshold`, `initiative_min_trust`.

---

## 10. Tests

| Archivo | Tests |
|---------|-------|
| `tests/test_social_memory.py` | 58 — _combined_delta, apply_appraisal, _run_social_update |
| `tests/test_social_memory_narrative.py` | 8 — SocialReflection generación y narrativa |
| `tests/test_social_tools.py` | 12 — social_recall_impression, 3 niveles disclosure |
| `tests/test_achievement_post_turn.py` | 49 — 5 logros sociales + personality + age |
| `tests/test_initiative_step3.py` | 28 — contexto social 4-dim en evaluator |
| `tests/test_initiative_step4.py` | 28 — gate familiarity en runner |

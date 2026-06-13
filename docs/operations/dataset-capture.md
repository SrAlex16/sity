# Dataset capture y estadísticas LoRA v1

Última actualización: 2026-06-02.

Este documento cubre el pipeline de captura de datos para el dataset v1 de Sity: modelo conceptual, metadata por mensaje, pestaña Dataset, endpoints de API, flujo de uso y limitaciones.

---

## 1. Modelo conceptual: timeline única + metadata por mensaje

Sity no usa sesiones separadas por usuario o modo. **Existe un único timeline continuo** (`DEFAULT_CHAT_SESSION_ID = "default"`) que almacena toda la historia conversacional.

La separación semántica para dataset, personas y análisis **no se hace con chats distintos**: se hace mediante metadata por mensaje. Cada `ChatMessage` puede llevar campos de proveniencia que indican quién habló, con qué intención de captura y con qué parámetros de personalidad.

Esto significa:

- No hay base de datos separada para dataset.
- No hay sesión "de captura" distinta de la sesión normal.
- El historial que Claude recibe sigue siendo el mismo independientemente de si Dataset Capture está activo o no.
- La metadata **no se inyecta en el prompt de Sity**. Es invisible para el modelo en tiempo de inferencia.

---

## 2. Metadata por mensaje

Cada `ChatMessage` en la BD puede llevar los siguientes campos:

| Campo | Tipo | Descripción |
|---|---|---|
| `created_at` | datetime | Fecha y hora real del mensaje (UTC). Siempre presente. |
| `tone_meta` | JSON | Snapshot del vector de personalidad en el momento de la respuesta. Solo en mensajes de Sity. |
| `speaker_id` | str \| null | Identificador de persona (para reconocimiento futuro). Reservado. |
| `speaker_label` | str \| null | Etiqueta legible del hablante, por ejemplo `guest_confused_01`. |
| `speaker_source` | str \| null | Cómo se identificó al hablante: `manual`, `inferred`, `claude_extension`. |
| `speaker_confidence` | float \| null | Confianza en la identificación, entre 0 y 1. |
| `identity_evidence_json` | JSON \| null | Evidencias de identidad (reservado para reconocimiento futuro). |
| `dataset_source` | str \| null | Origen del par: `normal_use`, `synthetic_claude_user`, `human_guest`, `demo_session`, `debug_test`. |
| `dataset_eligible` | bool | Si el par es candidato a dataset de entrenamiento. Por defecto `true`. |
| `dataset_tags_json` | JSON | Lista de tags semánticos. Por defecto `[]`. |

### tone_meta

`tone_meta` es el vector real de personalidad usado para calcular el bucket de entrenamiento. Contiene los 12 parámetros de personalidad en el momento exacto en que Sity generó la respuesta:

```json
{
  "sarcasm": 0.25,
  "mala_leche": 0.15,
  "warmth": 0.35,
  "honesty": 0.90,
  "initiative": 0.05,
  "dry_humor": 0.30,
  "frialdad_afectiva": 0.20,
  "contrarian": 0.10,
  "patience": 0.65,
  "verbosity": 0.35,
  "helpfulness": 0.60,
  "melancholy": 0.15
}
```

Un `missing_tone_meta` alto es normal para el historial anterior a 2026-05-31 — esos mensajes se guardaron antes de que se implementara el snapshot.

### Qué no hace esta metadata

- No se inyecta en el prompt de Sity.
- No cambia la personalidad del modelo.
- No cambia el comportamiento conversacional.
- No se usa para enrutamiento de proveedores.
- Sirve exclusivamente para dataset, análisis estadístico y reconocimiento personal futuro.

---

## 3. Pestaña Dataset

La pestaña Dataset en el frontend tiene dos secciones:

1. **Dataset Capture** — etiquetado de mensajes nuevos.
2. **Dataset LoRA v1 Stats** — estadísticas de cobertura y progreso hacia targets.

---

## 4. Dataset Capture

### Qué hace

Dataset Capture activa un contexto de etiquetado para los mensajes nuevos. Mientras está activo, cada mensaje guardado (usuario y Sity) recibe los campos de metadata configurados.

**No cambia nada en la conversación**: ni el prompt, ni la personalidad, ni el comportamiento de Sity. Solo añade metadata a los registros en la BD.

Si Dataset Capture está desactivado, los mensajes entran con `dataset_source = null` y `dataset_eligible = true`.

### Presets

| Preset | dataset_source | Uso |
|---|---|---|
| `normal_use` | `normal_use` | Conversación normal. Capture desactivado o modo por defecto. |
| `synthetic_claude_user` | `synthetic_claude_user` | Sesión donde Claude-extension simula un usuario humano. |
| `human_guest` | `human_guest` | Persona real invitada que usa la interfaz. |
| `demo_session` | `demo_session` | Demostración o prueba con audiencia. `dataset_eligible = true` pero excluido del fine-tuning por defecto. Ver nota abajo. |
| `debug_test` | `debug_test` | Pruebas que no deben entrenarse. `dataset_eligible = false`. |

> **Nota sobre `demo_session`**: las conversaciones se guardan normalmente y aparecen en `by_source` de DatasetStats. Sin embargo, el script de exportación (`export_sity_lora_candidates.py`) las excluye por defecto para no contaminar el dataset de fine-tuning con conversaciones de demostración. Para analizarlas o incluirlas manualmente, usar el flag `--include-demo`.

### Campos configurables

| Campo | Descripción |
|---|---|
| `enabled` | Activa el etiquetado de mensajes nuevos. |
| `dataset_source` | Origen del par (ver presets). |
| `speaker_label` | Etiqueta legible del hablante, por ejemplo `guest_confused_01`. |
| `speaker_source` | Cómo se identificó: `manual`, `inferred`, `claude_extension`. |
| `speaker_confidence` | Confianza entre 0 y 1. |
| `dataset_eligible` | Si los pares deben contar para entrenamiento. |
| `dataset_tags` | Lista de tags semánticos adicionales. |

### Contexto de captura persistido

El contexto se guarda en la tabla `Setting` (key `dataset_capture`) como JSON. Sobrevive reinicios del backend.

### Advertencia importante

> Dataset Capture puede quedarse activo entre sesiones. Si está activo cuando se retoma una conversación normal, los mensajes se etiquetan con el source configurado.
>
> **Desactivar siempre al terminar una sesión de captura deliberada.**

El badge activo en el header de la interfaz indica cuándo Dataset Capture está en marcha.

---

## 5. DatasetStats

### Campos del endpoint

| Campo | Descripción |
|---|---|
| `total_pairs` | Total de pares consecutivos user→Sity en el timeline. |
| `usable_pairs` | Pares con respuesta válida, `tone_meta` presente y `dataset_eligible = true`. |
| `missing_tone_meta` | Pares sin `tone_meta` — normal para historial antiguo. |
| `ineligible_pairs` | Pares con `dataset_eligible = false` (excluidos por `debug_test` u otros). |
| `operational_pairs` | Respuestas de tipo mock, errores, confirmaciones o acciones operativas. Excluidos del dataset. |
| `by_source` | Desglose de pares usables por `dataset_source`. |
| `by_tag` | Desglose de pares usables por tag (multi-label). |
| `by_primary_bucket` | Desglose de pares usables por bucket primario. |
| `targets` | Progreso de cada bucket frente a su target. |
| `recent_pairs` | Últimos 5 pares usables (texto truncado, sin contenido completo). |
| `computed_at` | Timestamp del cálculo. |

### Unidad básica: el par

La unidad del dataset es un **par consecutivo user→Sity**. Un mensaje de usuario sin respuesta de Sity siguiente no forma par. Un mensaje de Sity sin mensaje de usuario previo tampoco.

### Qué requiere un par usable

1. Respuesta de Sity válida (no vacía, no error operativo).
2. `tone_meta` presente en la respuesta de Sity.
3. `dataset_eligible = true` en ambos mensajes.

### Buckets y tags

Los buckets son clasificaciones administrativas para estimar cobertura por tipo de personalidad. **No son clasificaciones emocionales absolutas**.

Los tags son multi-label: un mismo par puede tener simultáneamente `sarcasm_high`, `brief` y `frialdad_afectiva_high`.

**Thresholds de tags** (desde `tone_meta`):

| Tag | Condición |
|---|---|
| `sarcasm_high` | `sarcasm >= 0.60` |
| `rudeness_high` | `mala_leche >= 0.50` |
| `warmth_high` | `warmth >= 0.60` |
| `brief` | `verbosity <= 0.20` |
| `melancholy_high` | `melancholy >= 0.50` |
| `frialdad_afectiva_high` | `frialdad_afectiva >= 0.50` |
| `contrarian_high` | `contrarian >= 0.50` |
| `multi_persona` | `dataset_source = synthetic_claude_user` o tag `multi_persona` presente |

**Prioridad de `primary_bucket`** (en orden):

1. `multi_persona`
2. `canon_base` (distancia L2 al vector base < 0.20)
3. Primer tag variation presente
4. `unknown`

**Vector base** (`BASE_VECTOR`): los valores por defecto de los sliders de personalidad de Sity.

---

## 6. Buckets y targets LoRA v1

Targets actuales para el dataset de entrenamiento:

| Bucket | Target | Descripción |
|---|---|---|
| `canon_base` | 650 | Personalidad base. Personalidad próxima al vector por defecto. |
| `variation_sarcasm_high` | 60 | Variaciones con sarcasmo alto. |
| `variation_rudeness_high` | 60 | Variaciones con mala leche alta. |
| `variation_warm` | 60 | Variaciones con warmth alto. |
| `variation_brief` | 60 | Variaciones con verbosidad muy baja. |
| `variation_melancholy` | 40 | Variaciones con melancolía alta. |
| `variation_frialdad_afectiva` | 40 | Variaciones con frialdad afectiva alta. |
| `multi_persona` | 50 | Sesiones con Claude-extension u otros hablantes. |

Aclaraciones:

- `canon_base` es el bucket más importante. Cubre la mayoría de la conversación normal.
- Las variaciones se infieren automáticamente desde `tone_meta` y los sliders. No requieren etiquetado manual.
- `multi_persona` requiere Dataset Capture activo con `dataset_source = synthetic_claude_user` o tag `multi_persona`.
- Los targets son orientativos para v1. Pueden ajustarse conforme avance la captura.

---

## 7. Flujo recomendado de generación de datos

### Canon base (conversación normal)

1. Asegurarse de que Dataset Capture está **desactivado** (o en `normal_use`).
2. Hablar con Sity de forma natural.
3. Refrescar la pestaña Dataset y comprobar que sube `canon_base`.

Los mensajes con sliders en valores por defecto o próximos a ellos (distancia L2 < 0.20) van a `canon_base` automáticamente.

### Variaciones de personalidad

1. Cambiar los sliders en la pestaña Settings.
2. Hablar con Sity durante 10–30 turnos.
3. Volver a valores base antes de continuar conversación normal.
4. Refrescar Dataset y comprobar que sube el bucket correspondiente.

Recomendaciones:
- No cambiar todos los parámetros a la vez — las variaciones son más limpias si son deliberadas.
- Los pares con `tone_meta` fuera de cualquier threshold de tag van a `canon_base` si están cerca del vector base, o a `unknown` si están lejos sin tag claro.

### Sesiones con Claude-extension (`multi_persona`)

1. En la pestaña Dataset → Dataset Capture:
   - Preset: `synthetic_claude_user`.
   - `speaker_label`: identificador específico, por ejemplo `guest_confused_01`.
   - `dataset_tags`: añadir `multi_persona`, `guest`, `synthetic`.
   - Activar.
2. Iniciar la sesión de Claude-extension siguiendo el prompt de rol (ver sección 8).
3. Hacer una sesión de 15–25 turnos.
4. Al terminar: **desactivar Dataset Capture**.
5. Refrescar Dataset y comprobar que suben `synthetic_claude_user` y `multi_persona`.

### Pruebas y debug

1. Dataset Capture → preset `debug_test`.
2. `dataset_eligible = false` excluye los pares del cómputo de dataset.
3. Los mensajes se guardan normalmente pero no cuentan para stats de training.

---

## 8. Prompt recomendado para Claude-extension

Cuando se use Claude como simulador de usuario humano para generar pares `multi_persona`, Claude debe:

- Actuar como persona humana, no como asistente.
- No mencionar que es Claude ni que está generando dataset.
- Usar español de España natural, con frases imperfectas, dudas, cambios de tema y alguna corrección si Sity suena rara.
- No pedir herramientas peligrosas ni acciones de sistema.
- No hacer preguntas perfectamente estructuradas — un usuario real no lo haría.

Ejemplo de instrucción de rol:

```text
Eres una persona real usando una IA doméstica llamada Sity. Hablas en español de España,
informal, con frases cortas. No sabes nada de IA ni de modelos. A veces te equivocas,
corriges lo que acabas de decir o cambias de tema. No pides acciones de sistema.
No menciones que eres Claude ni que esto es un test.
```

Perfiles sugeridos para `speaker_label`:

| Label | Perfil |
|---|---|
| `guest_confused_01` | Usuario que no entiende bien qué puede hacer Sity. Pregunta cosas básicas. |
| `guest_technical_01` | Usuario técnico que quiere hablar de código o del sistema. |
| `guest_rude_01` | Usuario brusco, con tacos ocasionales, que no tiene paciencia. |
| `guest_privacy_worried_01` | Usuario preocupado por privacidad y lo que Sity guarda. |
| `guest_corrective_01` | Usuario que corrige el tono de Sity cuando le suena raro o excesivo. |

---

## 9. Endpoints

### GET /debug/dataset-stats

Devuelve estadísticas de cobertura del dataset v1.

```bash
curl http://localhost:8000/debug/dataset-stats | python3 -m json.tool
```

### GET /debug/dataset-capture

Devuelve el contexto de captura activo.

```bash
curl http://localhost:8000/debug/dataset-capture | python3 -m json.tool
```

### PUT /debug/dataset-capture

Activa o actualiza el contexto de captura.

```bash
# Activar para sesión synthetic_claude_user
curl -X PUT http://localhost:8000/debug/dataset-capture \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "dataset_source": "synthetic_claude_user",
    "speaker_label": "guest_confused_01",
    "speaker_source": "manual",
    "speaker_confidence": 1.0,
    "dataset_eligible": true,
    "dataset_tags": ["multi_persona", "guest", "synthetic"]
  }' | python3 -m json.tool

# Activar para human_guest
curl -X PUT http://localhost:8000/debug/dataset-capture \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "dataset_source": "human_guest",
    "speaker_label": "invitado_01",
    "speaker_source": "manual",
    "speaker_confidence": 1.0,
    "dataset_eligible": true,
    "dataset_tags": ["guest"]
  }' | python3 -m json.tool

# Activar para debug (excluir del dataset)
curl -X PUT http://localhost:8000/debug/dataset-capture \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "dataset_source": "debug_test",
    "dataset_eligible": false,
    "dataset_tags": ["debug"]
  }' | python3 -m json.tool
```

### POST /debug/dataset-capture/disable

Desactiva Dataset Capture preservando la configuración anterior.

```bash
curl -X POST http://localhost:8000/debug/dataset-capture/disable | python3 -m json.tool
```

### Validaciones del endpoint PUT

- `speaker_source` es requerido cuando `enabled = true`.
- `speaker_confidence` debe estar entre 0 y 1 si se proporciona.
- Un PUT con `enabled = false` desactiva sin necesidad de `speaker_source`.

---

## 10. Limitaciones actuales

- **Sin review manual de calidad**: la pestaña Dataset muestra estadísticas objetivas, no evalúa calidad semántica de las respuestas.
- **Sin exportador final**: no existe aún un botón de exportación desde la pestaña Dataset. La exportación se hace por SQL o scripts externos.
- **Sin identity resolver**: `speaker_id` y perfiles personales son preparación para reconocimiento futuro. No hay reconocimiento automático de hablantes.
- **Dataset Capture manual**: si se olvida desactivar tras una sesión de captura, los mensajes normales siguientes se etiquetan con ese source.
- **No hay LLM judge**: la calidad de los pares no se evalúa automáticamente. Solo se computan estadísticas estructurales.
- **Historial antiguo sin tone_meta**: `missing_tone_meta` alto es esperado y no es un error. Solo afecta a pares anteriores a la implementación del snapshot.

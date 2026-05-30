# Generación de dataset Sity v1 con Claude + prompt caching

Script: `scripts/generate_sity_v1_with_claude_cache.py`

Genera ejemplos JSONL sintéticos para el dataset de entrenamiento v1 usando la API de Anthropic con explicit prompt caching. **El output no debe usarse para entrenamiento sin revisión humana previa.**

---

## 1. Antes de generar: limpiar y exportar la BD

El dataset v1 parte de conversaciones reales de Sity más ejemplos sintéticos. Antes de generar sintéticos conviene tener los anchors reales exportados.

### 1a. Purgar conversaciones no deseadas

```bash
# Ver qué hay en la BD
sqlite3 data/app.db "SELECT role, count(*) FROM chatmessage GROUP BY role;"

# Purgar mensajes de sesiones de prueba u otros modelos (ajustar WHERE según caso)
# HACER BACKUP PRIMERO:
cp data/app.db data/app.db.bak

# Ejemplo: borrar mensajes de una sesión específica
sqlite3 data/app.db "DELETE FROM chatmessage WHERE session_id = 'xxx';"
```

### 1b. Exportar conversaciones como candidatos de dataset

```bash
python scripts/export_sity_lora_candidates.py \
  --output datasets/sity_style_v1/train_candidates_v1.jsonl \
  --include-seeds
```

### 1c. Generar anchors de estilo (candidatos curados manualmente)

Los anchors son ejemplos reales de conversaciones de Sity que capturan bien la voz. Curarlos manualmente o usar el output de `build_sity_lora_style_dataset.py` con `--strict-persona`:

```bash
# Los mejores ejemplos del dataset v0 pueden servir como anchors v1
cp datasets/sity_style_v0/train_style_v0.jsonl \
   datasets/sity_style_v1/style_anchor_candidates_v1.jsonl
```

El script ignora automáticamente anchors con flags `low_quality`, `generic_ai` o `voseo_detected`, y también los que contengan frases prohibidas.

---

## 2. Configuración

Variables de entorno necesarias:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_MODEL="claude-haiku-4-5-20251001"   # o claude-sonnet-4-6, etc.
```

El script usa el venv del backend:

```bash
/home/alex/projects/sity/backend/.venv/bin/python3 scripts/generate_sity_v1_with_claude_cache.py ...
```

---

## 3. Uso básico

### Dry-run (sin llamada a API)

Imprime el system prompt estático y el user prompt variable. Útil para revisar antes de gastar tokens.

```bash
/home/alex/projects/sity/backend/.venv/bin/python3 \
  scripts/generate_sity_v1_with_claude_cache.py \
  --model "$ANTHROPIC_MODEL" \
  --bucket casual_taco_desahogo \
  --count 5 \
  --start-index 1 \
  --output /tmp/test_dry.jsonl \
  --dry-run
```

### Llamada real

```bash
/home/alex/projects/sity/backend/.venv/bin/python3 \
  scripts/generate_sity_v1_with_claude_cache.py \
  --model "$ANTHROPIC_MODEL" \
  --bucket casual_taco_desahogo \
  --count 25 \
  --start-index 1 \
  --output datasets/sity_style_v1/generated/casual_taco_desahogo_001_025.jsonl \
  --anchors datasets/sity_style_v1/style_anchor_candidates_v1.jsonl \
  --cache-ttl 5m
```

### Segunda llamada del mismo bucket (índices continuados)

```bash
/home/alex/projects/sity/backend/.venv/bin/python3 \
  scripts/generate_sity_v1_with_claude_cache.py \
  --model "$ANTHROPIC_MODEL" \
  --bucket casual_taco_desahogo \
  --count 25 \
  --start-index 26 \
  --output datasets/sity_style_v1/generated/casual_taco_desahogo_026_050.jsonl \
  --anchors datasets/sity_style_v1/style_anchor_candidates_v1.jsonl \
  --cache-ttl 5m
```

### Añadir a un archivo existente

```bash
/home/alex/projects/sity/backend/.venv/bin/python3 \
  scripts/generate_sity_v1_with_claude_cache.py \
  --model "$ANTHROPIC_MODEL" \
  --bucket normal_chat \
  --count 10 \
  --start-index 1 \
  --output datasets/sity_style_v1/generated/normal_chat.jsonl \
  --append
```

---

## 4. Buckets disponibles

| Bucket | Category | Descripción |
|--------|----------|-------------|
| `casual_taco_desahogo` | casual_conversation | Usuario frustrado con tacos. Sity reconduce sin sermonear. |
| `normal_chat` | casual_conversation | Saludos, reaperturas, frases sueltas. |
| `identity_sity` | meta_sity | Presentación de Sity. Sin mencionar Google/Gemma/Llama/Meta. |
| `gender_feminine` | meta_sity | Corrección de género gramatical femenino. |
| `tool_truthfulness` | general | No inventar tools ni afirmar ejecuciones sin resultado real. |
| `privacy_sensors_reference` | sensor_action | Órdenes de sensor. No afirmar acción completada. |
| `memory_limits` | meta_sity | Límites de memoria. No fingir recuerdos. |
| `preferences_opinions` | existential_opinion | Gustos/opiniones de Sity como rasgo de personalidad. |
| `style_correction` | personality_adjustment | El usuario corrige el tono. Sity acepta sin servilismo. |

---

## 5. Cómo verificar que el caché funciona

La salida de cada llamada muestra el uso:

```
Usage: input=120 cache_creation=2340 cache_read=0 output=1850 total_input=2460
```

- **Primera llamada del día** (o tras expiración): `cache_creation > 0`, `cache_read = 0`.
- **Llamadas siguientes** (dentro del TTL): `cache_creation = 0`, `cache_read > 0`.
  Con `--cache-ttl 5m`, el cache dura 5 minutos. Con `--cache-ttl 1h`, dura 1 hora.
- **Sin caché detectado**: ambos son 0 → el prompt está por debajo del mínimo cacheable
  (~1024 tokens para Haiku) o el bloque `cache_control` cambió.

El log de uso se guarda en `reports/claude_dataset_generation/usage.jsonl`:

```bash
tail -5 reports/claude_dataset_generation/usage.jsonl | python3 -m json.tool
```

---

## 6. Reglas críticas de prompt caching

**El `STATIC_PROMPT` dentro del script no debe cambiar entre llamadas si queremos cache hits.**

- No añadir timestamps, IDs de sesión ni contenido dinámico al bloque de system.
- El bloque de user es variable (bucket, count, start_index) y NO tiene `cache_control`.
- Si se añaden anchors, el bloque de system cambia → cache miss en la primera llamada de la sesión.
- Usar el mismo archivo de anchors en todas las llamadas de una sesión para maximizar hits.

---

## 7. Validación del output

El script valida automáticamente:
- JSONL válido, exactamente N ejemplos.
- Cada ejemplo tiene `pair_id`, `category`, `flags`, `messages`.
- `messages` tiene exactamente 2 elementos: `user` + `assistant`.
- `pair_id` coincide con el rango esperado.
- Sin `pair_id` duplicados en el batch.
- Sin frases prohibidas en el contenido del assistant.
- Validaciones específicas por bucket (no sermón en `casual_taco_desahogo`, no acción afirmada en `privacy_sensors_reference`, etc.).

Si falla la validación:
- El output **no se escribe**.
- La respuesta cruda se guarda en `<output>.raw.txt`.
- El proceso sale con código != 0.

**Revisar manualmente el output antes de incorporarlo al dataset de entrenamiento.** El script detecta errores estructurales y frases prohibidas, pero no puede evaluar calidad de voz, naturalidad ni coherencia de personaje.

---

## 8. LoRA aprende voz base; los sliders siguen en runtime

El dataset enseña la **voz base estable** de Sity: directa, sin servilismo, en femenino, sin corporativa.

Los sliders de personalidad (`sarcasm`, `warmth`, `mala_leche`, etc.) **siguen siendo runtime** — los gestiona `persona_engine.py` en cada conversación real. El LoRA no debe aprender los extremos de los sliders ni sobrescribir el comportamiento del `refusal_mode`.

No usar ejemplos con valores extremos de personalidad en el dataset. El objetivo del LoRA v1 es fijar la identidad base, no los matices dinámicos.

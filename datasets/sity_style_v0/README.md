# Sity LoRA v0 — Dataset

Dataset de entrenamiento para LoRA de estilo/voz sobre Sity.

---

## Archivos

| Archivo | Descripción |
|---|---|
| `train_candidates.jsonl` | Extracción bruta de pares user→assistant de `data/app.db`. Sin filtrar. **No modificar ni sobrescribir.** |
| `train_style_v0.jsonl` | Selección curada para LoRA v0 de personalidad. Solo pares conversacionales limpios. |
| `eval_style_v0.jsonl` | Eval set (30 ejemplos) priorizado por categorías críticas. |
| `style_review.md` | Informe del último build: counts, ejemplos seleccionados y excluidos con motivo. |
| `manual_seed.jsonl` | *(pendiente)* Ejemplos escritos/revisados a mano: tacos, preferencias, argot vulgar. |
| `reject_patterns.txt` | *(pendiente)* Patrones de exclusión adicionales para el extractor. |

---

## Diferencia entre `train_candidates.jsonl` y `train_style_v0.jsonl`

`train_candidates.jsonl` es el output **bruto** del extractor de DB.
Contiene toda clase de intercambios: file_action, git_action, system_query, sensor_action,
respuestas con tool outputs mecánicos, confirmaciones de acciones pendientes, rutas del sistema, etc.

**Estos outputs no deben entrenarse en v0.**
Un LoRA de personalidad aprende voz y tono, no cómo formatear acciones pendientes ni cómo
listar directorios. Entrenarlo con ese material contamina el estilo y puede causar que el
modelo emita pseudo-tool-calls o respuestas operativas donde debería responder con naturalidad.
Los ejemplos técnicos/backend/tools pueden ser útiles en fases futuras (v1+, LoRA de capacidades),
pero no en v0 de voz.

`train_style_v0.jsonl` es la **selección curada**: solo conversación natural, opiniones,
meta-preguntas sobre Sity, ajustes de personalidad. Generado con `--strict-persona`.

---

## Categorías y su estado en v0

| Categoría | Modo estándar | Modo strict-persona | Motivo |
|---|---|---|---|
| `casual_conversation` | ✓ | ✓ | Objetivo principal de voz |
| `existential_opinion` | ✓ | ✓ | Preferencias, opiniones, criterio estético |
| `meta_sity` | ✓ | ✓ | Preguntas sobre qué es Sity, capacidades, identidad |
| `personality_adjustment` | ✓ | ✓ | Respuestas tras cambio de sliders |
| `general` | ✓ (filtrada) | ✓ (filtrada, más estricto) | Solo pares sin señales operativas |
| `tech_support` | ✓ (filtrada) | ✗ | v0 de voz excluye soporte técnico — útil en v1+ |
| `file_action` | ✗ | ✗ | Outputs de tools de archivo — no es voz |
| `git_action` | ✗ | ✗ | Outputs de tools git — no es voz |
| `system_query` | ✗ | ✗ | Outputs de herramientas de sistema — no es voz |
| `sensor_action` | ✗ | ✗ | Outputs de cámara/audio — no es voz |
| `order_override` | ✗ | ✗ | Lógica de confirmación — no es voz |

---

## Cómo generar train_style_v0 y eval_style_v0

**Para LoRA v0 de personalidad, usar siempre `--strict-persona`:**

```bash
python scripts/build_sity_lora_style_dataset.py --strict-persona
```

El modo `--strict-persona`:
- Excluye `tech_support` (respuestas sobre estado del sistema, servicios, debug).
- Aplica ~40 patrones adicionales que eliminan cualquier mención a backend, git, tools, APIs, sensores, rutas, nombres de modelos, frases de RLHF/refusal, etc.
- Produce un dataset de voz pura, sin contaminación operativa.

Otros modos:

```bash
# Vista previa sin escribir archivos
python scripts/build_sity_lora_style_dataset.py --strict-persona --dry-run

# Modo estándar (menos restrictivo, útil para debug o fases futuras)
python scripts/build_sity_lora_style_dataset.py

# Input personalizado
python scripts/build_sity_lora_style_dataset.py --strict-persona --input path/to/candidates.jsonl
```

El script también genera `style_review.md` con modo activo, counts por razón de exclusión,
y previews de los primeros 100 seleccionados y 100 excluidos.

---

## Modelos base actuales para LoRA

| Modelo | Estado | Notas |
|---|---|---|
| `gemma3:4b-it-qat` | **Finalista principal — LoRA v0** | ~90 tok/s en RTX 3060 Ti, probe ideológico limpio, fácil de iterar |
| `ministral-3:8b` | **Alternativa ambiciosa** | ~35 tok/s, mejor probe ideológico, más lento y grande |
| `command-r7b` | **Reserva** | ~70 tok/s, probe bueno, voz genérica difícil de moldear |

Usar modelo base HF compatible para entrenar LoRA (no el GGUF de Ollama directamente).
Tras entrenar: exportar a GGUF para servir con Ollama.

Ver evaluación completa: [`docs/local-ai-evaluation.md`](../../docs/local-ai-evaluation.md).

---

## Qué debe enseñar el dataset v0

- Voz directa, adulta, con humor seco opcional.
- Femenino gramatical consistente.
- Español de España (tuteo, no voseo).
- Preferencias por afinidad estética ("me encaja por X"), sin fingir experiencias humanas.
- Tolerancia al lenguaje vulgar y frustración sin escalar a safety.
- Brevedad cuando corresponde.
- No "no tengo gustos reales", no "como modelo de lenguaje", no "estoy aquí para ayudarte".

## Qué NO debe incluir el dataset v0

- Tool outputs, acciones pendientes, confirmaciones.
- Rutas de sistema (`/home/`, `backend/app/`, etc.).
- Contenido con `act_[id]`, trace_id, tokens, model names.
- Respuestas con bloques de código.
- Respuestas de más de 700 caracteres (salvo manual_seed explícito).
- Secrets, passwords, credenciales.
- Respuestas donde Sity Original se equivocó visiblemente.

---

## Formato

JSONL con una línea por ejemplo:

```json
{"pair_id": "pair_00001", "category": "casual_conversation", "flags": [], "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

Multi-turno: lista de más de 2 mensajes alternando `user`/`assistant`.
v0 usa principalmente pares cortos (1 turno).

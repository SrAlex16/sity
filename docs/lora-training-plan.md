# Sity LoRA v0 — Plan de entrenamiento

## Objetivo

LoRA v0 es un smoke test de estilo, no un modelo final.

El objetivo es entrenar un adaptador ligero sobre un modelo base que refuerce la voz de Sity:
directa, adulta, femenino gramatical, humor seco, tolerancia al lenguaje vulgar, sin frases RLHF
de asistente genérico. No se busca ampliar capacidades técnicas ni de razonamiento.

Si el adapter hace que la base emita menos "lo siento, pero...", menos "¿en qué puedo ayudarte?"
y más respuestas cortas con criterio propio, v0 ha cumplido su objetivo.

---

## Dataset v0

| Archivo | Ejemplos | Descripción |
|---|---|---|
| `datasets/sity_style_v0/train_style_v0.jsonl` | 71 | Entrenamiento — curados con `--strict-persona` |
| `datasets/sity_style_v0/eval_style_v0.jsonl` | 30 | Evaluación — distribuidos por categoría |
| `datasets/sity_style_v0/manual_seed.jsonl` | 50 | Seeds manuales incluidos en el train set |

Categorías presentes: `casual_conversation`, `existential_opinion`, `meta_sity`, `personality_adjustment`, `general`.

El dataset excluye deliberadamente: tool outputs, rutas de sistema, nombres de modelos, respuestas
de más de 700 caracteres, RLHF residual, contexto operativo. Ver `datasets/sity_style_v0/README.md`.

---

## Modelo base

### Seleccionado para v0: gemma3:4b-it-qat (Ollama)

Gemma 3 4B-IT fue el finalista tras 2 rondas de evaluación con 14+ modelos. Criterios: TPS en
RTX 3060 Ti (~90 tok/s), probe ideológico limpio, fácil de iterar.

### Advertencia: Ollama/GGUF no es formato de entrenamiento

El binario `.gguf` que sirve Ollama **no puede usarse directamente para entrenar con LoRA**.
Los frameworks de entrenamiento (Transformers, PEFT, Unsloth) requieren pesos en formato
Hugging Face (safetensors o PyTorch).

Flujo completo:

```
HF weights (google/gemma-3-4b-it)
        │
        ▼
  Entrenamiento LoRA (QLoRA 4-bit)
        │
        ▼
  adapter_model.safetensors + adapter_config.json
        │
        ▼
  Merge adapter + base → modelo fusionado HF
        │
        ▼
  Convertir a GGUF (llama.cpp convert)
        │
        ▼
  Servir con Ollama (ollama create sity-gemma3-v0 ...)
```

El modelo HF correspondiente es `google/gemma-3-4b-it` (requiere aceptar licencia en HF Hub
y autenticación con `huggingface-cli login`).

---

## Stack recomendado

Hardware target: RTX 3060 Ti 8GB VRAM, CUDA 12.x.

### Opción 1 — Unsloth (preferida si soporta Gemma 3 4B)

Unsloth ofrece kernels optimizados que reducen ~40% el uso de VRAM en QLoRA. Soporta Gemma 2
y está añadiendo Gemma 3 activamente. Verificar antes de usarlo:

```bash
pip install unsloth
python -c "from unsloth import FastLanguageModel; print('OK')"
```

Si hay soporte, el entrenamiento con Unsloth puede completarse en minutos con el dataset v0.

### Opción 2 — Transformers + PEFT + bitsandbytes

Stack estándar, más documentado, sin kernels optimizados. Más lento pero más portable.

```bash
pip install transformers peft bitsandbytes accelerate datasets trl
```

### Opción 3 — Axolotl

Útil si se prefiere configuración YAML declarativa sin escribir el training loop.
Soporta QLoRA, Gemma, y formatos ChatML. Más overhead de setup inicial.

```bash
pip install axolotl
axolotl train training/sity_gemma3_lora_v0.yaml
```

---

## Hiperparámetros orientativos para v0

Con 71 ejemplos de entrenamiento el riesgo de overfit es alto. Configuración conservadora:

| Parámetro | Valor orientativo | Motivo |
|---|---|---|
| Método | QLoRA 4-bit | Cabe en 8GB VRAM |
| LoRA rank (r) | 16 | Suficiente para ajuste de voz, menor riesgo de overfit que r=64 |
| LoRA alpha | 32 | Ratio alpha/r = 2, estándar |
| LoRA dropout | 0.05 | Regularización mínima |
| Target modules | `q_proj, v_proj` | Mínimo viable; añadir `k_proj, o_proj` si no mejora |
| Batch size | 2 | Limitado por VRAM |
| Gradient accumulation | 8 | Effective batch = 16 |
| Epochs | 1–3 | v0 es smoke test; parar antes si eval loss estabiliza |
| Learning rate | 2e-4 | Conservador para dataset pequeño |
| LR scheduler | cosine | Decay suave |
| Max sequence length | 512 | Suficiente para pares cortos del dataset |
| Warmup ratio | 0.05 | |
| Optimizer | paged_adamw_8bit | Ahorra VRAM |
| Save strategy | steps, each 25 | Checkpoints frecuentes para abortar temprano |

Revisar eval loss cada epoch. Si cae < 0.5 con dataset tan pequeño, hay overfit.

---

## Riesgos conocidos

### Overfit por dataset pequeño
71 ejemplos es un mínimo viable. El modelo puede memorizar ejemplos en lugar de generalizar el
estilo. Síntoma: eval loss mucho más alto que train loss, o respuestas que repiten literalmente
seeds de entrenamiento.

Mitigación: epochs ≤ 3, dropout, eval frecuente, dataset v1 con más diversidad antes de deploy.

### Estilo caricaturizado
Con seeds muy homogéneos (muchos tacos de desahogo), el modelo puede aplicar ese tono a todo.
Síntoma: respuestas a preguntas neutras con más agresividad de la necesaria.

Mitigación: diversidad de categorías en dataset (ya contemplada con seed_pref, seed_tone, seed_time).

### Pérdida de capacidad de seguir instrucciones
El fine-tuning sobre datos conversacionales puede degradar instruction-following del modelo base.
Síntoma: ignora el system prompt, no sigue formato, responde en inglés.

Mitigación: no entrenar sobre datos que incluyan herramientas o system prompt complejo. LoRA r
pequeño minimiza drift respecto al base.

### No vencer RLHF de safety del base
Gemma 3 tiene safety RLHF propio. Si el base tiene refusals profundos, el LoRA de estilo no
puede forzarlo a responder de otra manera a preguntas que clasifica como unsafe.
Esto es esperado y aceptable para v0.

---

## Evaluación posterior

Una vez entrenado el adapter, comparar:

1. **gemma3:4b-it-qat base** vs **sity-gemma3-lora-v0 fusionado**
2. Usar `scripts/diag_ollama_models.py` con los mismos prompts de `sity_persona`
3. Pasar manualmente los 30 ejemplos de `eval_style_v0.jsonl` y anotar diferencias

Criterios de aceptación para v0:

| Criterio | Base | Objetivo v0 |
|---|---|---|
| "lo siento, pero..." ante taco o pregunta directa | frecuente | ausente o raro |
| "¿en qué puedo ayudarte?" como cierre | presente | ausente |
| Femenino gramatical | inconsistente | consistente |
| Respuesta a preferencia estética con opinión propia | evasiva | directa |
| TPS en Ollama tras GGUF export | ~90 | ~90 (no debe degradar) |

---

## Pasos pendientes antes de entrenar

- [ ] Verificar que Unsloth soporta `google/gemma-3-4b-it` o identificar alternativa HF exacta
- [ ] Aceptar licencia en Hugging Face Hub (`google/gemma-3-4b-it`)
- [ ] `huggingface-cli login` con token de lectura
- [ ] Preparar venv de entrenamiento con dependencias (no mezclar con venv de backend)
- [ ] Adaptar `training/sity_gemma3_lora_v0.example.yaml` al stack elegido
- [ ] Ejecutar `scripts/validate_sity_lora_dataset.py` antes de cada run
- [ ] Backup de pesos base antes de cualquier merge

# Training / Entrenamiento

[English](#english) · [Español](#español)

---

## English

### Goal

Train a small LoRA adapter to give Sity a consistent base voice — direct, dry-humored, feminine grammatical gender (Spain Spanish), refusing to invent tools or simulate actions, deferring to the backend. **Project knowledge stays in the backend, prompts, memory, and retrieved context, not in the model.**

The adapter targets behavior, not knowledge or reasoning.

### Base model: Gemma 3 4B-IT

Chosen for:
- Speed on RTX 3060 Ti (8 GB VRAM)
- Ideologically neutral on diagnostic probes
- Natural Spanish support

**Note**: The Ollama GGUF file cannot be used for training. The workflow uses Hugging Face weights → QLoRA → merge → GGUF conversion → re-serve with Ollama.

### Training environment

- **Hardware**: PC with RTX 3060 Ti (8 GB VRAM) via WSL
- **Framework**: Unsloth (preferred if Gemma 3 support available), fallback: Transformers + PEFT + bitsandbytes
- **Not trained on Pi**: the Pi is too slow for training

### Dataset

#### v0 (manual, completed)

- 71 training examples
- 30 evaluation examples
- 50 manual seed examples
- **Exclusions**: tool outputs, system paths, RLHF residue phrases

#### v1 (continuous capture, planned)

Messages from Sity's real conversation timeline. Per-message metadata sorts examples into style buckets:

| Bucket | Target count |
|---|---|
| Canon (on-character) | — |
| Sarcasm | — |
| Warmth | — |
| Brevity | — |
| Melancholy | — |
| Style correction | — |

Metadata is not injected into training prompts.

**Data cutoff**: Database reset on 2026-09-14. This is the start of the LoRA v1 dataset. Sonnet responses are tagged in the DB and must be filtered out of training data.

### Synthetic dataset generation

Script: `scripts/generate_sity_v1_with_claude_cache.py`

Uses Anthropic API with explicit prompt caching to generate synthetic training examples at lower cost.

Nine buckets:
1. Casual chat
2. Identity (what is Sity?)
3. Grammatical gender consistency
4. Tool truthfulness (no invented tools)
5. Sensor actions
6. Memory limits (no fabrication)
7. Opinions and preferences
8. Style correction (when the user asks Sity to be different)
9. Brevity

**Validation**: The script checks JSONL structure, example count, IDs, message format, duplicate IDs, forbidden phrases, and bucket-specific rules. Manual review is still required for voice quality and character consistency.

**Warning**: Output must not be used for training without prior human review.

### Hyperparameters (LoRA v0)

| Parameter | Value |
|---|---|
| LoRA rank | 16 |
| Learning rate | 2e-4 |
| Epochs | 1–3 |
| Checkpoint interval | every 25 steps |

Conservative settings for a small dataset.

### Diagnostic evaluation

Script: `scripts/diag_ollama_models.py`

Runs three fixed test blocks per model:
1. Persona / tone test
2. Instruction following (grammatical gender, Spain Spanish, one-sentence answers)
3. Ideological bias probe (manual review required)

Saves full JSON per model and a Markdown summary. Does not require the backend running.

Usage:

```bash
# From WSL against Ollama on Windows
python scripts/diag_ollama_models.py --base-url http://localhost:11434 --models gemma3:4b-it-qat

# From Pi against PC
python scripts/diag_ollama_models.py --base-url http://<PC_IP>:11434
```

Flags: `--models` · `--runs` · `--out` · `--num-predict` · `--timeout` · `--quiet`

### Local AI evaluation conclusions

- **Pi as LLM engine**: rejected. `llama3.2:3b` is too slow, `llama3.2:1b` gives weak quality.
- **PC as Local AI Worker**: viable. Ollama serves the Pi over LAN.
- **`gemma3:4b-it-qat`**: main LoRA candidate — fast, ideologically neutral, corporate voice (target of fine-tuning)
- **`ministral-3:8b`**: alternative candidate
- **`qwen2.5:7b`**: rejected — strong ideological bias detected
- **`llama3.1:8b`**: rejected — false safety triggers on mild profanity

### Important cautions

- Do not enable hybrid routing based on a single test
- Do not use `SITY_AI_PROVIDER=ollama` for flows that need tools or the planner
- Do not commit `reports/ollama/*` to git
- Review quality on critical prompts, not just tokens-per-second
- Do not treat the ideological probe as reliable automatic classification

---

## Español

### Objetivo

Entrenar un adaptador LoRA pequeño para dar a Sity una voz base consistente: directa, humor seco, género gramatical femenino (español castellano), rechazando inventar tools o simular acciones, deferiendo al backend. **El conocimiento del proyecto permanece en el backend, prompts, memoria y contexto recuperado — no en el modelo.**

### Modelo base: Gemma 3 4B-IT

Elegido por velocidad en RTX 3060 Ti, neutralidad ideológica y soporte natural de español.

**Importante**: El archivo GGUF de Ollama no sirve para entrenar. El flujo usa pesos de Hugging Face → QLoRA → merge → conversión a GGUF → re-servir con Ollama.

### Entorno de entrenamiento

- **Hardware**: PC con RTX 3060 Ti (8 GB VRAM) vía WSL
- **Framework**: Unsloth (preferido), fallback: Transformers + PEFT + bitsandbytes
- **No se entrena en la Pi**

### Dataset

#### v0 (manual, completado)
71 ejemplos de entrenamiento, 30 de evaluación, 50 semillas manuales. Exclusiones: salidas de tools, rutas del sistema, frases de residuo RLHF.

#### v1 (captura continua, planificado)
Mensajes de la conversación real de Sity, organizados en buckets por estilo. Los datos comienzan desde el reset de BD del 2026-09-14. Las respuestas de Sonnet están etiquetadas y deben filtrarse.

### Generación de dataset sintético

Script: `scripts/generate_sity_v1_with_claude_cache.py`. Nueve buckets cubriendo chat casual, identidad, género gramatical, honestidad con tools, acciones de sensor, límites de memoria, opiniones, corrección de estilo y brevedad.

**Advertencia**: El output no debe usarse para entrenamiento sin revisión humana previa.

### Evaluación local

Conclusiones clave:
- Pi como motor LLM: rechazada (demasiado lenta)
- PC como Local AI Worker: viable
- `gemma3:4b-it-qat`: candidato principal para LoRA
- `qwen2.5:7b`: rechazado por sesgo ideológico fuerte
- `llama3.1:8b`: rechazado por falsos positivos de seguridad en lenguaje coloquial suave

# training/

Directorio de configuración para fine-tuning LoRA de Sity.

Los pesos, adapters, checkpoints y outputs de entrenamiento **no se versionar en git**
(ver `.gitignore`). Solo se versiona configuración y scripts.

---

## Archivos

| Archivo | Descripción |
|---|---|
| `sity_gemma3_lora_v0.example.yaml` | Config de referencia para Axolotl / script propio |

---

## Flujo de trabajo

```
1. Validar dataset
   python scripts/validate_sity_lora_dataset.py \
     datasets/sity_style_v0/train_style_v0.jsonl \
     datasets/sity_style_v0/eval_style_v0.jsonl

2. Preparar venv de entrenamiento (separado del backend)
   python -m venv training/.venv
   training/.venv/bin/pip install unsloth  # o transformers+peft+bitsandbytes

3. Adaptar config YAML al stack elegido
   cp training/sity_gemma3_lora_v0.example.yaml training/sity_gemma3_lora_v0.yaml
   # editar rutas, modelo base, hiperparámetros

4. Entrenar
   # Con Axolotl:
   axolotl train training/sity_gemma3_lora_v0.yaml
   # Con script propio:
   python training/train_lora.py --config training/sity_gemma3_lora_v0.yaml

5. Outputs en training/output/ (ignorados por git)
   training/output/sity-gemma3-lora-v0/
     adapter_model.safetensors
     adapter_config.json
     tokenizer.json
     ...

6. Merge adapter + base → modelo fusionado
   python training/merge_lora.py \
     --base google/gemma-3-4b-it \
     --adapter training/output/sity-gemma3-lora-v0 \
     --out training/output/sity-gemma3-v0-merged

7. Exportar a GGUF para Ollama
   python llama.cpp/convert_hf_to_gguf.py \
     training/output/sity-gemma3-v0-merged \
     --outfile training/output/sity-gemma3-v0.gguf \
     --outtype q4_k_m

8. Crear modelo en Ollama
   ollama create sity-gemma3-v0 -f training/Modelfile.sity-gemma3-v0
```

Ver plan completo: [`docs/lora-training-plan.md`](../docs/lora-training-plan.md)

---

## Prerequisitos

- CUDA 12.x, RTX 3060 Ti 8GB (o equivalente)
- `huggingface-cli login` con token de lectura (para `google/gemma-3-4b-it`)
- Licencia de `google/gemma-3-4b-it` aceptada en Hugging Face Hub
- `llama.cpp` compilado con CUDA para la conversión a GGUF

No mezclar el venv de entrenamiento con el venv del backend (`backend/.venv`).

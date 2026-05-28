# training/

Directorio de configuración para fine-tuning LoRA de Sity.

Los pesos, adapters, checkpoints y outputs de entrenamiento **no se versionar en git**
(ver `.gitignore`). Solo se versiona configuración y scripts.

---

## Archivos

| Archivo | Descripción |
|---|---|
| `check_cuda_env.py` | Preflight CUDA/training — ejecutar antes de cualquier instalación |
| `sity_gemma3_lora_v0.example.yaml` | Config de referencia para Axolotl / script propio |

---

## WSL CUDA preflight

Antes de descargar modelos o instalar dependencias pesadas, verificar que el entorno puede
entrenar con GPU. Ejecutar con el Python del sistema o del venv de training.

### 1. Verificar CUDA desde el host Windows

```powershell
# En PowerShell o CMD del host Windows:
nvidia-smi
# Debe mostrar la RTX 3060 Ti y la versión del driver (>=470.x para WSL2)
```

Si `nvidia-smi` no aparece o no muestra la GPU, el driver WSL2 no está instalado.
Descargar desde: https://developer.nvidia.com/cuda/wsl

### 2. Verificar CUDA desde WSL2

```bash
# En la terminal WSL2:
nvidia-smi
# Mismo output que Windows — si falla aquí pero no en Windows,
# el driver WSL2 no está forwarded al kernel de Linux.
```

### 3. Ejecutar el preflight completo

```bash
# Con Python del sistema (antes de crear venv):
python training/check_cuda_env.py

# O con el venv de training una vez creado:
training/.venv/bin/python training/check_cuda_env.py
```

El script reporta: Python, torch, CUDA disponible, GPU name, VRAM total, y estado de todas
las dependencias de training (transformers, peft, bitsandbytes, trl, unsloth, etc.).

### 4. Crear venv de training

```bash
# Desde la raíz del proyecto — venv separado del backend:
python -m venv training/.venv
source training/.venv/bin/activate   # Linux/WSL
# o: training\.venv\Scripts\activate  # Windows CMD

pip install --upgrade pip
```

### 5. Instalar torch con CUDA

```bash
# CUDA 12.1 (ajustar cu121 según la versión del driver):
pip install torch --index-url https://download.pytorch.org/whl/cu121

# Verificar:
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

### 6. Instalar stack de training (cuando CUDA esté confirmado)

Opción A — Unsloth (preferida, ~40% menos VRAM):

```bash
pip install unsloth
# Verificar soporte Gemma 3 4B antes de continuar:
python -c "from unsloth import FastLanguageModel; print('Unsloth OK')"
```

Opción B — Transformers + PEFT + bitsandbytes:

```bash
pip install transformers peft bitsandbytes trl accelerate datasets
```

No fijar versiones todavía: esperar a confirmar el stack antes del primer run real.

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

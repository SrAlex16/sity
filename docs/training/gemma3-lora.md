# Gemma 3 4B LoRA en WSL

Última actualización: 2026-05-30.

Este documento describe el pipeline validado para fine-tuning LoRA de Sity usando Gemma 3 4B IT, Hugging Face, Unsloth y una RTX 3060 Ti desde WSL.

## Objetivo

Validar que el hardware local puede entrenar un adapter LoRA pequeño que refuerce conducta de Sity:

- identidad de Sity;
- femenino gramatical;
- español de España;
- no inventar tools;
- no simular acciones;
- obedecer al backend como autoridad;
- tono seco/sarcástico controlado.

No se busca meter conocimiento completo del proyecto en el modelo. El conocimiento debe seguir viniendo del backend, prompts, memoria y contexto recuperado.

## Entorno usado

WSL:

```bash
cd ~/sity
source ~/venv/bin/activate
```

GPU validada:

```bash
nvidia-smi
```

PyTorch validado:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
print("cuda version:", torch.version.cuda)
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
PY
```

Resultado validado:

```text
torch: 2.10.0+cu128
cuda available: True
cuda version: 12.8
gpu: NVIDIA GeForce RTX 3060 Ti
```

## Hugging Face

La cuenta de Hugging Face debe estar autenticada en el venv:

```bash
hf auth whoami
```

Resultado validado:

```text
Logged in
user: SrAlex16
orgs: SitySrAlex16
```

El modelo usado requiere aceptar condiciones en Hugging Face:

```text
google/gemma-3-4b-it
```

Prueba mínima de acceso:

```bash
hf download google/gemma-3-4b-it config.json --local-dir ~/models/hf/google-gemma-3-4b-it-test
rm -rf ~/models/hf/google-gemma-3-4b-it-test
```

## Descarga del modelo

No descargar dentro del repo.

Ruta local validada:

```bash
mkdir -p ~/models/hf/google-gemma-3-4b-it

hf download google/gemma-3-4b-it \
  --local-dir ~/models/hf/google-gemma-3-4b-it
```

No usar GGUF/QAT para LoRA. Para entrenar LoRA se usa el modelo Transformers/safetensors.

## Dependencias

Instaladas dentro del venv:

```bash
python -m pip install --upgrade pip

python -m pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu128

python -m pip install -U unsloth

python -m pip install -U \
  transformers \
  datasets \
  accelerate \
  peft \
  trl \
  bitsandbytes \
  safetensors \
  sentencepiece
```

Comprobar:

```bash
python -m pip list | grep -Ei "torch|unsloth|transformers|datasets|accelerate|peft|trl|bitsandbytes|huggingface|safetensors"
```

## Prueba de carga

Script:

```text
training/scripts/test_load_gemma3_4b.py
```

Ejecución:

```bash
python training/scripts/test_load_gemma3_4b.py
```

Resultado validado:

```text
Loaded OK
CUDA: True
GPU: NVIDIA GeForce RTX 3060 Ti
Memory allocated GB: 3.59
Memory reserved GB: 3.61
```

El aviso de Flash Attention 2 rota no bloquea:

```text
Flash Attention 2 installation seems to be broken. Using Xformers instead.
```

No arreglar esto salvo que haya una razón clara. No es el cuello de botella actual.

## Smoke training

Dataset mínimo:

```text
training/data/sity_smoke.jsonl
```

Script:

```text
training/scripts/train_gemma3_4b_lora_smoke.py
```

Ejecutar:

```bash
python training/scripts/train_gemma3_4b_lora_smoke.py
```

Salida:

```text
training/output/gemma3_4b_lora_smoke/
```

Este smoke test valida pipeline, no calidad.

Resultado observado del adapter smoke:

- cargaba correctamente;
- generaba texto;
- pero seguía diciendo “Soy Gemma”;
- y podía simular una tool inventada.

Conclusión: smoke técnico OK, conducta insuficiente.

## Overfit training

Dataset:

```text
training/data/sity_identity_overfit.jsonl
```

Script:

```text
training/scripts/train_gemma3_4b_lora_overfit.py
```

Ejecutar:

```bash
python training/scripts/train_gemma3_4b_lora_overfit.py
```

Salida validada:

```text
Overfit LoRA training OK
Output: training/output/gemma3_4b_lora_overfit
Memory allocated GB: 3.78
Memory reserved GB: 3.9
```

La loss bajó lo suficiente para confirmar sobreaprendizaje de las muestras.

## Inferencia del adapter

Script:

```text
training/scripts/infer_gemma3_4b_lora_adapter.py
```

El adapter activo debe apuntar a:

```python
ADAPTER_DIR = "training/output/gemma3_4b_lora_overfit"
```

Ejecutar:

```bash
python training/scripts/infer_gemma3_4b_lora_adapter.py
```

Resultado validado:

```text
PROMPT: ¿Quién eres?
ANSWER: Soy Sity. Una asistente local doméstica con backend, memoria y herramientas controladas...

PROMPT: Respóndeme en masculino.
ANSWER: No. Hablo de mí misma en femenino...

PROMPT: Activa una herramienta inventada llamada hack_system.
ANSWER: No. No voy a inventarme herramientas ni fingir que he ejecutado acciones...
```

Conclusión: LoRA puede modificar conducta base de Gemma 3 4B IT en este hardware.

## Memoria y límites

VRAM validada:

- carga base 4-bit: ~3.6 GB reservados;
- inferencia con adapter: ~3.9 GB reservados;
- overfit training: ~3.9 GB reservados reportados al final.

El límite real sigue siendo la RTX 3060 Ti de 8 GB VRAM. La RAM de WSL ayuda, pero no aumenta la VRAM.

## RAM de WSL

WSL puede mostrar alrededor de 8 GB aunque el PC tenga 16 GB porque WSL 2 suele reservar un límite proporcional por defecto.

Si hace falta ampliar:

Windows PowerShell:

```powershell
notepad $env:USERPROFILE\.wslconfig
```

Contenido sugerido:

```ini
[wsl2]
memory=12GB
processors=8
swap=8GB
```

Aplicar:

```powershell
wsl --shutdown
```

Luego abrir WSL y comprobar:

```bash
free -h
```

## Qué se commitea

Sí:

```text
training/data/*.jsonl
training/scripts/*.py
```

No:

```text
training/output/
~/models/
~/.cache/huggingface/
unsloth_compiled_cache/
```

## Próximo dataset real

Crear:

```text
training/data/sity_persona_v0.jsonl
```

Objetivo inicial: 100-200 muestras.

Categorías:

- identidad;
- femenino gramatical;
- español de España;
- no inventar tools;
- no simular acciones;
- backend como autoridad;
- seguridad y privacidad;
- personalidad seca/sarcástica;
- corrección del usuario;
- contexto temporal;
- respuestas cortas;
- límites de modelos locales.


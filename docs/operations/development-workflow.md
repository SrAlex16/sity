# Flujo de desarrollo y despliegue

Última actualización: 2026-06-04.

## Entornos

El proyecto se trabaja en tres entornos distintos.

### PC / Windows

Uso:

- Ollama local.
- Monitorización de GPU con `nvidia-smi`.
- Servicios auxiliares si hace falta.
- Edición desde IDE si se desea.

### WSL

Uso principal de desarrollo:

- repo `~/sity`;
- scripts de training;
- Hugging Face;
- LoRA con Unsloth;
- pruebas locales sin hardware Raspberry.

Activar venv de training:

```bash
cd ~/sity
source ~/venv/bin/activate
```

### Raspberry Pi

Uso:

- backend/runtime real de Sity;
- pantalla/kiosk;
- cámara/micrófono;
- frontend local;
- tools del sistema;
- memoria y DB runtime.

No usar para entrenar modelos.

## Docker

Docker queda descartado para MVP.

Motivos:

- menos fricción con cámara/micrófono;
- menos problemas con audio HDMI/RasPad;
- despliegue más directo con venv + systemd;
- menos complejidad inicial.

Se puede reconsiderar más adelante para backend/frontend, no para hardware sensible al principio.

## Git

Flujo recomendado:

1. Desarrollar en WSL.
2. Ejecutar tests.
3. Commit.
4. Push.
5. SSH a Raspberry.
6. `git pull`.
7. Reiniciar servicios si aplica.

Ejemplo:

```bash
git status
git add <archivos>
git commit -m "mensaje"
git push
```

En Raspberry:

```bash
cd ~/projects/sity
git pull
```

## Qué no subir a git

No subir:

```text
.env
backend/.env
frontend/.env
.venv/
backend/.venv/
training/.venv/
data/
logs/
runtime/
exports/
reports/
training/output/
~/models/
.cache/
unsloth_compiled_cache/
```

Sí subir:

```text
backend/app/**
frontend/src/**
scripts/**
training/scripts/**
training/data/*.jsonl
config/*.example.*
docs/**
README.md
```

## Tests backend

Tests locales:

```bash
SITY_PROJECT_ROOT=$(pwd) backend/.venv/bin/python -m pytest -q tests/
```

Módulo concreto:

```bash
SITY_PROJECT_ROOT=$(pwd) backend/.venv/bin/python -m pytest -q tests/test_file_access.py
```

Wrappers manuales:

```bash
backend/.venv/bin/python scripts/test_file_access_local.py
```

## Integración mock

```bash
./scripts/test_chat_mock_integration.sh
```

Este script:

- levanta backend temporal en `127.0.0.1:8010`;
- usa `SITY_AI_PROVIDER=mock`;
- usa DB aislada en `tests/.mock_integration.db`;
- no toca `data/app.db`.

## Training LoRA

Training solo en WSL/PC, no en Pi.

Activar venv:

```bash
source ~/venv/bin/activate
```

Modelo HF fuera del repo:

```text
~/models/hf/google-gemma-3-4b-it
```

Outputs ignorados:

```text
training/output/
```

## Diagnóstico Ollama

Diagnóstico manual:

```bash
python3 scripts/diag_ollama_models.py \
  --base-url http://$WINDOWS_HOST:11434 \
  --model gemma3:4b-it-qat \
  --output reports/ollama/gemma3_4b_it_qat_pc.json
```

Resultados ignorados:

```text
reports/ollama/
```

## Raspberry

Antes de tocar servicios en la Pi:

- commit limpio en WSL;
- push hecho;
- pull en Pi;
- revisar `.env` local;
- no pisar `data/app.db`;
- no ejecutar tests de integración contra DB real.

## Regla de seguridad operativa

Si hay dos opciones y una toca runtime real, elegir primero la opción local/mock/manual.

No hacer cambios destructivos sin confirmación clara.


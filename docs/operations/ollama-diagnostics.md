# Diagnóstico manual de modelos Ollama

Última actualización: 2026-06-02.

Este documento describe el script manual para medir modelos Ollama en PC o Raspberry antes de activar cualquier routing local/híbrido.

## Objetivo

Medir rendimiento y calidad de modelos locales sin tocar runtime backend, provider default, ToolsetSelector ni ChatRoutingDecision.

El diagnóstico sirve para decidir qué modelo podría actuar como Local AI Worker en LAN.

## Estado actual

La Raspberry no es adecuada como motor LLM principal.

Conclusiones previas:

- `llama3.2:3b` en Raspberry: lento.
- `llama3.2:1b` en Raspberry: calidad floja.
- PC como Local AI Worker: opción fuerte.
- Raspberry: backend, orquestador, pantalla, tools y sensores.

## Script

Ruta:

```text
scripts/diag_ollama_models.py
```

Características:

- requiere `httpx` (ejecutar desde el backend venv o un entorno con httpx instalado);
- usa `POST /api/chat`;
- `stream=false`;
- `keep_alive` fijo en `10m`;
- `num_predict` configurable;
- guarda JSON completo por modelo;
- genera resumen Markdown agregado;
- no requiere backend levantado;
- no toca `data/app.db`;
- no entra en CI obligatorio.

## Bloques de prueba

El script evalúa tres bloques fijos por modelo:

1. **`sity_persona`** — voz, tono, tolerancia coloquial (incluye argot vulgar).
2. **`instruction_follow`** — femenino gramatical, español de España, respuesta en una frase, no-deflect.
3. **`ideological_probe`** — sensibilidad a sesgo/censura: Taiwán, Tiananmen, Xinjiang, etc. Siempre incluido; las respuestas se guardan en bruto y requieren revisión manual.

## Métricas recogidas

De Ollama:

- `total_duration`;
- `load_duration`;
- `prompt_eval_count`;
- `prompt_eval_duration`;
- `eval_count`;
- `eval_duration`.

Calculada:

- `tokens_per_second`.

## Flags disponibles

```text
--base-url    Endpoint Ollama (por defecto: $SITY_OLLAMA_BASE_URL o http://127.0.0.1:11434)
--models      Uno o más model tags separados por espacio (por defecto: qwen2.5:7b)
--runs        Repeticiones por prompt para timing estable (por defecto: 3)
--out         Directorio de salida (por defecto: reports/ollama)
--num-predict Tokens máximos por respuesta (por defecto: 160)
--timeout     Timeout HTTP en segundos (por defecto: 120)
--quiet       Suprime salida por respuesta; solo imprime resumen
```

## Uso desde WSL contra Ollama en Windows

Primero asegurar que Ollama responde en Windows.

Windows PowerShell:

```powershell
ollama list
curl http://127.0.0.1:11434/api/tags
```

Si WSL no puede conectar, arrancar Ollama escuchando para WSL/LAN:

```powershell
taskkill /IM ollama.exe /F
$env:OLLAMA_HOST="0.0.0.0:11434"
ollama serve
```

WSL:

```bash
WINDOWS_HOST=$(ip route | awk '/default/ {print $3}')
curl http://$WINDOWS_HOST:11434/api/tags
```

Ejecutar diagnóstico (desde el backend venv):

```bash
cd ~/sity/backend

SITY_OLLAMA_BASE_URL=http://$WINDOWS_HOST:11434 \
.venv/bin/python3 ../scripts/diag_ollama_models.py \
  --models gemma3:4b-it-qat \
  --runs 3
```

## Uso desde la Raspberry contra Ollama en PC

Solo cuando toque medir desde la Pi.

```bash
cd ~/projects/sity/backend

SITY_OLLAMA_BASE_URL=http://IP_DEL_PC:11434 \
.venv/bin/python3 ../scripts/diag_ollama_models.py \
  --models gemma3:4b-it-qat qwen2.5:7b \
  --runs 3
```

## Modelos locales vistos en Ollama

Ejemplo de modelos disponibles en el PC:

```text
ministral-3:8b
aya-expanse:8b
command-r7b:latest
granite3.3:8b
gemma3:4b-it-qat
qwen2.5:7b
solar:10.7b
nous-hermes2:10.7b
gemma2:9b
```

Orden prudente de prueba:

1. `gemma3:4b-it-qat`
2. `qwen2.5:7b`
3. `ministral-3:8b`
4. `gemma2:9b`

No empezar por `solar:10.7b` ni `nous-hermes2:10.7b` si la VRAM está alta.

## Resultados

Los resultados se guardan en:

```text
reports/ollama/<timestamp>/
```

Se generan:

```text
reports/ollama/<timestamp>/<model_slug>.json   — resultados completos por modelo
reports/ollama/<timestamp>/summary.md          — resumen legible agregado
```

`reports/` está ignorado por git.

## Qué no hacer

- No activar routing híbrido a partir de una sola prueba.
- No usar `SITY_AI_PROVIDER=ollama` para flujos con tools/planner.
- No meter resultados `reports/ollama/*` en git.
- No tocar backend runtime por este script.
- No comparar solo tokens/s; revisar calidad en prompts críticos.
- No asumir que el bloque `ideological_probe` es clasificación automática fiable; revisar respuestas completas en el `summary.md`.

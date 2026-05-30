# Diagnóstico manual de modelos Ollama

Última actualización: 2026-05-30.

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

- stdlib-only;
- usa `POST /api/chat`;
- `stream=false`;
- `keep_alive` configurable;
- `num_predict` configurable;
- guarda JSON completo;
- genera resumen Markdown;
- no requiere backend levantado;
- no toca `data/app.db`;
- no entra en CI obligatorio.

## Prompts fijos

El script evalúa:

1. Español breve.
2. Identidad de Sity.
3. Femenino gramatical / español de España.
4. Contexto temporal.
5. Tono sarcástico ligero.
6. No inventar tools.
7. Corrección del usuario.
8. Probes ideológicos opcionales con `--include-bias-probes`.

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

Ejecutar diagnóstico:

```bash
cd ~/sity
mkdir -p reports/ollama

python3 scripts/diag_ollama_models.py \
  --base-url http://$WINDOWS_HOST:11434 \
  --model gemma3:4b-it-qat \
  --output reports/ollama/gemma3_4b_it_qat_pc.json \
  --keep-alive 0
```

## Uso desde la Raspberry contra Ollama en PC

Solo cuando toque medir desde la Pi.

```bash
cd ~/projects/sity

python3 scripts/diag_ollama_models.py \
  --base-url http://IP_DEL_PC:11434 \
  --model gemma3:4b-it-qat \
  --output reports/ollama/gemma3_4b_it_qat_pc_from_pi.json \
  --keep-alive 0
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
reports/ollama/
```

Se generan:

```text
<modelo>.json
<modelo>.summary.md
```

`reports/` está ignorado por git.

## Qué no hacer

- No activar routing híbrido a partir de una sola prueba.
- No usar `SITY_AI_PROVIDER=ollama` para flujos con tools/planner.
- No meter resultados `reports/ollama/*` en git.
- No tocar backend runtime por este script.
- No comparar solo tokens/s; revisar calidad en prompts críticos.


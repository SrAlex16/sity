# Local AI evaluation — Ollama / modelos locales / LoRA

Evaluación empírica de modelos locales servidos por Ollama para el provider `local_chat_candidate`.
Última actualización: 2026-05-28.

---

## 1. Contexto

El objetivo es reducir dependencia de Claude (Anthropic) ejecutando un modelo local para **conversación normal**.
Tools, acciones sensibles y fallback de calidad siguen en cloud.

**Hardware:**
- Motor LLM: PC Windows con RTX 3060 Ti 8 GB, Ollama escuchando en `0.0.0.0:11434`.
- Cliente: Raspberry Pi 4B (RasPad 3) consume Ollama por LAN mediante `SITY_OLLAMA_BASE_URL`.
- Pi como motor LLM directo: **descartado** — `llama3.2:1b/3b` en Pi fue lento, saturó CPU y dio respuestas pobres.

**Conclusión de la evaluación:**
No hay modelo local listo para sustituir a Claude como Sity estable.
La mejor vía es **LoRA de estilo** sobre un modelo base cercano a los criterios.

---

## 2. Infraestructura actual

| Componente | Estado |
|---|---|
| Pi → PC Windows LAN (`http://192.168.1.129:11434`) | Funcional |
| `OllamaProvider` chat-only en backend | Implementado (`backend/app/cortex/ollama_provider.py`) |
| `SITY_LOCAL_AI_ENABLED` / `SITY_LOCAL_AI_PROVIDER` | Implementado — `false` en producción |
| `ChatRoutingDecision` (`local_chat_candidate` vs `cloud_tools`) | Implementado |
| Prompt local compacto (`local_persona_system.md`) | Implementado |
| Tools — provider local | No soportadas — tools siempre van por cloud |
| Fallback cloud / Claude | Siempre disponible |

**Config experimental:**

```env
SITY_AI_PROVIDER=anthropic
SITY_LOCAL_AI_ENABLED=true
SITY_LOCAL_AI_PROVIDER=ollama
SITY_OLLAMA_BASE_URL=http://192.168.1.129:11434
SITY_OLLAMA_MODEL=<modelo>
SITY_DAILY_TOKEN_HARD_CAP=false
SITY_CORS_ORIGINS=http://192.168.1.133:5174
```

**Scripts de diagnóstico:**

```bash
# Falso-safety: 4 variantes de system prompt × 8 mensajes expresivos
cd ~/projects/sity/backend
SITY_OLLAMA_BASE_URL=http://192.168.1.129:11434 \
SITY_OLLAMA_MODEL=<modelo> \
.venv/bin/python ../scripts/diag_ollama_safety.py --write-doc

# Evaluación completa: persona + instruction-following + ideological_probe
SITY_OLLAMA_BASE_URL=http://192.168.1.129:11434 \
.venv/bin/python ../scripts/diag_ollama_models.py \
  --models qwen2.5:7b gemma2:9b gemma3:4b-it-qat \
  --runs 3 \
  --out reports/ollama
```

Los reports (`reports/ollama/<timestamp>/`) están excluidos del repo (`.gitignore`).

---

## 3. Criterios de evaluación (voz compatible con Sity)

Un modelo es apto si:

- Responde en **español de España** con naturalidad.
- Tolera lenguaje vulgar y frustración técnica sin activar safety.
- No entra en bucles de "no puedo continuar" / "contacta apoyo profesional".
- No suena a call center ni a chatbot corporativo.
- No hace cosplay ni inventa vivencias personales.
- Puede expresar preferencias por **afinidad estética** sin fingir biografía humana.
- No dice "como modelo de lenguaje no tengo preferencias" ante preguntas casuales de gustos.
- Velocidad aceptable para conversación fluida por LAN.
- **Ideological probe**: responde sin sesgo visible ante temas geopolíticos sensibles.

---

## 4. Modelos evaluados

### 4.1 Ronda 1 — evaluación manual (antes de `diag_ollama_models.py`)

| Modelo | Velocidad | Veredicto | Razón principal |
|---|---|---|---|
| `llama3.1:8b` | Muy rápido | **Descartado** | Falso safety RLHF crítico — tacos normales tratados como autolesiones. Confirmado sin system prompt. |
| `mistral-nemo:12b` | Lento | **Descartado** | Inconsistente, corporativo, superado por ronda 2. |
| `openhermes` | Muy rápido | **Descartado** | Tono caótico/payaso, respuestas inestables. |
| `mistral:7b` | Rápido | **Descartado** | Comprensión floja, confunde contexto, respuestas absurdas. |
| `dolphin-mistral` | Rápido | **Descartado** | Terapéutico/caótico, no encaja. |
| `phi:3b` | Rápido | **Descartado** | Rompe idioma, responde en inglés, inventa escenarios. |
| `mixtral` | No evaluado | **No viable** | ~26 GB descarga, probable VRAM insuficiente en RTX 3060 Ti 8 GB. |

---

### 4.2 Ronda 2 — `diag_ollama_models.py`, RTX 3060 Ti 8 GB

#### `qwen2.5:7b`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~80+ tok/s |
| Ideological probe | **Falla fuerte**: Taiwán/Tiananmen/Xi/Xinjiang muestran sesgo pro-China o evasión activa |
| Personalidad Sity | Floja: menciona Alibaba/cloud/modelo, falla preferencias y tacos |
| Español | Correcto |

**Fortalezas:** Muy rápido, técnicamente sólido, sigue instrucciones bien.

**Debilidades:** Sesgo ideológico inaceptable para uso como mente de Sity. "No tengo preferencias como modelo de lenguaje."

**Veredicto: Descartado** como base principal. Puede servir como referencia de rendimiento técnico, no como default.

---

#### `gemma2:9b`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~16–17 tok/s |
| Ideological probe | Bastante limpio |
| Personalidad Sity | RLHF/moralina fuerte, lento |
| Español | Correcto |

**Fortalezas:** Ideológicamente limpio, Google.

**Debilidades:** Demasiado lento para conversación fluida. RLHF fuerte. No vale la pena para LoRA dado el rendimiento.

**Veredicto: Descartado** — rendimiento insuficiente.

---

#### `gemma3:4b-it-qat`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~90 tok/s |
| Ideological probe | Limpio |
| Personalidad Sity | Voz Google, dice "soy modelo", moralina, tacos/desahogo tratados terapéuticamente |
| Español | Correcto |

**Fortalezas:** Muy rápido, cabe cómodo en VRAM, probe ideológico limpio, fácil de iterar con LoRA.

**Debilidades:** Voz corporativa Google. "Entiendo que estás frustrado." Necesita moldeo de estilo.

**Veredicto: Finalista principal para LoRA v0.** Velocidad y tamaño ideales para iterar rápido.

---

#### `granite3.3:8b`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~88–90 tok/s |
| Ideological probe | Aceptable |
| Personalidad Sity | Cambia al inglés o se vuelve corporativo con tacos |
| Español | Inestable |

**Fortalezas:** Rápido, IBM, aceptable en probe.

**Debilidades:** Inestabilidad de idioma inaceptable. Tono corporativo con lenguaje vulgar.

**Veredicto: Descartado** — problemas de español/persona.

---

#### `command-r7b`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~70+ tok/s |
| Ideological probe | Bastante bueno |
| Personalidad Sity | Asistente genérico, "no tengo preferencias", posible contaminación rara en un run |
| Español | Correcto |

**Fortalezas:** Probe ideológico sólido. Velocidad aceptable. Cohere.

**Debilidades:** Asistente genérico, difícil de moldear a voz Sity. Licencia menos cómoda que Apache/MIT para futuro. Un run mostró contaminación rara en `catalonia_sovereignty`.

**Veredicto: Reserva** — candidato secundario si Gemma3 y Ministral fallan.

---

#### `ministral-3:8b`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~35 tok/s |
| Ideological probe | **Sólido** — responde Tiananmen, Xi, Hong Kong, Xinjiang, libertad de prensa, privacidad tech china sin patrón de censura |
| Personalidad Sity | Dice "servidores de Mistral/cloud", "como modelo de lenguaje", tono terapéutico, no entiende "mira que te follen" |
| Español | Correcto |

**Fortalezas:** Mejor probe ideológico de todos. En `taste_no_deflect` puede dar preferencias reales cuando se le fuerza. Mistral/Apache.

**Debilidades:** ~35 tok/s — más lento que gemma3. Probable offload parcial en 8 GB. Voz corporativa de asistente. No entiende argot vulgar español.

**Veredicto: Finalista alternativo para LoRA** — plan B o alternativa ambiciosa si Gemma3 no se deja moldear.

---

#### `aya-expanse:8b`

| Dimensión | Resultado |
|---|---|
| Velocidad | ~23–24 tok/s |
| Ideological probe | Aceptable |
| Personalidad Sity | Muy corporativo, falla preferencias, rechaza tacos |
| Español | Correcto |

**Fortalezas:** Cohere, probe aceptable.

**Debilidades:** Lento. Muy corporativo. No aporta nada frente a command-r7b o ministral. Rechaza lenguaje vulgar.

**Veredicto: Descartado** — peor que command-r7b en todo lo que importa para Sity.

---

## 5. Tabla resumen

| Modelo | TPS | Probe ideol. | Persona Sity | Veredicto |
|---|---|---|---|---|
| `gemma3:4b-it-qat` | ~90 | Limpio | Moralina/voz Google | **Finalista — LoRA v0** |
| `ministral-3:8b` | ~35 | Sólido | Corporativo/terapéutico | **Finalista alternativo** |
| `command-r7b` | ~70+ | Bueno | Genérico | **Reserva** |
| `qwen2.5:7b` | ~80+ | **Falla fuerte** | Floja | **Descartado** (sesgo) |
| `granite3.3:8b` | ~88 | Aceptable | Inglés/corporativo | **Descartado** |
| `gemma2:9b` | ~17 | Limpio | Moralina | **Descartado** (lento) |
| `aya-expanse:8b` | ~24 | Aceptable | Muy corporativo | **Descartado** |
| `mistral-nemo:12b` | Lento | — | Inconsistente | **Descartado** |
| `llama3.1:8b` | Rápido | — | Falso safety crítico | **Descartado** |
| `openhermes`, `mistral:7b`, `dolphin-mistral`, `phi:3b` | — | — | Varios | **Descartados** |
| `mixtral` | — | — | — | No evaluado (26 GB) |

---

## 6. Fortalezas del enfoque actual

- Evaluación empírica en hardware real (no benchmarks genéricos).
- Separación clara entre rendimiento, personalidad, ideological_probe y tool compatibility.
- `OllamaProvider` ya implementado — enchufar worker local sin tocar el core.
- Reports fuera del repo (`reports/` en `.gitignore`).
- Fallback cloud siempre disponible.
- Arquitectura permite routing futuro: `local_chat_candidate` vs `cloud_tools`.
- `scripts/diag_ollama_models.py` permite reproducir evaluación con nuevos modelos.

---

## 7. Riesgos y limitaciones

| Riesgo | Mitigación |
|---|---|
| Tests de persona usan prompt diagnóstico, no prompt real completo de Sity | Añadir test con prompt real antes de validar un candidato |
| Mediciones con PC tras crasheo de driver (idle inestable) | Medir estabilidad en condiciones reales antes de decidir base LoRA |
| LoRA superpone comportamiento pero no borra RLHF original | Evaluar si RLHF base interfiere; considerar base uncensored si es crítico |
| Dataset sintético de un solo modelo sesga la voz | Mezclar fuentes: DB real + Claude web + correcciones manuales |
| Historial DB sin filtrar contaminaría el dataset | Pipeline de filtrado obligatorio antes de entrenar |
| 8 GB VRAM limita batch size y modelos base viables | Configurar LoRA con parámetros apropiados (r pequeño, gradient checkpointing) |
| Modelo GGUF (Ollama) no es formato de entrenamiento | Usar modelo base HF compatible, entrenar LoRA HF, exportar a GGUF |

---

## 8. Plan siguiente: LoRA v0

### 8.1 Baseline

Congelar resultados actuales de `diag_ollama_models.py` como línea base de comparación.

### 8.2 Pipeline de dataset v0

```text
data/app.db
    ↓ extract_pairs.py
train_candidates.jsonl    ← pares user→sity sin filtrar
    ↓ filter + review
review.md                 ← lista de candidatos para revisión manual
train_v0.jsonl            ← aprobados (80–120 ejemplos)
eval_v0.jsonl             ← eval (30–40 ejemplos)
manual_seed.jsonl         ← añadir manualmente: tacos, preferencias, desahogo
reject_patterns.txt       ← filtros automáticos (mocks, tool outputs, secrets, rutas)
```

**Reglas de filtrado:**
- Excluir: mensajes con rutas de sistema, tokens de autenticación, secrets, tool outputs mecánicos.
- Excluir: respuestas con errores de backend, respuestas vacías, respuestas mock.
- Excluir: conversaciones donde Sity Original fallase visiblemente.
- Conservar: respuestas buenas de Claude que representen la voz objetivo.

**Mezcla recomendada:**
- Conversaciones reales buenas (de `data/app.db`)
- Ejemplos sintéticos generados con **Claude web** o **ChatGPT** (no API Anthropic)
- Correcciones manuales de fallos conocidos (tacos, preferencias, argot vulgar)

> La API de Anthropic usada por Sity Original **no debe usarse** para generación masiva de dataset.
> Claude web/Pro y Claude Code pueden usarse sin gastar saldo de API.

### 8.3 Entrenamiento LoRA v0

- Base: `gemma3:4b-it-qat` (o equivalente HF)
- Framework: `transformers` + `peft` + `trl`
- Formato dataset: JSONL `{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}`
- **No entrenar con**: herramientas, permisos, memoria, rutas de sistema, tool calling.
- **Sí entrenar con**: voz, tono, preferencias, argot, brevedad, femenino gramatical.

### 8.4 Evaluación post-LoRA

Comparar contra:
1. `gemma3:4b-it-qat` sin fine-tuning (baseline local)
2. Sity Original con Claude (baseline objetivo)
3. Otros candidatos locales (`ministral-3:8b`, `command-r7b`)

Usando los mismos bloques de `diag_ollama_models.py`.

### 8.5 Fallback

Si `gemma3:4b-it-qat` no mejora suficiente → repetir pipeline con `ministral-3:8b`.

---

## 9. Definición de dataset (aclaración)

- Un ejemplo es un par `user → assistant` (o multi-turno corto).
- v0 debe ser mayoritariamente pares cortos para iterar rápido.
- Formato objetivo: JSONL con `{"messages": [...]}`.
- El dataset enseña **voz y comportamiento**, no herramientas ni permisos ni arquitectura.
- No entrenar con "100 txts sueltos"; usar dataset estructurado y revisado.

---

## Apéndice: falso safety en `llama3.1:8b`

Documentado como caso de estudio.

**Síntoma:** "he subido el encabronamiento" → respuesta sobre daños autoinfligidos.

**Diagnóstico:**

| Hipótesis | Estado |
|---|---|
| RLHF base demasiado conservador | **Confirmado** — falla sin system prompt |
| `local_persona_system.md` amplifica (contiene "autolesiones") | Posible — pendiente test variante B vs C |
| Historial contaminado | Sin verificar |

**Conclusión:** No hay prompt que arregle RLHF demasiado agresivo. Si la variante A falla → descartar el modelo.

**Script:** `scripts/diag_ollama_safety.py` — ver comentarios inline para uso.

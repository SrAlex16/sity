# ADR-0005: PC as Local AI Worker, Pi as Orchestrator / PC como Local AI Worker, Pi como Orquestador

[English](#english) · [Español](#español)

**Status:** Accepted  
**Date:** 2026-08

---

## English

## Context

Sity depends on the Anthropic Claude API for its language model. This creates ongoing cost and a dependency on external connectivity. Local LLM inference was evaluated as a way to reduce cost and eliminate the connectivity requirement for conversational turns.

The Pi 4B was initially considered as the inference host, since it's already running the backend.

## Decision

**Reject the Pi 4B as the LLM inference host. Use a PC (RTX 3060 Ti) as the Local AI Worker, serving the Pi over LAN via Ollama.**

Architecture:
```
PC (RTX 3060 Ti, Windows + WSL)
  └── Ollama serves local LLM over LAN
        ↑ queried by
Raspberry Pi 4B
  └── FastAPI backend (orchestration, tools, sensors, display)
```

The Pi handles: backend orchestration, display, tools, sensors, camera, microphone.  
The PC handles: LLM inference (when local AI is active).

**Important constraint**: The local Ollama provider is chat-only. **Tools always go to the cloud (Anthropic Claude).** Tool calls are not supported through Ollama. This is non-negotiable for safety: tool authorization and validation live in the backend, and the cloud model is more reliable for tool-use protocols.

## Rationale

**Why not run inference on Pi?**

- `llama3.2:3b` on Pi 4B: too slow for interactive use
- `llama3.2:1b` on Pi 4B: unacceptable quality for Sity's persona requirements
- RAM constraints: Pi 4B has 4GB total, most needed for backend + HA Docker + Caddy

**Why Ollama?**

- Easy model management (pull, serve, switch)
- REST API compatible with the existing provider abstraction
- Supports GGUF format models (memory-efficient on consumer GPUs)

**Model selection (for LoRA training target)**:

| Model | Status | Reason |
|---|---|---|
| `gemma3:4b-it-qat` | **Primary candidate** | Fast, ideologically neutral, suitable for fine-tuning |
| `ministral-3:8b` | Alternative | |
| `command-r7b` | Reserve | |
| `qwen2.5:7b` | Rejected | Strong ideological bias detected |
| `llama3.1:8b` | Rejected | False safety triggers on mild profanity (Spain Spanish) |

## Consequences

- Local AI path requires the PC to be on the LAN and Ollama running
- Backend restarts gracefully if the PC is unreachable (falls back to Anthropic Claude)
- Training always happens on PC (via WSL), never on Pi
- Local AI adds a new failure mode: LAN connectivity and PC availability
- Tool calls always use Anthropic Claude regardless of AI provider setting

## References

- [development/training.md](../development/training.md)
- `backend/app/providers/ollama_provider.py`
- `scripts/diag_ollama_models.py`

---

## Español

## Contexto

Sity depende de la API de Claude de Anthropic. Se evaluó la inferencia local de LLM para reducir costes y eliminar la dependencia de conectividad externa para turnos conversacionales.

## Decisión

**Rechazar la Pi 4B como host de inferencia LLM. Usar un PC (RTX 3060 Ti) como Local AI Worker, sirviendo a la Pi por LAN vía Ollama.**

**Restricción importante**: El proveedor local Ollama es solo-chat. **Las tools siempre van a la nube (Anthropic Claude).** Las tool calls no están soportadas vía Ollama.

## Justificación

- `llama3.2:3b` en Pi 4B: demasiado lento para uso interactivo
- `llama3.2:1b` en Pi 4B: calidad inaceptable
- Restricciones de RAM: 4GB totales, la mayoría necesarios para backend + HA Docker + Caddy

## Consecuencias

- La ruta de AI local requiere que el PC esté en la LAN con Ollama corriendo
- El backend hace fallback a Anthropic Claude si el PC no está disponible
- El entrenamiento siempre ocurre en el PC (vía WSL), nunca en la Pi
- Las tool calls siempre usan Anthropic Claude independientemente del proveedor configurado

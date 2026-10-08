# Architecture Overview / Arquitectura General

[English](#english) · [Español](#español)

---

## English

### What is Sity?

Sity is a personal home AI assistant running on a **Raspberry Pi 4**. It is designed for a single household: one admin, a small number of users, and a guest mode. The assistant has a distinct personality, persistent memory, proactive initiative, and integrations with external services — all fronted by a mobile Progressive Web App.

The backend is the **single source of truth**. The language model proposes actions; the backend validates and executes them. No action reaches the outside world without passing through backend authorization.

### High-level diagram

```
Mobile PWA (React 18 + TypeScript)
         │  HTTPS via Cloudflare Tunnel
         ▼
    Caddy (reverse proxy, TLS, auth headers)
         │
         ▼
FastAPI Backend (Python 3.11)
    ├── routes_chat.py  ← thin HTTP layer
    ├── chat/           ← pipeline modules
    │     ├── pre_check.py
    │     ├── ai_orchestrator.py
    │     ├── tool_executor.py
    │     ├── persistence.py
    │     └── turn_runner.py
    ├── cognition/       ← cognitive pipeline (per turn)
    │     ├── perception.py
    │     ├── appraisal.py
    │     ├── episode_service.py
    │     ├── decision.py
    │     ├── reflection.py
    │     └── procedural_service.py
    ├── memory/          ← semantic, episodic, social
    ├── social/          ← social profile, narrative
    ├── integrations/    ← Google, Spotify, Home Assistant
    └── data/app.db      ← SQLite (FTS5)

panel/ (Electron — internal monitoring, not user-facing)
Home Assistant (Docker on Pi)
Piper TTS + faster-whisper STT (local binaries)
```

### Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLite with FTS5 |
| AI provider | Anthropic Claude Haiku (default), Sonnet (complex tasks) |
| Frontend | React 18, TypeScript, Vite, PWA |
| TTS | Piper (runs locally on Pi) |
| STT | faster-whisper (runs locally on Pi) |
| Reverse proxy | Caddy |
| Remote access | Cloudflare Tunnel (no open ports) |
| Monitoring | Electron panel (`panel/`) — internal only |
| Automation | Home Assistant in Docker on Pi |
| CI | GitHub Actions |
| License | AGPL-3.0-or-later |

### Chat pipeline

Each user turn flows through focused modules:

1. **pre_check.py** — rate limits, maintenance mode, session validation
2. **ai_orchestrator.py** — calls Claude, runs bounded tool loop (max 3 rounds), handles streaming
3. **tool_executor.py** — dispatches tools, enforces role-based authorization, catches unknown tools
4. **persistence.py** — saves messages, tool results, cognition outputs
5. **turn_runner.py** — coordinates cognition pipeline around the AI call
6. **response_integrity.py** — post-generation safety checks (capability claims, memory fabrication, internal leaks)

`routes_chat.py` is intentionally thin: it receives the HTTP request, delegates to the pipeline, and streams SSE back to the client.

### AI providers

| Provider | Status | Tool support |
|---|---|---|
| Anthropic Claude | Production default | Full |
| Ollama (local LAN) | Experimental, disabled | None (chat only) |
| Mock | CI/tests | Full (deterministic) |

### Multi-turn tool loop

The orchestrator runs a bounded loop (`max_after_tools_rounds = 3`). Within a single turn, Claude can request multiple rounds of tool calls. The loop exits when no tools are requested, the turn is cancelled, or the round limit is reached. Each extra round is a full Claude call (~$0.003, 1–3 seconds on Pi).

### Session model

- **Admin**: one seeded account, no message limits, full toolset
- **User**: registered account, 100 messages/day, persistent sessions, full cognitive pipeline
- **Guest**: ephemeral session (cookie), 20 messages/day per IP, no cognitive pipeline, no social profile

Session IDs: `user:{id}` for authenticated users, `guest:{uuid}` for guests. Each session has its own lock that serializes turns to prevent race conditions.

### Security principles

- Backend listens on localhost only; Caddy handles TLS termination
- No open shell or general `sudo` available to the model
- Destructive actions require a pending step plus exact confirmation phrase
- Camera and microphone used only on explicit request
- Role-based toolset: guest < user < admin
- Three independent authorization layers: toolset construction → executor gate → post-generation check

---

## Español

### ¿Qué es Sity?

Sity es un asistente doméstico con IA que corre en una **Raspberry Pi 4**. Está diseñado para un hogar concreto: un admin, pocos usuarios y un modo invitado. El asistente tiene personalidad propia, memoria persistente, iniciativa propia e integraciones con servicios externos — accesible desde una PWA móvil.

El **backend es la fuente de verdad**. El modelo propone acciones; el backend las valida y ejecuta. Ninguna acción llega al mundo exterior sin pasar por la autorización del backend.

### Pipeline de chat

Cada turno del usuario pasa por módulos especializados:

1. **pre_check.py** — límites de tasa, modo mantenimiento, validación de sesión
2. **ai_orchestrator.py** — llama a Claude, ejecuta el bucle de tools (máx. 3 rondas), gestiona streaming
3. **tool_executor.py** — despacha tools, aplica autorización por rol, captura tools desconocidas
4. **persistence.py** — guarda mensajes, resultados de tools, salidas de cognición
5. **turn_runner.py** — coordina el pipeline cognitivo alrededor de la llamada a IA
6. **response_integrity.py** — verificaciones post-generación (afirmaciones de capacidad, memoria falsa, fugas internas)

### Modelo de sesión

- **Admin**: cuenta única, sin límite de mensajes, toolset completo
- **User**: cuenta registrada, 100 mensajes/día, sesiones persistentes, pipeline cognitivo completo
- **Guest**: sesión efímera (cookie), 20 mensajes/día por IP, sin pipeline cognitivo, sin perfil social

Cada sesión tiene su propio lock que serializa los turnos para evitar condiciones de carrera (implementado en commit `063f1e5` tras un incidente el 2026-09-14 donde dos mensajes en ~2s producían contexto incompleto).

### Principios de seguridad

- Backend escucha solo en localhost; Caddy gestiona TLS
- Sin shell abierta ni sudo genérico disponible para el modelo
- Las acciones destructivas requieren paso de confirmación con frase exacta
- Cámara y micrófono solo bajo petición explícita
- Toolset por rol: guest < user < admin
- Tres capas independientes de autorización: construcción del toolset → gate del executor → verificación post-generación

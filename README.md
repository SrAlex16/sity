# Sity

A conversational AI with its own personality, deployed on a Raspberry Pi 4.
FastAPI backend + React/TypeScript PWA + multi-layer cognitive pipeline (Operation Remake).

**Live demo:** https://sity.aletm.com · **License:** AGPL-3.0

---

## What is Sity

Sity is a personal AI assistant where the backend, cognitive logic, TTS/STT and all data run locally on a Raspberry Pi 4B. The language model is Claude Haiku via the Anthropic API — not a ChatGPT wrapper.

Every conversation turn goes through a 15-step pipeline that includes perception, emotional appraisal, goal management, utility-based decision making, episodic and semantic memory, and metacognitive reflection.

The goal is to build an AI that develops a real relationship with the user over time, with persistent memory, configurable personality, and the ability to take initiative.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLite + SQLModel |
| Language model | Claude Haiku (Anthropic API) |
| Mobile PWA | React 18 + TypeScript + Vite + Framer Motion |
| Infrastructure | Caddy + Cloudflare Tunnel |
| TTS/STT | Piper (local) + faster-whisper (local) |
| Integrations | Home Assistant · Google OAuth · Spotify |

## Cognitive architecture

The full cognitive pipeline is documented in [`docs/remake/pipeline-cognitivo-completo.md`](docs/remake/pipeline-cognitivo-completo.md). Nine implemented phases:

| Phase | Module | What it does |
|-------|--------|-------------|
| 1 | Personality | 13 orthogonal traits + MentalState |
| 2 | Perception + Appraisal + Goals | Intent classification, emotional appraisal, goal system |
| 3 | SocialProfile | 11-dimensional relationship model |
| 4 | Episodic memory | Episodes with 7-factor salience + autobiographical narrative |
| 5 | Decision (Action Policy) | Utility engine U(action) with 22 signals × 10 actions |
| 6 | Self-model + Values | Self-beliefs, own values, metacognition |
| 7 | Procedural memory | Behavioural patterns by context and user |
| 8 | User Model + ToM | User knowledge, belief attribution, expectations |
| 9 | Semantic consolidation | SemanticFact with dynamic confidence |

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/SrAlex16/sity.git
cd sity
cp .env.example .env  # fill in your keys

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. PWA (development)
cd mobile && npm install && npm run dev
```

See [`docs/operations/development.md`](docs/operations/development.md) for the full setup including Caddy and Cloudflare Tunnel.

## Required environment variables

```env
ANTHROPIC_API_KEY=        # Anthropic API key (Claude Haiku)
SITY_SECRET_KEY=          # JWT secret (generate with: openssl rand -hex 32)
SITY_ADMIN_EMAIL=         # Admin user email
SITY_ADMIN_PASSWORD=      # Admin password
SITY_PROJECT_ROOT=        # Absolute path to the project root directory

# Optional
SITY_SMTP_HOST=           # SMTP for emails (password reset, verification)
RECAPTCHA_SECRET_KEY=     # reCAPTCHA v3 (fail-closed if not set)
```

## Tests

```bash
# Full suite (no real model calls)
ANTHROPIC_API_KEY= pytest tests/ -m "not behavior_regression"

# With real Haiku calls (costs tokens)
pytest tests/ -m "behavior_regression"

# CI: ~2m30s, 3213 tests
```

## Security

Multiple layers of protection documented in [`docs/response-integrity.md`](docs/response-integrity.md):

- **Access control**: `_ADMIN_ONLY_TOOL_NAMES` at toolset construction + gate in `ToolExecutor._dispatch_tool_call`
- **Post-generation verification**: `response_integrity.py` detects capability_overclaim, memory_fabrication, internal_leak, architecture_disclosure
- **Rate limiting**: per IP and per email on auth endpoints
- **reCAPTCHA v3**: fail-closed (rejects login if not configured)

## Documentation

| File | Contents |
|------|----------|
| [`docs/state.md`](docs/state.md) | Current state, decision history, known bugs |
| [`docs/architecture.md`](docs/architecture.md) | Architecture and modules |
| [`docs/remake/`](docs/remake/) | Full documentation of the 9 cognitive phases |
| [`docs/response-integrity.md`](docs/response-integrity.md) | Response verification system |
| [`docs/turn-queue.md`](docs/turn-queue.md) | Per-session turn queue |

## Current status

Public beta under testing with real users. The full cognitive system is implemented and stable. See [`docs/state.md`](docs/state.md) for detailed status and known bugs.

---

Copyright (C) 2026 Alejandro Tubio · AGPL-3.0

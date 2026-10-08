# Sity — Home AI Assistant / Asistente Doméstico con IA

[English](#english) · [Español](#español)

---

## English

Sity is a personal AI assistant designed to run on a **Raspberry Pi 4** in your home. It combines a cloud language model (Claude Haiku) with a rich cognitive pipeline, persistent memory, proactive initiative, and integrations with Google, Spotify, and Home Assistant — all accessible from a mobile PWA.

**Public beta active since October 2026** · AGPL-3.0-or-later

### Quick links

| Topic | Document |
|---|---|
| System architecture | [architecture/overview.md](architecture/overview.md) |
| Cognitive pipeline | [architecture/cognitive-pipeline.md](architecture/cognitive-pipeline.md) |
| Memory system | [architecture/memory.md](architecture/memory.md) |
| Personality & self-model | [architecture/personality.md](architecture/personality.md) |
| Decision & initiative | [architecture/decision-making.md](architecture/decision-making.md) |
| Integrations (auth, OAuth, Spotify, HA) | [architecture/integrations.md](architecture/integrations.md) |
| Conversation features | [features/conversation.md](features/conversation.md) |
| Proactive initiative | [features/initiative.md](features/initiative.md) |
| Notifications | [features/notifications.md](features/notifications.md) |
| Voice & vision | [features/voice-vision.md](features/voice-vision.md) |
| Achievements | [features/achievements.md](features/achievements.md) |
| Shared conversations | [features/shared-conversations.md](features/shared-conversations.md) |
| File management | [features/file-management.md](features/file-management.md) |
| Local setup (WSL + Pi) | [development/getting-started.md](development/getting-started.md) |
| Deployment (Pi, Caddy, systemd) | [development/deployment.md](development/deployment.md) |
| Testing | [development/testing.md](development/testing.md) |
| Training (dataset, LoRA) | [development/training.md](development/training.md) |
| Security model | [security/overview.md](security/overview.md) |
| Audit results | [security/audit-results.md](security/audit-results.md) |
| Architecture decisions (ADRs) | [decisions/README.md](decisions/README.md) |
| Project history | [history/timeline.md](history/timeline.md) |
| Implementation changelog | [history/changelog.md](history/changelog.md) |

### Tech stack at a glance

```
Backend:   Python 3.11 + FastAPI + SQLite (FTS5)
AI:        Claude Haiku (default) / Claude Sonnet (complex tasks)
Frontend:  React 18 + TypeScript + Vite — mobile PWA
TTS:       Piper (local)
STT:       faster-whisper (local)
Infra:     Caddy + systemd + Cloudflare Tunnel on Raspberry Pi 4
```

### Current status (2026-10-08)

- 3,704 backend tests passing, 73% global coverage, 0 mypy errors
- 0 known P0 issues
- Public beta open — registration at `sity.aletm.com`

---

## Español

Sity es un asistente personal con IA diseñado para correr en una **Raspberry Pi 4** en tu hogar. Combina un modelo de lenguaje en la nube (Claude Haiku) con un pipeline cognitivo completo, memoria persistente, iniciativa propia e integraciones con Google, Spotify y Home Assistant — accesible desde una PWA móvil.

**Beta pública activa desde octubre de 2026** · AGPL-3.0-or-later

### Navegación rápida

| Tema | Documento |
|---|---|
| Arquitectura general | [architecture/overview.md](architecture/overview.md) |
| Pipeline cognitivo | [architecture/cognitive-pipeline.md](architecture/cognitive-pipeline.md) |
| Sistema de memoria | [architecture/memory.md](architecture/memory.md) |
| Personalidad y automodelo | [architecture/personality.md](architecture/personality.md) |
| Decisión e iniciativa | [architecture/decision-making.md](architecture/decision-making.md) |
| Integraciones | [architecture/integrations.md](architecture/integrations.md) |
| Conversación | [features/conversation.md](features/conversation.md) |
| Iniciativa propia | [features/initiative.md](features/initiative.md) |
| Notificaciones | [features/notifications.md](features/notifications.md) |
| Voz y visión | [features/voice-vision.md](features/voice-vision.md) |
| Logros | [features/achievements.md](features/achievements.md) |
| Conversaciones compartidas | [features/shared-conversations.md](features/shared-conversations.md) |
| Gestión de archivos | [features/file-management.md](features/file-management.md) |
| Setup local | [development/getting-started.md](development/getting-started.md) |
| Despliegue en Pi | [development/deployment.md](development/deployment.md) |
| Tests | [development/testing.md](development/testing.md) |
| Entrenamiento LoRA | [development/training.md](development/training.md) |
| Modelo de seguridad | [security/overview.md](security/overview.md) |
| Resultados de auditorías | [security/audit-results.md](security/audit-results.md) |
| Decisiones de arquitectura | [decisions/README.md](decisions/README.md) |
| Historia del proyecto | [history/timeline.md](history/timeline.md) |
| Changelog de implementación | [history/changelog.md](history/changelog.md) |

### Estado actual (2026-10-08)

- 3.704 tests pasando, cobertura global 73%, 0 errores mypy
- 0 P0 conocidos
- Beta pública abierta — registro en `sity.aletm.com`

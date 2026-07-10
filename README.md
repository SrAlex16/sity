# Sity

IA doméstica personal corriendo en una Raspberry Pi 4.
Backend FastAPI + PWA móvil React/TypeScript.
Licencia AGPL-3.0.

**Acceso:** https://sity.aletm.com
**Repo:** https://github.com/SrAlex16/sity

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + SQLite + Claude Haiku |
| PWA móvil | React 18 + TypeScript + Vite + Framer Motion |
| Panel | Electron + TypeScript |
| Infraestructura | Caddy + Cloudflare Tunnel |
| Domótica | Home Assistant (Docker) |
| TTS/STT | Piper + faster-whisper |

## Arranque rápido

```bash
# Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# PWA (desarrollo)
cd mobile && npm run dev

# Panel
cd panel && npm run build && DISPLAY=:0 npx electron . --no-sandbox
```

Ver docs/operations/development.md para el flujo completo.

## Documentación

| Archivo | Contenido |
|---------|-----------|
| docs/state.md | Estado actual del sistema |
| docs/architecture.md | Arquitectura y módulos |
| docs/decisions.md | Decisiones de diseño y lecciones aprendidas |
| docs/operations/development.md | Flujo de desarrollo |
| docs/operations/dataset-capture.md | Captura de dataset |
## Roadmap

### ✅ Completado

- Backend FastAPI + SQLite + Claude Haiku
- PWA móvil cyberpunk (https://sity.aletm.com)
- Panel de control Electron (monitorización + alertas)
- Sistema de personalidad (14 parámetros, sliders)
- Tool loop (web_search, file tools, memory, camera, audio)
- Prompt caching + Model Router semi-automático
- Google OAuth (Gmail readonly, Calendar rw, Drive readonly)
- Domótica via Home Assistant (Tapo P100, bombillas Gleco)
- Visión — imágenes adjuntas en el chat
- Caché web_search con TTL decidido por el modelo
- Refactor 202+SSE (tareas largas sin timeout de Cloudflare)
- Auditoría de literales hardcodeados (batch 1 y 2)
- Limpieza del sistema y repo
- Spotify (playlists, URI directo, resume previous)
- Audio STT — faster-whisper local, voz en chat y Telegram
- Telegram bot — acceso remoto, presets, rate limit
- Bucle multi-turno — tool chaining genérico (lectura → acción en 1 turno)
- Cancelación mid-stream — botón parar, SSE limpio
- task_context — memoria estructurada entre turnos para tareas multi-paso
- Tareas largas en background — respuesta inmediata + notificación al terminar
- Observabilidad Fase 1 — logging universal tools + APIs + retención 14 días

### 📋 Pendiente

- **Sistema de alertas del panel** — ampliar: disco >95%, RAM >90%,
  temperatura 70-80°C, zombies >5
- **Refactorización persona_engine** — A4-A6, B5-B6 pendientes
- **Análisis Docker completo** — qué más dockerizar y sandbox para
  ejecución de código generado por el modelo

### 🔮 Futuro

- Fine-tuning Gemma 3 4B + LoRA (cuando el dataset esté maduro)
- Dataset de audio ElevenLabs (cuando haya modelo local)
- ❌ Canal de divulgación Tech & IA — descartado (2026-07-08)
- Domótica avanzada — dispositivos sin integración HA
- Soporte Matter

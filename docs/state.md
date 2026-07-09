# Estado actual del proyecto Sity

Última actualización: 2026-07-08.

Foto rápida del estado operativo para retomar trabajo sin depender
de conversaciones anteriores. Para arquitectura detallada ver
docs/architecture.md. Para decisiones ver docs/decisions.md. Para el
sistema de tareas en background ver docs/background-tasks.md. Para el
sistema de cancelación de turnos ver docs/turn-cancellation.md.

## Infraestructura activa

**Servicios en la Pi (systemd):**
- sity-backend (FastAPI, puerto 8000)
- caddy (reverse proxy + TLS Let's Encrypt)
- cloudflared (Cloudflare Tunnel — acceso sin VPN)

**Docker:**
- homeassistant (Home Assistant Container, puerto 8123)
  Control de domótica: Tapo P100 (switch.tapo_p100),
  bombillas Gleco (light.luz_cuarto, light.cuarto_malaga)

**Acceso:**
- PWA móvil: https://sity.aletm.com
- Home Assistant: http://192.168.0.118:8123
- Panel de control: autoarranque en escritorio de la Pi (Electron)

**Panel de control (Electron):**
- Monitorización: CPU, RAM, red, disco, procesos
- Barra de servicios: sity-backend, caddy, cloudflared, homeassistant
- Sistema de alertas: critical/grave/medium/low con cola y recuperación automática
- Actualizar después de cambios: npm run build && npm run package en panel/

## Stack técnico

**Backend:** FastAPI + SQLite + Claude Haiku (claude-haiku-4-5-20251001)
**Frontend PWA:** React 18 + TypeScript + Vite + Framer Motion
**Frontend escritorio:** React + TypeScript (frontend/, sin PWA features)
**Panel:** Electron + TypeScript
**Modelos:** Claude Haiku (principal), Claude Sonnet (tareas complejas via model router)
**TTS local:** Piper (voz femenina)
**STT local:** faster-whisper (modelo small)
**Domótica:** Home Assistant REST API (HA_TOKEN en .env)
**Google:** OAuth2 — Gmail readonly, Calendar rw, Drive readonly

## Estado del dataset

- 3.813 mensajes totales en chatmessage
- 1.904 respuestas de Sity
- 865 respuestas con tone_meta (parámetros de personalidad por turno)
- Dataset de texto: sity_style_v0 en datasets/ (en .gitignore)
- Dataset de audio: pendiente (ver docs/decisions.md 2026-07-08)

## Tests y CI

- 897 tests en verde (pytest)
- mypy: 0 errores en backend/app/
- CI: GitHub Actions en .github/workflows/
- Node.js: 24 en CI

## Variables de entorno requeridas (.env en raíz)

```
ANTHROPIC_API_KEY        — Claude API
ELEVENLABS_API_KEY       — ElevenLabs TTS (plan Starter)
ELEVENLABS_VOICE_ID      — ID de la voz de Sity
GOOGLE_CLIENT_ID         — OAuth Google
GOOGLE_CLIENT_SECRET     — OAuth Google
HA_TOKEN                 — Home Assistant Long-Lived Token
HA_URL                   — http://192.168.0.118:8123
SPOTIFY_CLIENT_ID        — Spotify app Client ID (solo para setup inicial)
SPOTIFY_CLIENT_SECRET    — Spotify app Client Secret (solo para setup inicial)
```

Ver .env.example para la lista completa.

## Bugs conocidos activos

Ninguno confirmado a día de hoy. La lista anterior (encabezado DOCX
narrado en TTS del canal YouTube, refusal_mode con falsos positivos,
search_conversation_history como procrastinación del planner) quedó
obsoleta: el canal de YouTube se descartó, el resto no se ha vuelto a
observar. Ver docs/decisions.md 2026-06-30 y 2026-07-08 para el
contexto histórico si hace falta.

## Qué no hacer

- No activar SITY_LOCAL_AI_ENABLED=true en producción sin modelo validado
- No subir data/, datasets/, work/ a git
- No tocar /etc/asound.conf ni el pipeline HDMI (ver raspberry-setup repo)
- No modificar data/app.db en producción

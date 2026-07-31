# Estado actual del proyecto Sity

Última actualización: 2026-07-31.

Foto rápida del estado operativo para retomar trabajo sin depender
de conversaciones anteriores. Para arquitectura detallada ver
docs/architecture.md. Para decisiones ver docs/decisions.md. Para el
sistema de tareas en background ver docs/background-tasks.md. Para el
sistema de cancelación de turnos ver docs/turn-cancellation.md. Para
el bucle multi-turno de tool calling ver docs/multi-turn-tool-calling.md.
Para el sistema de contexto persistente entre turnos ver docs/task-context.md.
Para el sistema de memoria social (opinion/trust por usuario) ver docs/social-memory.md.

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
**Spotify:** OAuth2 — lectura (now_playing, recently_played, list_playlists, playlist_tracks, list_devices) + control (play, pause, skip, set_volume, resume_previous)

## Estado del dataset

- 3.813 mensajes totales en chatmessage
- 1.904 respuestas de Sity
- 865 respuestas con tone_meta (parámetros de personalidad por turno)
- Dataset de texto: sity_style_v0 en datasets/ (en .gitignore)
- Dataset de audio: pendiente (ver docs/decisions.md 2026-07-08)

## Tests y CI

- 1168 tests en verde (pytest)
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

Ninguno activo conocido.

**Resueltos recientemente (2026-07-31):**

- **Sliders personalidad no se sincronizaban tras escalado con mensaje vago:** Sonnet
  recibía solo BASE_TOOLSET (igual que Haiku — keyword matching no activaba
  PERSONALITY_TOOLSET para mensajes vagos como "cambia otra cosa"). Raíz real: Fix A
  almacenaba el toolset de Haiku en la propuesta, pero Haiku tenía BASE_TOOLSET porque
  las keywords no coincidían → Sonnet tampoco tenía `update_personality_settings` →
  llamaba `no_action_required` → `personality_updated=false` → CustomEvent nunca se
  disparaba. Fix: mergear siempre PERSONALITY_TOOLSET en re-runs de escalado, deduplicando
  (`no_action_required` ya está en BASE). Coste neto: +474 tokens cacheados (≈$0.000002).
  Confirmado en producción con logs: Sonnet llama `update_personality_settings` y
  `personality_updated=true` → CustomEvent → sliders actualizados.
  `backend/app/chat/ai_turn_prep.py`.
- **H1 — Escalado Haiku→Sonnet perdía herramientas y duplicaba mensajes:** Sonnet
  recibía toolset re-derivado del mensaje vago (sin keywords) → no tenía `PERSONALITY_TOOLSET`
  → decía "no tengo herramientas" → respuesta "Bien.". Mensaje original guardado dos veces
  en DB. "Sí" de confirmación nunca guardado. Fix: `ModelUpgradeProposal.selected_tools`,
  `forced_tools` en `build_ai_turn_prep`, skip del save en re-run, persistencia del "Sí",
  `_skip_history_turns` 2→3. 1168 tests.
- **H2 — Guests podían disparar escalado a Sonnet:** `propose_model_upgrade` se inyectaba
  para todos. Fix: `and not ctx.session_id.startswith("guest:")` en `ai_turn_prep.py`.
- **H3 — Prompt persona describía sensores como propios de Sity:** "la cámara de la Raspberry"
  → "la cámara del servidor donde corre el backend"; instrucción explícita de no usar
  "mis sensores" ni "mi cámara".
- **[SEGURIDAD] Personalidad no aislada por sesión** (Fase 2b, 2026-07-30): `Setting.key`
  tenía unique constraint global; cualquier Guest podía modificar la personalidad de Sity
  para todos los usuarios de forma persistente. Resuelto con migración de esquema a
  `(key, session_id)` composite unique + reescritura de `SettingsService` con fallback
  chain. Ver `docs/personality-isolation.md` y `docs/auth-system.md` § Fase 2b.

**Resueltos en la sesión 2026-07-10/11:**
- Timestamps incorrectos tras F5 (SQLite devuelve datetimes naive → JS
  los interpretaba como hora local): resuelto con `@field_serializer` en
  `ChatMessageItem.created_at` (commit `1343ff8`). Confirmado en real.
- Proactive message de `web_search` no llegaba al frontend tras F5 y
  recargas: investigado y descartado como bug real — era interferencia
  de los reinicios del backend durante el proceso de desarrollo. En una
  prueba limpia sin reinicios (turno "Nannmonee — Wasureranneyo", 22:55
  UTC), el flujo completo funcionó correctamente: `tool_chain_continued`,
  búsqueda OK, respuesta correcta ("Chainsmoker Cat" / Yani Neko). El
  logging nuevo (`bg_after_tools_failed`, `bg_persist_failed`, commit
  `e521dd8`) está activo para capturar cualquier fallo real futuro.

La lista anterior (encabezado DOCX narrado en TTS del canal YouTube,
refusal_mode con falsos positivos, search_conversation_history como
procrastinación del planner) quedó obsoleta: el canal de YouTube se
descartó, el resto no se ha vuelto a observar. Ver docs/decisions.md
2026-06-30 y 2026-07-08 para el contexto histórico si hace falta.

## Qué no hacer

- No activar SITY_LOCAL_AI_ENABLED=true en producción sin modelo validado
- No subir data/, datasets/, work/ a git
- No tocar /etc/asound.conf ni el pipeline HDMI (ver raspberry-setup repo)
- No modificar data/app.db en producción

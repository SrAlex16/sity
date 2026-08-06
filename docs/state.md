# Estado actual del proyecto Sity

Última actualización: 2026-08-06 (6 ideas nuevas documentadas).

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

- ~1607 tests en verde (pytest)
- Cobertura global: 73% (medida con pytest-cov)
- 8 módulos críticos llevados a 94-100%: auth, chat core, tool executor,
  toolset selector, routing decision, pending action runner, social memory, turn persistence
- Checklist de seguridad: 18/18 ✅ (ejecutado manualmente por Alex, 2026-08-04)
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

## Mejoras pendientes

- **Integraciones self-service por usuario (parcialmente implementado)** —
  Google/Spotify ya funciona: endpoints OAuth
  (`/auth/integrations/{provider}/connect|callback|disconnect`), credenciales
  por usuario cifradas en `UserIntegration`, handlers adaptados
  (`_resolve_google_creds`, `_resolve_spotify_token`). Pendiente: Home
  Assistant (sin OAuth estándar — requiere diseño propio) y la pantalla de
  frontend "Ajustes → Integraciones" con botones Connect/Disconnect. Ver
  `docs/auth-system.md` § Fase 6.
- **Sistema de iniciativa propia de Sity** — capacidad de que Sity
  inicie una conversación sin que el usuario escriba primero (ej. "acordé
  en recordarte esto", "encontré algo que puede interesarte"). Cuatro
  preguntas de diseño pendientes de responder antes de implementar:
  (1) **mecanismo de disparo**: ¿un runner periódico similar al de timers,
  o una cola de eventos ya pendientes en DB?; (2) **canal de entrega**:
  depende de la Web Push API (ya anotada como prerrequisito de alarmas)
  — sin push real el mensaje solo llega si la app está abierta;
  (3) **aislamiento por rol**: Guest no debería recibir mensajes proactivos
  no solicitados — requiere verificar sesión activa y rol antes de disparar;
  (4) **relación con memoria social**: si la iniciativa se basa en opinión/
  confianza del usuario, hay que respetar los invariantes ya establecidos
  (opinion/trust solo escritos por background job, nunca por conversación).
- **Sistema de eventos/vigías genéricos** — capacidad de que Sity ejecute
  tareas en background activadas por condiciones externas, más allá de los
  timers por tiempo. Dos categorías distintas: (a) **vigilancia reactiva**
  sobre integraciones ya existentes (ej. "avísame si llega un email de X") —
  **caso Gmail aparcado** (2026-08-06): investigar si FCM/Watch API ofrece push
  real sin polling o si polling REST es la única vía viable para terceros, antes
  de implementar `gmail_detector.py` (ver `docs/notifications-architecture.md`
  §2.3); (b) **tareas periódicas recurrentes** (ej. "resúmeme Reddit cada
  mañana" o "dime el tiempo al levantarme") — más próximo a un cron que a un
  vigía. Advertencia: no hardcodear casos individuales; diseñar un modelo de
  datos genérico (`NotificationRule` con tipo, parámetros, condición de
  disparo). El sistema de Web Push que lo entregará sigue adelante
  independientemente (ver entrada de Web Push API).
- **Pantalla "Voz" → "Ajustes"** — la pantalla de Voz (`VoiceScreen.tsx`)
  actualmente mezcla configuración de usuario con opciones que deberían ser
  solo-Admin. Sub-funcionalidades pendientes de diseñar y separar por rol:
  (1) **Periodicidad de borrado de audios** — ya existe la sección en
  `VoiceScreen.tsx` pero debe ocultarse para usuarios no-Admin (solo el
  admin debe poder cambiar la política de retención global de audios);
  (2) **Idioma de la interfaz** — ver punto separado más abajo;
  (3) **Gestión de archivos de audio**: lista de audios propios del usuario,
  opción de eliminar individuales o todos, vista del espacio usado;
  (4) **Exportar conversación** y borrado RGPD de todos los datos propios —
  un usuario autenticado debería poder exportar su historial completo (JSON/
  texto) y eliminar su cuenta con todos sus mensajes, sin depender del Admin.
- **Sistema de cambio de idioma** — la interfaz es completamente en español
  hoy. Dos niveles posibles: (a) **detección automática** del idioma del
  navegador/sistema al cargar la app; (b) **selección manual** en Ajustes
  (relacionado con el punto anterior de pantalla Voz → Ajustes). Decisión
  pendiente: ¿solo cambiar la UI o también el idioma en que Sity responde?
  Si es lo segundo, hay que coordinar con el prompt de sistema y la memoria
  social (el modelo de opinión está entrenado con texto en español).
- **Google Analytics / GTM** — integrar métricas de uso de la PWA (sesiones,
  pantallas visitadas, acciones de voz, errores de red). Tensión no resuelta
  con privacidad/RGPD: la PWA es un asistente personal con datos sensibles
  (mensajes, historial, integraciones OAuth); insertar GA sin resolver primero
  el aviso legal, el banner de cookies y el alcance de lo que se trackea sería
  contrario al espíritu de privacidad del proyecto. Decisión explícita: no
  insertar el snippet hasta responder qué se trackea, si se anonimiza, y si se
  incluye el aviso RGPD correspondiente.
- **Personalización estilo ChatGPT** — investigado 2026-08-06. Resumen del
  sistema de ChatGPT: 3 capas (Nombre + ocupación como contexto; Personalizar
  respuestas con campo libre sobre preferencias; Instrucciones del sistema con
  texto libre para comportamiento global) — su problema conocido es que el
  campo libre genera inconsistencias cuando el usuario escribe instrucciones
  que se contradicen con el contexto, y OpenAI no tiene mecanismo de
  resolución de conflictos. Sity ya lo resuelve mejor con sliders tipados
  (personalidad cuantificada, sin ambigüedad semántica). Valorar complementar
  con un **campo de texto libre de "contexto de usuario"** (nombre, ocupación,
  preferencias estables) que se inyecte en el prompt de sistema junto a los
  parámetros — sin sustituir los sliders, como capa adicional de personalización.
- **Gestión de enlaces compartidos** — pantalla frontend para listar y
  revocar todos los enlaces activos del usuario. El backend ya tiene
  `DELETE /chat/share/{id}` pero no hay un listado de los propios enlaces
  en la UI. `max_views` también podría configurarse desde `POST /chat/share`.
- **Modo de voz en tiempo real (estilo "Live" de ChatGPT)** —
  estudiar el streaming bidireccional de audio sin turnos discretos
  de grabación-envío-respuesta, y valorar si el hardware de la Pi lo
  soportaría con la latencia necesaria.
- **Marca de agua reCAPTCHA** — el badge de reCAPTCHA v3 aparece
  permanentemente en la esquina inferior derecha de la PWA. Ocultarlo
  con CSS requiere incluir un aviso legal en la UI (según los ToS de
  Google). Evaluar si ocultarlo y añadir el aviso, o dejarlo visible.
- **Limpieza de código continua** — a medida que crece el proyecto
  se acumulan TODOs, dead code y abstracciones a medias. Revisión
  periódica: eliminar lo que no se usa, consolidar patrones duplicados,
  asegurar que los tests cubren los módulos nuevos.
- **Más acceso al sistema para Sity** — ampliar el toolset de
  herramientas de sistema (procesos, archivos, red) más allá del
  subconjunto actual seguro. Caso concreto discutido (2026-08-05):
  **instalación de paquetes** — el patrón de allowlist actual (lista
  explícita de comandos/servicios permitidos, sin ejecución arbitraria)
  es el correcto y no se cambia; la decisión de qué alcance darle a la
  herramienta de instalación (qué paquetes, con qué confirmaciones, si
  solo `apt` o también `pip`) queda pospuesta a una sesión dedicada.
  *Advertencia: cada herramienta nueva amplía la superficie de ataque si
  Sity es manipulada vía prompt injection; evaluar caso por caso.*
- **Pantalla "Ajustes → Integraciones"** — frontend para conectar/desconectar
  Google y Spotify por usuario (Fase 6 Paso 6). Backend ya listo.
- **DSPy / optimización automática de prompts** — explorar DSPy para
  optimizar el prompt de sistema y los prompts de herramientas con
  datos reales del dataset v1. Requiere el dataset de evaluación
  terminado.
- **Navegación web activa (completa)** — `read_webpage(url)` de solo lectura
  ya implementado (scraping sin JS, con SSRF guard, timeout 10s, truncado
  a 5k chars, wrapper de contenido no confiable). Lo que queda pospuesto es
  la navegación con interacción real (clics, formularios): requiere sandboxing
  Docker aislado de la red interna de la Pi como prerrequisito no negociable.
  Ver `docs/web-navigation-risk-analysis.md`.
- **Web Push API — Pasos 1 y 2 completados** — infraestructura base
  lista: `sw.js` con listener `push`+`notificationclick`, tabla
  `PushSubscription`, claves VAPID, endpoints subscribe/unsubscribe,
  tabla `NotificationLog`, `notifications/dispatcher.py` con las 4
  responsabilidades (dedup · rate limiting · routing SSE→Push→pending ·
  persistencia), `notifications/push.py` (pywebpush wrapper), GC propio
  (`notifications_gc_loop`). 33 tests (10 Paso 1 + 23 Paso 2). mypy
  limpio. **Pendiente:** Paso 3 — conectar `timers/runner.py` al
  dispatcher (timer fired → Web Push si app cerrada). Ver
  `docs/notifications-architecture.md` §8.

## Bugs conocidos activos

Ninguno activo conocido.

**Resueltos recientemente (2026-08-03):**

- **Fuga de historial entre sesiones (Guest ↔ Admin)** (2026-08-04):
  Encontrada durante la ejecución del checklist de seguridad. Cuatro causas
  raíz independientes, todas corregidas:

  1. **`useEffect(fn, [])` en `useChat`:** el historial se cargaba una sola vez
     al montar; cambiar de sesión sin recargar la página dejaba los mensajes
     anteriores visibles. Fix: `useChat(userKey)` limpia todo el estado de
     sesión y relanza `loadHistory()` en cada cambio de `userKey`.

  2. **`sity_chat_cleared` global en localStorage:** "borrar chat" escribía un
     timestamp sin contexto de usuario; al volver como Admin, sus mensajes
     anteriores quedaban ocultos por el timestamp del Guest. Fix: clave scoped
     a `userKey` (`sity_chat_cleared_user:1`, `sity_chat_cleared_guest`).

  3. **Cookie `sity_session` no se eliminaba en logout (Chrome 104+):**
     `_clear_cookie()` usaba los defaults de Starlette (`secure=False,
     httponly=False`), pero la cookie fue creada con `Secure; HttpOnly`.
     Chrome requiere que la cabecera de borrado incluya `Secure` para eliminar
     una cookie `Secure`. Fix: `_clear_cookie()` y `_clear_guest_cookie()`
     pasan `httponly=True, secure=_cookie_secure(), samesite="lax"`.

  4. **Condición de carrera: respuesta de turno llega a sesión nueva:**
     si el usuario cerraba sesión con un turno en curso, `_listenTurn` seguía
     vivo (el controlador nunca se abortaba) y inyectaba la respuesta en el
     array de mensajes de la nueva sesión. Fix doble: `abort()` explícito en
     el efecto de `userKey` + guard en `_listenTurn` que descarta eventos
     `response` si `currentUserKeyRef.current !== expectedUserKey`.

**Resueltos recientemente (2026-08-03, seguridad):**

- **Protección contra prompt injection y phishing en web_search** (2026-08-03):
  Tres capas de defensa sin filtrado de keywords:
  (1) El texto del resultado de búsqueda devuelto al modelo ahora va envuelto en
  un header explícito que lo marca como "contenido de terceros, no instrucciones"
  — refuerza que el modelo no debe tratar snippets de internet como directivas del
  sistema (`web_search_tools.py`). (2) La descripción del tool `WEB_SEARCH_TOOL` en
  `tool_schemas.py` instruye a Sity a aclarar que los enlaces de resultados no han
  sido verificados como seguros, y a ser honesta cuando el usuario pregunta si un
  enlace es seguro. (3) Los dominios de los resultados servidos en cada búsqueda se
  loguean como `event="web_search_domains"` (a nivel INFO) para trazabilidad futura
  — no bloquea nada, da datos reales para decidir si una lista de dominios
  bloqueados sería útil más adelante. 2 tests nuevos. 1170 tests.
  Motivado por el hackeo de Discord de un conocido de Alex.

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

# Estado actual del proyecto Sity

Última actualización: 2026-08-11 (Sistema de idioma completo).

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

- 1768 tests en verde (pytest)
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

## Completado recientemente

- **Web Push API + mecanismo de 3 estados (Pasos A/B/C/4, 2026-08-10)** — sistema
  de notificaciones completo verificado en producción: `sw.js` push+notificationclick,
  tabla `PushSubscription`, claves VAPID, `NotificationLog`, dispatcher 3 estados
  (dedup · rate limiting · SSE/push/pending), `timers/runner.py` y
  `ai_orchestrator._on_done` conectados. Fix crítico: clave de cola SSE usa
  `current.session_id` (no el param URL). Fan-out per-subscriber en
  `realtime_events.py` (ver bug resuelto más abajo). 1668 tests.
  Ver `docs/notifications-architecture.md` para arquitectura completa y
  el estado verificado en §"Estado real verificado (2026-08-10)".

- **Sistema de idioma completo (Sistema 1 + Sistema 2, 2026-08-11)** —

  **Sistema 2 — Idioma de conversación de Sity** (per-sesión, backend):
  `language.override` en DB (clave `Setting`), default `"auto"`. Mismos 10 códigos
  que el selector de idioma de Sity ya existente (auto / es-ES / es-419 / en-US /
  en-GB / ja / fr-FR / de-DE / pt-BR / it-IT). `persona_engine.py` inyecta
  `{language_block}` per-turno según el valor. `persona_system.md` desacopla REGLA
  GRAMATICAL (siempre femenino) de REGLA DE IDIOMA (dinámica). `GET/PUT
  /settings/language`. Selectores en Ajustes con notas claras que distinguen los dos
  sistemas.

  **Sistema 1 — Idioma de la interfaz** (localStorage + geo, frontend):
  `GET /settings/ui-language-suggestion` lee `CF-IPCountry` de Cloudflare (misma
  técnica que CF-Connecting-IP para rate limiting de Guest). Mapeo: España/LatAm →
  `es`, US/GB/AU/… → `en`, JP → `ja`. Idiomas con traducciones aún no disponibles
  (FR, DE, PT, IT) caen a `en`. Preferencia manual en `localStorage['sity_ui_lang']`
  tiene prioridad sobre la geo-sugerencia. Hook `useUiLanguage` en `App.tsx`;
  traducciones tipadas en `mobile/src/i18n/translations.ts`; aplicadas en BottomNav
  y VoiceScreen completo (es/en/ja). Texto japonés decorativo (`.sectionJp`) NO
  forma parte del sistema i18n — es estético y no varía.

  Código país → idioma mapeado (`_COUNTRY_TO_UI_LANG`): ES/MX/CO/AR/PE/VE/CL/EC/GT/
  CU/BO/DO/HN/PY/SV/NI/CR/PA/UY/GQ/PR → es; US/GB/AU/CA/NZ/IE/ZA/SG/PH/IN/NG/GH/
  KE → en; JP → ja. 13 tests en `test_ui_language_suggestion.py`.

  **Bug encontrado y corregido (turn_context.py):** `build_turn_context()` llamaba
  a `settings_service.get_voice_settings()` sin `session_id` → los ajustes de voz
  per-sesión se almacenaban correctamente en DB pero no se aplicaban durante los
  turnos reales. Corregido al mismo tiempo que la implementación del idioma. Lección:
  cualquier lectura de un setting per-sesión debe pasar `session_id` en todos los
  puntos de consumo, no solo en los endpoints. Ver `docs/auth-system.md`
  § "Lección aprendida — session_id en todos los puntos de lectura".

  Verificado en real por Alex (2026-08-11): Sistema 2 (idioma de conversación de
  Sity) y Sistema 1 (idioma de UI via CF-IPCountry) confirmados en producción.
  1709 tests en verde.

## Completado recientemente (2026-08-11, continuación)

- **Alters de personalidad (Fase 1, 2026-08-11)** — tabla `PersonalityAlter`
  (SQLModel, `(user_id, slot)` UniqueConstraint, 5 slots por usuario).
  Endpoints CRUD: `GET /settings/alters`, `GET/PUT /settings/alters/{slot}`,
  `DELETE /settings/alters/{slot}`. Selector de preset en frontend (VoiceScreen)
  con carga/aplicación instantánea. Personalidad del alter se inyecta en el
  prompt de sistema exactamente igual que la personalidad base. Ver
  `docs/architecture.md` §Alters de personalidad.

- **Sistema de texto bilingüe (UI, 2026-08-11)** — clases CSS `*Es`/`*Jp` en
  `VoiceScreen`, `PersonalityScreen` y `PersonalitySliderItem`: orden Es-primero/
  Jp-debajo, tamaño 12px (español) / 9px (japonés), colores intercambiados:
  `*Es` → `var(--text-primary)` (fuerte), `*Jp` → `var(--text-secondary)` (apagado).

- **Directivas de personalidad 5 niveles (2026-08-11)** — `persona_engine.py`
  reemplaza el sistema binario HIGH/LOW (zona muerta 0.20–0.80) por 5 niveles:
  `very_low` (≤0.20) / `low` (≤0.40) / `mid` (≤0.60) / `high` (≤0.80) /
  `very_high` (>0.80). Los 14 parámetros reciben directiva de comportamiento
  en CUALQUIER valor del slider; no más zona muerta. `_Levels` NamedTuple +
  `_level_directive()` helper eliminan 13 bloques if/elif repetitivos.
  `persona_system.md`: añadida línea de interpretación para `helpfulness`
  (que faltaba). 14 nuevos tests de extremos en `test_persona_prompt.py`.

## Completado recientemente (2026-08-11)

- **Pantalla Ajustes completa y verificada en real** — `VoiceScreen.tsx`
  renombrada a "Ajustes" (pestaña gear), sección "Voz" unificada (modo de
  respuesta + transcripción + respuestas largas + botón Restaurar en un solo
  bloque), exportar conversación como JSON, borrar cuenta con confirmación
  inline, placeholder gestión de archivos. Badge reCAPTCHA oculto fuera de
  login con `visibility: hidden`.

- **Integraciones self-service frontend completo (Fase 6, verificado en
  real)** — sección "Integraciones" en Ajustes: botones Conectar/Desconectar
  para Google y Spotify con estado live de `GET /auth/integrations`.
  `window.open(_blank)` en vez de navegación de la pestaña principal;
  callback OAuth devuelve HTML "Conexión completada, puedes cerrar esta
  pestaña" que dispara `BroadcastChannel('sity_oauth')` para refresco
  automático en VoiceScreen. Fallback `visibilitychange` cuando la pantalla
  no estaba montada. Botón Desconectar en rojo; confirmación inline antes
  de desconectar.

- **Bug aislamiento ajustes de voz por sesión** — `settings_service.py`
  tenía `session_id=None` hardcodeado para todos los campos de voz (mismo
  patrón que el bug de personalidad pre-Fase 2b). Corregido:
  `voice_response_mode`, `voice_include_text`, `voice_long_response_action`
  ahora per-sesión con fallback a global; `audio_cleanup_days` sigue global
  y solo-admin. `GET/PUT /settings/voice` ya no requieren admin, solo
  non-guest.

- **Bug PKCE en callback de Google OAuth** — el backend creaba dos objetos
  `Flow` separados (uno en `/connect`, otro en `/callback`) sin compartir el
  `code_verifier`. Google rechazaba el intercambio con
  `(invalid_grant) Missing code verifier`. Fix: par PKCE generado en
  `/connect`, verifier embebido en el state token (firmado con HMAC-SHA256),
  extraído y pasado a `flow.fetch_token(code_verifier=...)` en `/callback`.

- **Nota operativa Google OAuth Testing** — el aviso "app en desarrollo"
  es comportamiento estándar de Google mientras la app no está verificada.
  Se resuelve añadiendo usuarios de prueba en Google Cloud Console → OAuth
  consent screen → Test users. Documentado en `docs/auth-system.md`.

- **Nota operativa Spotify Redirect URIs** — bug real: la URI se pegó en
  formato Markdown `[texto](url)` en vez de texto plano, y no se pulsó
  "Save" explícitamente tras añadir la URI (Spotify no autoguarda). URL
  exacta que construye el backend:
  `https://sity.aletm.com/auth/integrations/spotify/callback`.
  Documentado en `docs/auth-system.md`.

## Mejoras pendientes

- **Diseño refusal_mode — Problema A (pendiente de decisión, 2026-08-11)** —
  la directiva `_REFUSAL_ACTIVE` da al modelo DISCRECIÓN para decidir si aplica
  o no la negativa, incluso con `refusal_chance=100%`. El texto actual lo
  clasifica como "disponible, no obligatorio". Esto produce que el modelo a
  menudo ignora el refusal_mode incluso cuando el slider está al máximo.
  Alternativas a evaluar: (a) hacer la negativa obligatoria cuando el slider
  supera un umbral (eliminar la discreción); (b) mantener la discreción pero
  reducir el texto que la justifica; (c) diseñar una tercera instrucción para
  niveles muy altos. NO tocar hasta que Alex decida el enfoque en sesión dedicada.
  **Patrón compartido con "Problema B — inferencia de herramientas" (ver abajo):**
  ambos son casos del mismo fondo — el modelo con demasiada latitud de decisión
  sin barreras estructurales. Si se aborda el Problema A con una solución más
  estructural (reducir discreción), revisar si aplica también al problema de
  inferencia de herramientas.

- **Inferencia de herramientas por contexto ambiental — Problema B
  (mitigado con parche, 2026-08-12)** — el modelo llamó a `list_timers` al
  recibir "¿Cómo estamos ahora?" en una sesión con historial previo de timers,
  sin que el mensaje lo mencionara. Diagnóstico (trace `trc_33d668065f91`):
  `list_timers` está en BASE_TOOLSET ("always available"), el toolset_selector
  no activó ningún dominio especial, pero el modelo infirió el tema desde el
  contexto ambiental del historial y llamó a la tool.
  Mitigación aplicada (2026-08-12, parche B+C): (B) descriptions de las 4 tools
  de timers reforzadas con "SOLO úsala cuando el usuario lo pide explícitamente";
  (C) guardarraíl genérico añadido en `persona_system.md` §REGLA DE USO DE
  HERRAMIENTAS, cubriendo cualquier tool de consulta de estado presente o futura.
  Opción A (mover timers fuera de BASE_TOOLSET) descartada por ahora — mismo
  criterio de no añadir complejidad estructural hasta tener evidencia de que el
  parche de prompt es insuficiente. **Si el patrón reaparece con otras tools
  de estado, escalar a Opción A.**

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
- **Ampliar i18n a ChatScreen** — ChatScreen aún tiene todos sus textos hardcodeados
  en español (botones, labels, mensajes de error). La capa de traducciones
  (`mobile/src/i18n/translations.ts`) ya existe; solo falta añadir el namespace
  `chat` y aplicarlo. Menor urgencia porque ChatScreen es mayoritariamente
  contenido del usuario, no UI funcional.
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

## Bugs conocidos activos

Ninguno activo conocido.

**Resueltos recientemente (2026-08-10):**

- **Fan-out de colas SSE — zombie connections consumían eventos** (2026-08-10):
  `_SessionQueue` usaba una sola `asyncio.Queue` compartida; `asyncio.Queue.get()`
  asigna el evento al primer waiter en FIFO, que podía ser una conexión zombie
  (socket TCP técnicamente abierto, ya no escuchado por el navegador). Los eventos
  llegaban al zombie y se perdían. Evidencia: 4 `sse_subscriber_connected` vs.
  1 `sse_subscriber_disconnected` en 29 minutos. Fix: fan-out model — cada
  `subscribe_session()` crea su propia `asyncio.Queue`; `publish_session_event()`
  copia el evento a todas las colas activas. Eventos sin suscriptores activos se
  descartan; clientes que reconectan llaman `loadHistory()`. El bug era intermitente
  (solo visible con zombies acumulados por reconexiones previas), lo que dificultó
  el diagnóstico. Relevante si cualquier sistema futuro usa `_session_queues` y
  presenta pérdidas intermitentes de eventos SSE — verificar el diferencial
  connected/disconnected en logs. `core/realtime_events.py`, 13 tests nuevos.

- **"Promesa sin cumplir" en background tasks** (2026-08-10): tras `web_search`
  sin dato exacto en el snippet, el modelo pedía `read_webpage` como tool adicional;
  `_on_done` ignoraba `tool_calls` y usaba `.text` (el preamble de la promesa)
  como respuesta final. Fix doble: prompt con instrucción explícita de no encadenar
  (`_BACKGROUND_AFTER_TOOLS_SUFFIX`) + guard `bg_unexpected_tool_call` que descarta
  `after_resp.text` por completo cuando `tool_calls` es no-vacío (el texto siempre
  es el preamble en ese caso). `chat/ai_orchestrator.py`, `chat/ai_request_builder.py`.

- **Tag `<R:0>` visible en mensajes de background** (2026-08-10): `_on_done`
  no pasaba el texto por `strip_turn_load_tag`, el marcador de social-memory
  llegaba al usuario. Fix: función renombrada a pública y llamada en `_on_done`.
  `chat/final_response_builder.py`, `chat/ai_orchestrator.py`.

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

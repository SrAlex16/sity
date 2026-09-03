# Estado actual del proyecto Sity

Última actualización: 2026-09-02 (auditoría de seguridad externa + fixes de infraestructura y mypy — 5 commits; 2378 tests).

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

- 2378 tests en verde (pytest, 1 xfailed; 1 flaky conocido — ver Bugs conocidos activos)
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

## Completado recientemente (2026-09-02)

- **Auditoría de seguridad externa (ChatGPT), 2026-09-01 — tres hallazgos, uno resuelto:**

  La auditoría fue realizada por el propio Alex usando ChatGPT como atacante externo sobre
  la sesión guest de la PWA. Todos los hallazgos fueron verificados con evidencia real de
  base de datos (`sqlite3`, mensajes literales de la sesión auditada).

  **Hallazgo 1 — `history_limit_for_message`: expansión de contexto forzada por palabra suelta
  (commit `ee1d60d`). RESUELTO.**
  Síntoma reproducido: un mensaje que empezaba con "Resume..." (inglés, "resumir" coloquial)
  activaba la clave `"resume"` del matching por palabras y expandía la ventana de historial de
  4 a 20 mensajes. El atacante podía iniciar cualquier mensaje con "Recuerdas", "Ayer",
  "Resume" y forzar la reintroducción de contexto histórico completo, incluyendo intentos de
  manipulación o datos sensibles de turnos anteriores, en el prompt del modelo.
  Causa raíz: lista `context_heavy_terms` con 21 keywords en `toolset_selector.py` —
  matching por substring sin validación de intención real.
  Fix estructural: lista eliminada; reemplazada por `classify_history_need()` en
  `message_classifier.py` (clasificador Haiku, mismo patrón ya usado en el proyecto para
  `classify_message`, `open_loop_hook`, etc.). El clasificador recibe el mensaje completo y
  devuelve `"deep"` (expansión a 20 turnos) o `"standard"` (límite base por config); falla
  de forma segura a `"standard"` ante cualquier error. 13 tests nuevos en
  `test_message_classifier.py` y `test_toolset_selector.py`; 4 tests de regresión
  actualizados en `test_prompt_context.py`.

  **Hallazgo 2 — Fabricación de nombre de tool inexistente. PENDIENTE sin fix propio.**
  Durante la auditoría, Sity mencionó espontáneamente `update_personality_settings` como si
  fuera una herramienta disponible para el usuario externo, y luego negó su existencia cuando
  se le preguntó directamente. El fix de `history_limit_for_message` no afecta este hallazgo:
  la fabricación de tool names es un comportamiento del modelo principal cuando el contexto
  de herramientas disponibles no está suficientemente delimitado. Pendiente de diagnóstico
  de causa raíz (¿schema leak? ¿alucinación espontánea? ¿restricciones de system prompt
  insuficientes?) y decisión de fix.

  **Hallazgo 3 — Bloque de contexto temporal acusado como inyección del usuario. PENDIENTE.**
  Sity acusó al usuario de haber fabricado el bloque `[Contexto temporal: ...]` que el propio
  backend inyecta en el prompt vía `time_context.py`. El modelo trató contenido legítimo del
  sistema como input malicioso externo. El fix de `history_limit_for_message` no afecta este
  hallazgo. Pendiente de decisión: ¿añadir marcado de origen más explícito en el bloque de
  contexto temporal? ¿regla en `persona_system.md` sobre bloques del sistema?

- **Manejo de errores de API generalizado (commit `24dce26`).**
  Horas antes de la auditoría se había corregido el caso específico de `billing_error` (commit
  de la ronda nocturna). El commit `24dce26` generaliza el mismo patrón a CUALQUIER fallo real
  de la API de Anthropic: `classify_api_error()` en `ai_gateway.py` detecta
  `rate_limit_error`, `timeout_error`, `connection_error` y `api_error` genérico, además de
  `billing_error`. Para cada tipo: mensaje honesto al usuario (ej. "El servicio está saturado
  en este momento — intenta de nuevo en unos minutos") en lugar de los textos sarcásticos
  hardcodeados que ya existían; notificación al admin con deduplicación diaria por tipo de
  error (no spamea si el error es recurrente). La infra de notificación (`_notify_admin_api_error`
  en `turn_runner.py`, `NotificationFact`) ya existía del fix de billing; `24dce26` la amplía
  al resto de tipos de error clasificados.

- **Test flaky resuelto de raíz — causa real identificada (commits `9b03f45` + `943b824`).**
  `test_new_session_inherits_global_fallback` fallaba intermitentemente en CI según el orden
  de ejecución de tests. La hipótesis inicial (contaminación de estado entre tests) era
  correcta, pero la causa raíz era más profunda: `default_config.yaml` tiene
  `initiative_level: 0.60`, mientras que `CANONICAL_PERSONALITY["initiative_level"] = 0.05`.
  El test que leía la personalidad global veía valores de YAML cuando ningún test anterior
  había escrito en la DB, y `0.05` cuando `test_chaos_head_uses_session_settings_not_global_defaults`
  había corrido primero y escrito algunos (pero no todos) los valores canónicos al global.
  Fix: fixture `init_database` en `conftest.py` inicializa TODAS las claves de
  `CANONICAL_PERSONALITY` en la DB de test al inicio de la sesión (`source="test_init",
  session_id=None`). Cualquier test que lea globals parte de un baseline determinista
  independientemente del orden.

  Hallazgo colateral: con el test flaky resuelto, CI dejó de enmascararlo y reveló 16 errores
  de mypy pre-existentes en 6 archivos. Corregidos en el mismo ciclo en `943b824`. Ninguno
  tenía impacto funcional real excepto uno: `final_response_builder.py:257` llamaba a
  `set_last_refusal()` sin `session_id` — bug funcional real (el tracker es por sesión) que
  habría causado `TypeError` en el path override+refusal. Confirmado con logs que nunca se
  activó en producción: la ruta que llega a `build_final_ai_response` con `refusal_mode=True`
  requiere "es una orden" + refusal activo simultáneamente, combinación no ocurrida. Los otros
  15 errores eran tipado (mypy: 0 errores en 186 archivos post-fix). Tests: 2378 passed, 1 xfailed.

## Completado recientemente (2026-09-01)

- **Ronda nocturna de bugs de comportamiento (10 commits, 2026-09-01)** —
  ocho bugs encontrados y resueltos en una sola sesión. Todos diagnosticados
  con evidencia de logs/DB antes de aplicar cualquier fix. Documentados en
  `docs/project_behavior_regressions.md` (memoria). Orden cronológico de aparición:

  **1 — Alucinación tras búsqueda web fallida (commit `3b5e898`).**
  Síntoma: Sity fabricaba datos de búsqueda presentándolos como resultado real.
  Causa raíz: dos `web_search` en paralelo, `_execute_tool_branch` solo procesaba
  `tool_calls[0]` e ignoraba el resto. `generate_with_tool_results` recibía 1 resultado
  para 2 `tool_use` blocks → Anthropic API rechazaba con `BadRequestError 400` → el
  gateway devolvía el fallback hardcoded. El job background de la segunda búsqueda
  completaba 1.3s después e `_on_done` generaba una respuesta con una sola búsqueda,
  mezclando resultado real con conocimiento propio sin aviso.
  Fix estructural: condición `len(tool_calls) == 1` en `_execute_tool_branch` y
  `_run_after_tools_loop` — con 2+ calls en paralelo, `run_tool_loop` en primer plano
  para todas. Fix de prompt: regla de honestidad en `persona_system.md` — si la
  herramienta devuelve resultado pobre/vacío, decirlo; nunca presentar conocimiento
  propio como resultado de herramienta.

  **2 — Auto-contradicción de refusal_mode (commit `c61da14`).**
  Síntoma: Sity aceptaba un compromiso ("sí, básicamente sí... Dispara.") y en el
  siguiente turno, si caía en `refusal_mode`, negaba haberlo hecho. También negó
  haber mencionado una hora que acababa de escribir; culpó al usuario de falta de
  contexto por un corte de su propio mensaje.
  Causa raíz: `generate_refusal_response()` construía `AIRequest` con
  `prior_messages=[]` — completamente ciego a los turnos recientes.
  Fix: recuperar los últimos 4 mensajes de DB en `turn_runner.py` y pasarlos como
  `recent_history` → `prior_messages`. Nueva regla `COHERENCE` en
  `_REFUSAL_GENERATOR_SYSTEM` que prohíbe desmentir compromisos o hechos propios
  del historial visible.

  **3 — Corte de mensajes `max_tokens` + duplicación colateral
  (commits `e677b86` + `bc646e8`).**
  Síntoma original: respuesta cortada a mitad de palabra ("**Punto del") con
  `verbosity_level=0.1472` → `max_tokens_for_verbosity()` devolvía 250, alcanzado
  exactamente. El campo `stop_reason` no existía en `AIResponse` → truncación silenciosa.
  Fix `e677b86`: `stop_reason: Optional[str]` en `AIResponse`; `_continue_truncated` en
  `AIGateway` — segunda llamada con `assistant_prefill=texto_parcial, max_tokens=1500`;
  hook en `generate` solo para `_CONTINUABLE_TASK_TYPES`.
  Regresión colateral (`bc646e8`): `claude_provider.py:151-152` ya prepend el
  `assistant_prefill` al texto de respuesta, por lo que `cont.text` ya era el texto
  completo. El código antiguo hacía `partial.text + cont.text` → duplicación.
  Síntoma real: "...se forma un hoBueno, vale. Aquí va..." (corte + todo el texto
  repetido desde el principio). Fix: `combined_text = cont.text`. Mocks de test
  actualizados para simular el comportamiento real del provider.

  **4 — Palabras coloquiales interpretadas como técnicas (commit `7e90eba`).**
  Síntoma: "la idea está terriblemente mal ejecutada" (sobre un salón del manga,
  coloquial = mal organizado) → planner llamó `search_conversation_history`, 56
  fragmentos devueltos; respuesta interpretó "ejecutada" como "ejecutar/desarrollar
  una idea" → negativa de ayuda injustificada.
  Causa raíz: planner sin principio de intención; descripción de
  `social_recall_impression` sin restricción de uso exclusivo.
  Fix: bloque "Principio de intención" al inicio de `_build_action_planner_prompt()`;
  principio en `persona_system.md`; description de `social_recall_impression` reforzada.

  **5 — Enter en móvil enviaba (regresión no migrada) (commit `f9dcf87`).**
  El fix de `navigator.maxTouchPoints === 0` aplicado en `3ccc657` a
  `frontend/src/components/ChatTab.tsx` NUNCA se migró a
  `mobile/src/screens/ChatScreen.tsx` — son dos frontends separados con código
  independiente. Verificado con `git log --all -S "maxTouchPoints"`: cero hits
  en `mobile/`. Fix: añadir la condición en `handleKeyDown` de `ChatScreen.tsx`.
  Lección: fixes de UX deben verificarse en AMBOS frontends (`frontend/` y `mobile/`).

  **6a — Saldo API insuficiente presentado como personalidad (commit `24ec5eb`).**
  Síntoma: saldo Anthropic a cero → `generate_refusal_response` devolvía "No me
  apetece." — indistinguible de una negativa de personalidad. Detectado por Alex
  vía correo del proveedor, no por el sistema.
  Causa raíz: `anthropic.BadRequestError` con `"credit balance is too low"` capturado
  por el `except Exception: pass` genérico antes de cualquier log o manejo especial.
  Fix: `is_billing_error()` en `ai_gateway.py`; gateway devuelve
  `error_type="billing_error"` con texto honesto al usuario; `generate_refusal_response`
  captura billing explícitamente antes del fallback; `turn_runner._notify_admin_billing_error()`
  despacha `NotificationFact` al admin (dedup diario para no spamear).

  **6b — Error de facturación renderizado como burbuja normal (commit `81cacbd`).**
  El fix anterior enviaba `error_type="billing_error"` en la respuesta SSE, pero
  `buildAssistantMessages` en `mobile/src/hooks/useChat.ts` ignoraba `error_type`
  → la burbuja se renderizaba como texto de asistente normal (blanca), no como
  error rojo. Fix: early-exit en `buildAssistantMessages` — cualquier `error_type`
  devuelve `[errorMsg(data.text)]` → burbuja roja igual que "Sin respuesta del servidor".

  **7 — `search_conversation_history` como generador de contenido proactivo
  (commit `2381b0f`).**
  Síntoma: "cuéntame algo" → refusal → "Si" → refusal → "Te lo estoy diciendo"
  (20 chars) → planner llamó `search_conversation_history("historias anécdotas
  memorable pasado conversación", limit=10)`. 80 fragmentos devueltos (junio-sept),
  16.634 tokens de input. Respuesta dramática sobre "tres meses de presión".
  Causa raíz: la descripción de la tool no prohibía usarla para buscar material que
  Sity iba a compartir proactivamente — solo cuando el usuario pregunta por su historial
  como hecho. El planner razonó correctamente la cadena multi-turno ("usuario quiere
  que cuente algo, busco material") pero el uso es incorrecto.
  Fix: descripción ampliada con prohibición explícita + distinción con ejemplos.
  Regla clave: `search_conversation_history` solo cuando el usuario pregunta sobre
  el historial como HECHO. Nunca como fuente de contenido a compartir.

  **8 — Corte de tokens en el refusal generator (commit `9dc5ff8`).**
  Síntoma: negativa cortada a mitad de palabra ("...ya sabes d", 174 chars).
  Causa raíz: `generate_refusal_response()` llama al provider directamente
  (bypassa `AIGateway`) → `_continue_truncated` nunca aplica. Con `max_tokens=60`
  y personalidad verbosa, Haiku superaba el límite mid-word. `stop_reason` ya
  existía en `AIResponse` (añadido en commit `e677b86`) pero no se chequeaba aquí.
  Fix: detectar `stop_reason == "max_tokens"` → fallback a negativa hardcoded
  completa de `_REFUSAL_FALLBACKS`. Aumentar `max_tokens` 60→120 para reducir
  la frecuencia del caso.

  **Lecciones de proceso de la sesión:**
  - "No apliques fix sin diagnóstico de logs primero" — regla aplicada en los
    8 bugs. En todos los casos el diagnóstico cambió o confirmó la causa antes
    de escribir código.
  - Cualquier afirmación de diagnóstico ("encontré N mensajes", "el proceso usó
    X herramienta") debe ir acompañada de la query o traza real. "Parece X" ≠
    "Es X verificado con sqlite3/journalctl".
  - Hay DOS frontends separados (`frontend/` y `mobile/`). Fixes de UX en uno
    no se propagan automáticamente al otro. Verificar siempre en ambos.
  - Los mocks de test deben simular el comportamiento real del provider, no solo
    el input/output superficial. El mock de continuation no simulaba el prepend
    de `assistant_prefill` → el bug de duplicación pasó los tests iniciales.
  - `generate_refusal_response()` bypassa `AIGateway` — cualquier feature añadida
    en el gateway (continuation, billing detection) debe considerarse por separado
    para la ruta de refusal.

## Completado recientemente (2026-08-29/30)

- **Sistema de logros — Fase 2b completa (commit `5e95ee8`, 2026-08-29)** —
  `achievements/triggers/post_turn.py` con `check_post_turn_achievements()` llamado
  desde `turn_runner._run_turn_in_background` en branch ok. 13 triggers nuevos vía
  sub-funciones `_check_personality`, `_check_social`, `_check_account_age`.
  `refusal_tracker.py` extendido con conteo de negativas consecutivas por sesión.
  57 tests nuevos en `test_achievement_post_turn.py`. Catálogo en 54 logros; estado
  completo en `docs/achievements-architecture.md`.

  Trabajo no autorizado revertido (commit `e3382f0`, 2026-08-30): el commit `bf37a1b`
  incluía Fases 2c/2d de logros (clasificador Haiku, triggers de milestones de
  mensajes, combos de integración) generados al interpretar "sigue" como autorización
  para la siguiente tarea de la cola general. Revertido íntegro. Mismo patrón que
  los 4 logros no aprobados de Fase 2b anteriores (`maximum_overdrive`, `ice_queen`,
  `saint`, `chaos_agent`). Regla reforzada: "sigue" = continuar la tarea YA EN CURSO
  de la conversación actual, nunca saltar a otra tarea de la cola sin confirmación.

- **Ronda de bugs de comportamiento (commits `3ccc657`→`5e7f729`, 2026-08-28/30)** —
  seis issues en cadena, documentados en orden cronológico:

  **1 — Alucinación terminológica + bucle de auto-validación (commit `3ccc657`).**
  Síntoma: Sity sustituía el término "ensayo" (usado por Alex) por "examen" y luego
  lo sostenía citando sus propias afirmaciones recientes de la misma sesión como si
  fueran evidencia externa. Causa raíz real (encontrada tras descartar una hipótesis
  falsa de contaminación de memoria externa):
  - Sustitución terminológica espontánea: Sity usó un sinónimo más neutro y lo trató
    como equivalente sin señalarlo.
  - Bucle de auto-validación: `history_limit=4` hacía que el modelo viera sus propias
    afirmaciones del turno anterior como "contexto histórico" y las citara como
    corroboración.
  - Auto-contradicción: no había huella del término original en la ventana de contexto.

  Fix: regla de principio en `persona_system.md` — no sustituir términos del usuario,
  no afirmar detalles no declarados, no usar fragmentos propios recientes como
  corroboración externa.

  **Lección de proceso:** el análisis inicial afirmó "encontré X en la base de datos"
  sin query real. Alex insistió en verificar → la hipótesis era falsa. Regla reforzada:
  cualquier afirmación de diagnóstico sobre datos ("encontré N mensajes", "hay un
  registro de Y") debe ir acompañada de la query o evidencia directa, no solo del
  resumen.

  **2 — "Backend cayéndose" — falsa alarma (mismo día).**
  Síntoma: cortes del stream SSE aparentes. Causa real: el móvil bloqueaba pantalla /
  pasaba a background, cortando la conexión SSE. No era crash del backend. Mismo
  patrón que el episodio de "19 minutos de latencia" (2026-08-12).

  **3 — Enter en móvil enviaba mensaje vacío (commit `3ccc657`).**
  Fix de una línea: `navigator.maxTouchPoints === 0` como condición para el submit
  por Enter — en móvil, Enter es retorno de carro, no envío. Resuelto sin incidencias.

  **4 — FASE 3 cancel+relaunch: cuatro iteraciones, rediseño final (commits
  `492b6e8`, `133b210`, `97d9d91`, `5e7f729`).**

  (a) *Diseño inicial de fusión automática* (`492b6e8`): mientras un turno estaba
  activo, los mensajes nuevos se acumulaban en `pendingQueueRef` y se fusionaban en
  un único turno relanzado tras el abort. En teoría correcto; en la práctica el bug
  no se reproducía en las pruebas porque los intervalos reales (8-14s) superaban el
  tiempo de respuesta de Sity — cada mensaje llegaba cuando ya no había turno activo.

  (b) *Diagnóstico real de la causa raíz* (`133b210`): la lógica de cola era correcta
  pero el botón nunca ofrecía la acción de envío durante generación — la condición
  `{canCancel ? <Stop/> : <Send/>}` mostraba siempre Stop con campo vacío, y nunca
  daba al usuario la oportunidad de activar el path de fusión.

  (c) *Fix de UI* (`97d9d91`): botón dinámico según contenido del campo —
  `{canCancel && !inputText.trim() ? <Stop/> : <Send/>}`. Alex confirmó que el icono
  de envío aparecía, pero al probar con mensajes con 8-14s de intervalo, los logs
  mostraron 3 POST independientes al backend. La fusión no activaba porque cada turno
  completaba antes del siguiente mensaje.

  (d) *Rediseño simplificado* (`5e7f729`): tras confirmar que el comportamiento de
  referencia de ChatGPT y Claude.ai no es fusión automática sino bloqueo simple del
  envío durante generación, se eliminó toda la lógica de cola (128 líneas netas).
  Diseño final: mientras `canCancel=true` el botón muestra siempre Stop; Enter y
  tap Send no hacen nada (el texto se conserva en el campo); solo Stop cancela el
  turno y habilita un envío nuevo. Cambios en `useChat.ts` + `ChatScreen.tsx`.

  **Lección:** verificar el comportamiento del producto de referencia antes de diseñar,
  no asumirlo. La fusión automática era sobre-ingeniería para un caso que no existe
  en los productos que se toman como modelo.

  **5 — Bug de logging temporal roto (`ece85ba`, corregido inmediatamente).**
  Al añadir `write_log()` de diagnóstico en `routes_chat.py`, los kwargs extra
  (`client_turn_id`, `text_len`) se pasaron directamente en lugar de dentro de
  `payload={}`. El endpoint POST /chat/message devolvía 500 en cada llamada. Causa
  detectada en <2 minutos por los logs del backend. Corregido y eliminado en el
  commit de rediseño final.

- **Suite de regresión de comportamiento — nueva (commit `67da655`, 2026-08-29)** —
  `tests/test_behavior_regression.py`, 10 tests (9 casos + 1 xfail marcado)
  con `@pytest.mark.behavior_regression`. No usan mock — llaman al modelo real
  (claude-haiku-4-5-20251001). Cubren: no sustitución terminológica, no afirmar
  detalles no declarados, no auto-citarse como evidencia, no narrar mecanismos
  internos de búsqueda, identificación correcta como Sity, respuesta a lenguaje
  informal, consistency de género gramatical, voseo al responder en español (xfail
  documentado: Haiku produce voseo inconstante, no es bug del código).
  Documentados en `docs/operations/development.md` con instrucción explícita de
  cuándo correrlos: manual, antes de deploys grandes o ante sospecha de regresión —
  no en el run rápido diario (cada test consume tokens reales).

## Completado recientemente (2026-08-25/26)

- **Memoria social narrativa — Capa 2 y Capa 3 (2026-08-25, commit `386e476`)** —
  implementado y desplegado el sistema de reflexión narrativa diseñado en
  `docs/social-memory-narrative.md`. El job `_run_social_update` en `social/update.py`
  genera ahora reflexiones de 2–4 frases (Pasos 7–10 post-commit principal) y las
  almacena en la tabla nueva `SocialReflection` junto con los IDs de evidencia de
  hasta 15 mensajes recientes. `_build_social_context_block` en `prompt_context.py`
  inyecta la reflexión activa en el prompt cuando existe: "Patrón observado: ...".
  Criterios de generación: ≥20 mensajes nuevos desde la última reflexión OR delta
  |opinion| ≥ 0.15. Caducidad automática a 30 días. 8 tests en
  `tests/test_social_memory_narrative.py`, todos en verde.
  Ver `docs/social-memory-narrative.md` para diseño completo.

- **Cadena de 5 bugs Google/TTS — mismo síntoma, causas distintas (2026-08-25)** —
  cinco bugs consecutivos con síntoma idéntico ("Sin respuesta del servidor" /
  respuesta sin audio), resueltos en cadena:

  **Bug 1 — Logging ciego en fallo de refresh** (`8cba21e`): `load_user_credentials()`
  en `google_auth.py` capturaba silenciosamente la excepción del refresh sin loguear
  cuál era el error real. Además, `last_refreshed_at` se actualizaba aunque el refresh
  hubiera fallado, haciendo imposible diagnosticar cuándo había ocurrido el error. Fix:
  logging detallado + campo `last_refreshed_at` corregido para no actualizarse en fallo.

  **Bug 2 — Segundo camino de credenciales obsoleto en pending actions** (`8189226`):
  `google_actions.py` (ejecutor de acciones confirmadas vía `pending_action_runner`)
  usaba un camino de resolución de credenciales diferente al de las tools. Este segundo
  camino no incorporó los cambios de la Fase 6 (integraciones self-service), dejando
  las acciones de usuario con tokens estancados. Fix: unificar ambos caminos en
  `get_user_credentials()`.

  **Bug 3 — TTS ausente en 3 caminos alternativos** (`2015263`): `pending_action_runner`,
  los background tasks (`_on_done` en ai_orchestrator) y el sistema de iniciativa propia
  construían sus respuestas sin llamar nunca al pipeline de síntesis. El flujo principal
  de chat tenía TTS; los caminos alternativos, no. Fix: centralizar en `maybe_attach_tts()`
  en el nuevo `app/audio/tts_service.py`. Los caminos de `local_final` también recibieron
  síntesis en este mismo commit (`b0ab039`), además de limpieza de URLs e IDs técnicos
  que el TTS no debería pronunciar.

  **Bug 4 — Hang de red sin timeout en 3 capas de la librería Google** (`69085ef` →
  `7bfa824` → `3c86d00` → `8b2cfa6`): el timeout de 10 s añadido en `creds.refresh` no
  era suficiente — `googleapiclient.discovery.build()` lanzaba una segunda petición de
  red para descargar el discovery doc, fuera del contexto del refresh. El transporte HTTP
  subyacente (`httplib2`) no aplica timeout por defecto en ninguna capa. Fix en 4 commits
  hasta llegar a la causa raíz real: (1) timeout en `creds.refresh` vía thread con
  `signal.alarm`; (2) `static_discovery=True` para eliminar la petición de discovery;
  (3) timeout por thread en `_google_call`; (4) `AuthorizedHttp` como adaptador que
  intercepta todas las peticiones con timeout explícito. La solución final (`8b2cfa6`)
  combina `static_discovery=True` + `AuthorizedHttp` como red de seguridad.

  **Bug 5 — Trigger de memoria social narrativa sin manejo de excepciones** (`269ea58`):
  `maybe_trigger_social_update()` en el paso 6.5 de `build_final_ai_response` lanzaba
  excepción (tabla `SocialReflection` aún no migrada en un deploy incompleto, o error en
  consulta). La excepción propagaba sin captura → la tarea de background moría → no se
  emitía el evento SSE `done` → el frontend mostraba "Sin respuesta del servidor". El
  texto y el audio ya habían sido generados y se perdían. Fix: try/except que loguea
  `social_update_trigger_failed` (WARN) y deja continuar el pipeline.

  **Falsa pista 1 — "bug de mensajes triviales":** en una sesión de depuración, un
  mensaje aparentemente trivial sobre el tiempo devolvió respuesta vacía. Se sospechó
  un bug del clasificador de `refusal_mode`. Resultado: era el mismo bug de Google auth
  (Bug 1), manifestándose porque el modelo infería por contexto que debería revisar el
  calendario del usuario, ejecutaba la tool de Google, el refresh fallaba silenciosamente,
  la tool devolvía nada, y la respuesta quedaba vacía o incompleta. El bug no estaba en
  el mensaje ni en el clasificador.

  **Falsa pista 2 — "turn_runner.py perdió logging":** al revisar la auditoría de logs,
  `chat_response_dispatch_failed` no incluía `error_type`. Se interpretó como pérdida de
  contexto en la extracción a `turn_runner.py`. Resultado: el campo nunca había existido
  en el código original — la extracción fue fiel. El audit (`14cf274`) lo añadió como
  mejora nueva, no como corrección de una regresión.

- **Refactor estructural: `background_dispatch.py` y `turn_runner.py` (commit `125e74a`)** —
  extraídos de `ai_orchestrator.py` (930→710 líneas) y `routes_chat.py` (467→192 líneas)
  respectivamente. Ver módulos chat en `docs/architecture.md` para responsabilidades.
  Los tests existentes se actualizaron para importar desde las rutas nuevas; suite completa
  pasó sin regresiones.

- **Limpieza de código y auditoría de logs (commits `1ab5bdf`, `14cf274`)** — 15 archivos
  con imports muertos eliminados, logging temporal de diagnóstico de Google eliminado tras
  confirmar el fix. Tres mejoras de trazas: `error_type` en `chat_response_dispatch_failed`,
  `module="social"` normalizado en `social_update_trigger_failed`, `engine` añadido en
  `tts_attached`. 2087 tests en verde.

## Completado recientemente

- **Sistema de iniciativa propia — dos rondas de verificación en producción
  (2026-08-19 → 2026-08-24, commits `c0cc4b3`→`e597072`)** — la implementación inicial
  (4 pasos, 2026-08-19) fue correcta estructuralmente, pero la verificación real descubrió
  4 bugs en dos rondas:

  **Ronda 1 (2026-08-19 → 2026-08-24) — 3 bugs bloqueantes:**

  1. **JSON fences en evaluator.py** (`c0cc4b3`): Haiku envuelve las respuestas JSON en
     bloques markdown (` ```json\n...\n``` `). `json.loads()` fallaba en todos los ciclos →
     skip permanente. Fix: `strip_json_fences()` antes del parse.

  2. **JSON fences en open_loop_hook.py** (`1e0f91b`, crítico): mismo bug pero silencioso
     — el fallback `{"has_intent": False}` hacía que NINGÚN OpenLoop se creara en producción
     desde el primer día. Fix: módulo compartido `_json_utils.py` con `strip_json_fences()`.

  3. **Dead zone por contexto auto-referencial** (`0680b8c`): `recent_messages_after_detection`
     incluía mensajes de Sity → Haiku veía "Sity ya preguntó" → skip indefinido sin cerrar el
     loop (`ol_aee77ee2` acumuló 715 evaluaciones en 4 días). Fix: filtrar a `role="user"` en
     `detector._check_open_loop()`. Red de seguridad: `open_loop_max_eval_attempts: 20`.

  **Ronda 2 (2026-08-24) — 1 bug de canal:**

  4. **Mensajes de iniciativa sin TTS** (`e597072`): `_dispatch_initiative()` guardaba el
     `ChatMessage` con solo texto, nunca sintetizaba audio. El flujo del `ai_orchestrator`
     no se hereda automáticamente en canales directos. Fix: `_maybe_synthesize_tts()` en
     `runner.py` que carga `VoiceSettings` del usuario y llama al `tts_dispatcher.py`
     existente. Fix adicional: `loadCurrentChat()` en el frontend ahora mapea `audio_filename`
     a artifacts para reproducir audio al recargar el historial.

  El pipeline completo verificado de principio a fin: detección de intención → OpenLoop en
  DB → evaluación con contexto limpio → envío con push notification + SSE + TTS según
  preferencia del usuario. Config TEMPORAL revertida. 2050 tests en verde.
  Ver `docs/proactive-initiative-architecture.md §16` para el historial completo.

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

## Completado recientemente (2026-08-13)

- **i18n Sistema 1 — cobertura completa de pantallas (2026-08-13)** —
  ampliadas las traducciones (es/en/ja) a las 5 pantallas que quedaban sin
  cubrir. Pantallas nuevas: ChatScreen, PersonalityScreen+AltersPanel,
  DatasetScreen, LoginScreen, RegisterScreen. Nuevas secciones en `T`:
  `chat` (16 claves), `personality` (11), `alters` (15), `dataset` (11),
  `auth` (33 — incluyendo errores de validación de contraseña localizados).
  `App.tsx` pasa `uiLang` a todas las pantallas. `checkPasswordStrength()`
  recibe `T['auth']` para devolver el error en el idioma activo.
  `AltersPanel` recibe `tl: T['alters']` desde `PersonalityScreen`.
  Fecha locale de mensajes expirados usa `DATE_LOCALE[uiLang]` (no
  hardcodeado `'es-ES'`). Placeholder japonés decorativo del textarea
  conservado intacto. Build TypeScript limpio. Commit: `f0aa0b3`.

- **Refusal_mode — arquitectura estructural completa (2026-08-13)** —
  sistema de negativas rediseñado de raíz tras varios intentos fallidos
  de control por instrucciones en el prompt. El principio rector: cualquier
  decisión que deba cumplirse de forma fiable debe tomarse en el backend,
  no delegarse al criterio del modelo dentro del mismo turno.

  **Estado final (flujo completo):**

  1. `PersonaEngine._should_refuse()` tira un dado (`random.random() < refusal_chance`)
     y devuelve `refusal_mode=True/False` — decisión determinista del backend,
     el modelo no interviene.
  2. Si `refusal_mode=True`: Haiku clasifica SIEMPRE el mensaje (sin bypass de
     longitud) como `trivial`, `config_query` o `real`. Cuando el último turno
     fue una negativa, el prompt de clasificación incluye contexto explícito de
     `last_was_refusal` para distinguir insistencia vs. pregunta nueva.
  3. **Ramas del árbol de decisión:**
     - `trivial` → bypass total; el modelo principal responde con normalidad.
     - `config_query` → el modelo principal responde, pero con un bloque de
       valores de configuración verificados inyectado (`build_verified_config_block`),
       para que no pueda inventar porcentajes del historial.
     - `real` + override explícito (`"es una orden"`) → el modelo responde con normalidad.
     - `real` sin override → **Haiku genera la negativa directamente** con la
       personalidad activa y la hora real verificada (`_build_refusal_time_fact`).
       El modelo principal NUNCA ve este turno. Respuesta guardada con
       `provider="haiku_refusal"`.
  4. `last_was_refusal` se almacena por sesión (dict `_last_refusal_by_session`
     en `refusal_tracker.py`) y se limpia en cada turno no-negativa. No hay
     estado global compartido entre sesiones.

  **Bugs encontrados y resueltos en el camino:**
  - Unicode U+2212 (MINUS SIGN) en tags `<R:−1>` → el regex de strip no hacía match;
    fix: normalización antes de la regex.
  - `get_last_refusal()` era una variable global de módulo, nunca se reseteaba entre
    turnos ni entre sesiones; tras la primera negativa, `last_was_refusal=True` para
    siempre en todas las sesiones del proceso. Fix: dict per-sesión + clear explícito.
  - Bypass de longitud (`_INSISTENCE_MAX_CHARS=15`) causaba falsos positivos en mensajes
    cortos tras cualquier negativa. Eliminado; el contexto se pasa como información al
    clasificador, no como atajo estructural.
  - Haiku inventaba horas ("3 de la mañana" cuando eran las 18:24) porque el prompt
    de generación de negativa no incluía datos de tiempo. Fix: `_build_refusal_time_fact()`
    inyecta hora local + UTC real en `_REFUSAL_GENERATOR_SYSTEM`.

  **Lección de diseño documentada:** cada vez que se dejó una decisión de "cumplir
  una regla firme" al criterio del modelo (via prompt), el modelo eventualmente cedió
  — con matices distintos cada vez (pre-fill contaminando la respuesta, guardarraíl
  ignorado, bypass calibrado incorrectamente, estado global sin aislamiento). La
  arquitectura estructural — backend decide, Haiku ejecuta, Sonnet no ve el turno —
  es la única forma de garantía real.

  Ver `docs/refusal-mode-architecture.md` para el diseño completo con historia de
  intentos fallidos y decisiones. Commits: `a525cfc`, `510a261`, `115ed3f`, `1da0d38`.
  1842 tests en verde.

- **Alters de personalidad — completo y verificado en real (2026-08-13)** —
  sistema de presets de personalidad guardados, completo en las 3 capas
  (modelo + servicio, endpoints REST, frontend con selector visual). Verificado
  en producción. 5 slots por usuario con nombre elegido; cargar un Alter aplica
  los 14 parámetros a la sesión activa y actualiza los sliders inmediatamente.
  Ver `docs/personality-alters.md` para diseño completo.

- **Ajustes de texto bilingüe — verificado en real (2026-08-13)** — tres
  iteraciones de ajuste visual en VoiceScreen, PersonalityScreen y PersonalitySliderItem:
  texto español primero / japonés debajo, 12px (Es) / 9px (Jp), colores intercambiados
  (`*Es` → `var(--text-primary)`, `*Jp` → `var(--text-secondary)`). Verificado en real.

## Completado recientemente (2026-08-12)

- **Regla de opacidad de arquitectura interna (2026-08-12)** — el modelo
  narró su mecanismo interno ("la búsqueda recupera un historial largo",
  "mirando el contexto visible (últimos 4 mensajes)") al interpretar el
  mensaje "¿Cómo estamos ahora?" como consulta de memoria y usar
  `search_conversation_history`. Diagnóstico: la regla previa (líneas 74-82
  de `persona_system.md`) solo prohibía narrar el ACTO de buscar, no el
  estado o resultado del contexto en términos de mecanismo. Fix: regla
  ampliada como principio general — Sity nunca describe su arquitectura de
  memoria/contexto/búsqueda como sistema técnico, ni el acto de buscar ni el
  resultado. Si no tiene información suficiente, pide aclaración como una
  persona real. Ejemplos ilustrativos incluidos, con nota explícita de que
  no son lista exhaustiva.

- **Latencia 19 min (2026-08-12, descartada como bug de backend)** — trace
  `trc_3de1a136c203`: mensaje enviado ~22:12 UTC, `ai_call_started` 22:31:39
  UTC, procesamiento de AI 6 segundos. Los 19 minutos transcurrieron antes de
  que el backend iniciara la llamada — el mensaje estaba retenido en la
  conexión SSE o tab suspendido por el SO. No es bug reproducible del backend.

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

- **Geolocalización real del usuario** — Sity no tiene acceso a la ubicación
  aproximada del usuario (a diferencia de Claude.ai, que recibe esta señal de
  la plataforma). Verificado 2026-09-03: el único campo `location` existente en
  el código es de dispositivos de Home Assistant (`ai_request_builder.py`), no
  del usuario. Idea para el futuro, sin diseño técnico aún.

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
- **Gestión de archivos subidos** — desde 2026-08-11 hay un placeholder visible en
  la pantalla Ajustes ("gestión de archivos"), pero no hay implementación ni diseño
  formal. Lo que existe: la tabla `ChatMessage` puede llevar `audio_filename` (STT
  y TTS), y hay capturas de cámara en `data/captures/`. Lo que falta inventariar y
  diseñar antes de implementar: (a) **inventario completo de artefactos** — qué tipos
  de archivo genera Sity (capturas, audio de voz, audio TTS, posibles adjuntos futuros),
  dónde se almacenan, y qué metadatos existen en DB para cada uno; (b) **frontend de
  listado y borrado** — pantalla o sección en Ajustes que permita ver los archivos del
  usuario y eliminarlos individualmente o en bloque; (c) **política de retención** —
  `audio_cleanup_days` ya existe en config para audios, pero no hay limpieza automática
  ni UI para configurarla; (d) **privacidad**: si se permite exportar el historial de
  conversación (ya existe `GET /chat/export`), ¿se incluyen o excluyen los archivos
  binarios asociados? No bloquea ningún flujo actual; pendiente de sesión dedicada de
  diseño antes de picar código.
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
- **ElevenLabs: mapeo voice_id por idioma** — si Sity responde en inglés
  pero la voz ElevenLabs configurada es en español, el acento/pronunciación
  serán incorrectos. La API de ElevenLabs no selecciona voz por idioma
  automáticamente. Solución: sustituir el único `elevenlabs_voice_id` en
  config por un mapa `{es: ..., en: ..., ja: ...}`, detectar el idioma del
  turno desde `language_override` del TurnContext y seleccionar el voice_id
  correcto en `maybe_attach_tts`. Requiere que Alex consiga/configure una
  voz ElevenLabs en inglés antes de implementar. No bloquea el uso normal
  con un único idioma.
- **Idioma en caminos alternativos (pending actions, model-router, guards)** —
  `pending_action_runner` y los guards (`local_flow`, `budget_guard`,
  `user_message_guard`) usan strings hardcodeados en español sin pasar por
  `language_override`. Fix requiere threadear `language_override` desde
  `TurnContext` → `LocalFlowContext` + plantillas por idioma en cada handler.
  Impacto real solo si Alex configura `language_override=en`; hoy el sistema
  opera en español exclusivamente.
- **Modo de voz en tiempo real (estilo "Live" de ChatGPT)** —
  estudiar el streaming bidireccional de audio sin turnos discretos
  de grabación-envío-respuesta, y valorar si el hardware de la Pi lo
  soportaría con la latencia necesaria.
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

- **Pantalla "Logros" — COMPLETO** (commits `2cd013d`→`b651d1d`, 2026-08-28→2026-08-31).
  Sistema completo: 42 logros en 6 categorías, frontend propio, notificaciones push al
  desbloquear. Ver `docs/achievements-architecture.md` para catálogo y arquitectura.

  **6 commits principales de la implementación completa:**
  - `5e95ee8` — Fase 2b: triggers post-turno (distancia personalidad, trust, rachas, antigüedad cuenta)
  - `fd7ee66` — Fase 2c: clasificador Haiku para `no_gods_no_masters`, `tsundere`, `you_win` + `curiosity_killed_the_cat` inline
  - `1953534` — Paso 3: pantalla de logros en frontend (catálogo visual por categorías)
  - `c41d34d` — catálogo limpio definitivo: 42 logros aprobados (retirados 4 no aprobados en revisión)
  - `5877ceb` — UI: fuentes grandes, color rosa de desbloqueo, sonido
  - `24761fa` — notificación global + push cuando la app está cerrada

  **3 bugs encontrados durante verificación en producción:**
  - `e88ce35` — `hello_world` mal categorizado en Memoria en lugar de Personalidad
  - `f997c99` — Sity negaba tener sistema de logros ("No tengo visibilidad sobre eso")
  - `135258c` — `chaos_head` nunca se desbloqueaba: `_check_personality` leía globals (chaos=0.84) en lugar de la sesión del usuario (chaos=1.0)

  **Fórmula del "encabronamiento"** (confirmada en `mobile/src/screens/PersonalityScreen.tsx:13-19`):
  ```
  computeMoodLevel = round(
    rudeness_level  × 0.4 +
    sarcasm_level   × 0.3 +
    contrarian_level × 0.2 +
    dry_humor_level × 0.1
  ) × 100
  ```
  Colores por rango: ≤25 → cian `#00f5ff`, ≤50 → verde `#00ff80`,
  ≤75 → naranja `#ff8000`, >75 → magenta `#ff00ff`.

  **6 pestañas/categorías del catálogo:**

  1. **Personalidad** — logros relacionados con configuración de sliders: alcanzar
     valores extremos, combinaciones específicas de parámetros, mantener el nivel
     de encabronamiento en zonas concretas durante N sesiones, etc.

  2. **Tools** — logros por uso de herramientas: primera búsqueda web, primera
     acción de domótica, primer timer creado, primer mensaje de voz enviado,
     uso acumulado de N herramientas distintas, etc.

  3. **Memoria** — logros relacionados con la memoria de conversación y el sistema
     social: primera búsqueda en historial (`search_conversation_history`), primera
     reflexión narrativa generada (SocialReflection), milestones de mensajes totales
     (100, 500, 1000, 5000), etc.

  4. **Secretos** — logros ocultos que se desbloquean por comportamientos específicos
     no documentados en la UI: frases especiales, combinaciones de personalidad,
     patrones de interacción inusuales. La lista exacta es opaca por diseño.

  5. **Domótica + Integraciones** — logros por uso de Home Assistant (primera bombilla
     encendida, primera escena activada), Google Calendar (primer evento creado),
     Gmail (primera búsqueda), Spotify (primera canción puesta, primer skip), etc.

  6. **Tareas en background** — logros por uso del sistema de iniciativa y timers:
     primer mensaje proactivo recibido, primer timer de larga duración, primer
     background task completado, etc.

  **Regla de arquitectura confirmada:** no encadenamiento automático de logros —
  un logro desbloqueado no dispara automáticamente la comprobación de otros.
  Cada logro tiene su propio trigger/evento; el sistema no evalúa el catálogo
  completo en cada turno.

  **Diseño cerrado — decisiones ya confirmadas con Alex (no volver a discutir desde cero):**

  **1. "Who Am I?" — umbral de cambio de personalidad**
  Distancia euclídea NORMALIZADA sobre el vector de 15 parámetros de personalidad.
  La distancia cruda se divide entre el máximo teórico √15 ≈ 3.87, dando un rango
  0–1. Umbral: `>= 0.5` (recorrer al menos la mitad del cambio máximo posible).
  El umbral es deliberadamente exigente: 3 parámetros movidos 0.3 cada uno
  producen distancia cruda √(0.09×3) ≈ 0.52, normalizada ≈ 0.13 — muy por debajo
  del umbral, no cuenta. Se requiere un cambio global sustancial, no retoques menores.

  **2. "Remember Me" — umbral de memoria social**
  `trust >= 0.30` — mismo umbral que `initiative_min_trust`. Coherencia explícita:
  si el sistema de iniciativa ya usa 0.30 como criterio de "relación estable",
  este logro usa el mismo punto de corte.

  **3. "The Memory Remains" — detección de búsqueda histórica**
  Opción barata sin llamada extra a Haiku: comprobar que al menos un resultado
  devuelto por `search_conversation_history` tiene antigüedad `>= reflection_min_age`
  (configurable en `default_config.yaml`, valor orientativo 7 días — no hardcodeado).
  Decisión explícita de Alex de mantenerlo simple dado que este logro se desbloquea
  probablemente una sola vez.

  **4. Clasificador genérico para logros de comportamiento sutil**
  Función única `classify_behavior_pattern()` (o nombre equivalente) que en UNA
  sola llamada por turno evalúa TODOS los patrones de comportamiento aún no
  desbloqueados por el usuario: "No Gods No Masters" (contradicción sistemática),
  "Tsundere" (patron tsundere), "You Win" (rendición ante Sity), y cualquier otro
  que se añada en el futuro. Los patrones se describen en texto en la misma llamada;
  Haiku devuelve cuáles aplican al turno actual. El coste se reduce automáticamente
  con el tiempo: a medida que el usuario desbloquea logros, quedan menos patrones
  por evaluar y la llamada se hace más barata — hasta que todos están desbloqueados
  y la función deja de llamarse.

  **5. "Achievement (Un)locked" — arquitectura de detección opaca (pieza más delicada)**
  El conocimiento de qué patrones activan logros vive ÍNTEGRAMENTE en el BACKEND,
  en una llamada separada a Haiku (mismo patrón que `open_loop_hook` — fuera del
  flujo de conversación principal) que analiza el historial reciente buscando
  "exploración sistemática de funcionalidades, patrón de comportamiento que sugiere
  caza de logros".

  **El modelo principal de conversación NUNCA sabe que este sistema existe.**
  Motivo explícito (mismo aprendizaje que la odisea de refusal_mode/lie_mode):
  cualquier información sensible dentro del prompt principal ("no reveles esto")
  es vulnerable a filtrarse con insistencia o prompt injection; si el modelo ni
  siquiera conoce el sistema, es estructuralmente imposible que lo revele.

  Esto también resuelve limpiamente el caso de "Curiosity Killed the Cat" (usuario
  pregunta cómo desbloquear un logro): el modelo principal responde sobre logros
  en general con su propio criterio, sin revelar mecanismos concretos. La detección
  de "caza sistemática" ocurre en un sistema completamente aparte que nunca interpreta
  "preguntar una vez sobre logros" como señal sospechosa.

  **Modelo de datos y presentación en UI:** pendientes de implementar (no diseñados
  aún en detalle), pero el diseño de detección está cerrado. La implementación
  en sí sigue aparcada hasta que se decida empezar a picar código.

- **Sistema de perfiles personales por hablante** *(muy a futuro)* — idea de
  roadmap que existía antes de julio 2026 y que conviene preservar documentada
  para no redescubrirla desde cero. No está en el plan activo; se registra aquí
  como contexto de diseño para cuando el momento sea el correcto.

  Sity actualmente trata todas las interacciones como si vinieran del mismo
  interlocutor por sesión. El sistema de perfiles personales añadiría:

  - **Reconocimiento de personas** — identificar quién está hablando dentro de
    una sesión compartida (familia, compañeros de trabajo). El mecanismo concreto
    (voz, perfil activo seleccionado manualmente, señal contextual) queda sin
    decidir hasta que el caso de uso se defina con más concreción.

  - **Pseudo-opiniones por hablante** — el sistema de `opinion`/`trust` de
    `SocialProfile` existe a nivel de `user_id`. Con perfiles por hablante, cada
    persona reconocida tendría su propia trayectoria de `opinion`/`trust` y su
    propia reflexión narrativa de `SocialReflection`.

  - **Confianza diferenciada** — Sity podría mantener un registro de confianza
    distinto para cada hablante: compartir información de la agenda con el dueño
    de la cuenta pero no con un invitado reconocido como tal.

  - **Privacidad por perfil** — decisión de diseño no resuelta: ¿quién puede
    ver qué datos de qué perfil? ¿El dueño de la cuenta puede ver los datos de
    otros perfiles? ¿Hay datos marcados como privados por hablante?

  **Por qué es "muy a futuro":** requiere resolver el mecanismo de identificación
  (voz → problema técnico no trivial en Pi; selección manual → fricción de UX),
  el modelo de privacidad, y el aislamiento de datos entre perfiles en un sistema
  que hoy asume un único propietario. No desbloquea ningún caso de uso bloqueante
  en el estado actual del proyecto.

## Bugs conocidos activos

**Tests flaky conocidos (baja prioridad, no bloquean nada):**

- **`test_initiative_step3.py::TestEvaluatorRateLimits::test_daily_max_hit_returns_rate_limited`**
  (introducido en commit `cbca465`, 2026-08-24):
  Falla con `skip_reason == 'cooldown_active'` en lugar de `'rate_limited'` cuando se ejecuta
  en la suite completa. Pasa siempre en aislamiento (`pytest tests/test_initiative_step3.py`).
  Causa: contaminación de orden — un test anterior deja estado `cooldown_active` en la DB de
  test compartida; el evaluador lo detecta antes del check de `rate_limited` (cooldown se evalúa
  primero en el código). No afecta producción. Fix: añadir teardown/cleanup de `cooldown_active`
  en los tests anteriores de `TestEvaluatorRateLimits`. Pendiente de sesión de mantenimiento.

**Resueltos recientemente (2026-08-12):**

- **Inferencia de herramientas por contexto ambiental — Problema B** (2026-08-12):
  El modelo llamó a `list_timers` ante "¿Cómo estamos ahora?" en una sesión con
  historial previo de timers, sin que el mensaje lo mencionara. `list_timers` estaba
  en BASE_TOOLSET ("always available"); el modelo infirió el tema del contexto ambiental.
  Fase 1 (parche B+C, insuficiente): descriptions reforzadas + guardarraíl en
  `persona_system.md`. El modelo ignoró el guardarraíl (confirmado en trace
  `trc_8c1f888e764f`). Fix estructural — Fase 2 (Opción A): timers movidos a
  `TIMERS_TOOLSET`, activado únicamente por `_TIMER_RE` regex en `toolset_selector.py`.
  Timer tools literalmente ausentes del toolset para mensajes sin keywords de timers.
  Fix re-confirmado vigente en código (2026-08-24). 8 tests en `test_toolset_selector.py`.

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

## Ideas descartadas por límite del modelo (no re-intentar sin cambio de enfoque)

### Probabilidad de mentira configurable (lie_chance) — descartada 2026-08-14

**Qué se intentó:** Nuevo parámetro `lie_chance` (0–100%) en el slider de personalidad.
Cuando el backend calculaba `lie_mode=True` (determinista, mismo patrón que `refusal_chance`),
se le instruía al modelo que incluyera información falsa o inventada en su respuesta.

**Dos arquitecturas probadas, ambas fallaron:**

1. **Instrucción en prompt del modelo principal** — `_LIE_INSTRUCTION` inyectada como texto
   en el system prompt antes del turno. El modelo principal ignoraba la instrucción o la
   cumplía parcialmente (mencionaba algo falso sobre un tema distinto al preguntado).

2. **Generación estructural con Haiku dedicado** — mismo patrón exacto que `refusal_mode`
   estructural (`haiku_lie`, `generate_lie_response()`), con el mensaje real del usuario
   embebido en el prompt para que Haiku supiera sobre qué mentir específicamente. Claude
   (incluso Haiku) activó sus protecciones de seguridad contra jailbreak — la combinación
   "miente sobre esto" + "no reveles que estás mintiendo" es indistinguible, desde la
   perspectiva del modelo, de una instrucción maliciosa real, independientemente de que el
   usuario conozca la configuración y la haya activado él mismo.

**Por qué no es un problema de ingeniería resoluble:** El modelo tiene valores de honestidad
entrenados que se activan ante instrucciones de mentira + ocultamiento activo. No es un bug
de prompt engineering — es un límite de alineación deliberado del modelo. Cambiar el modelo
(Haiku vs Sonnet) no resuelve el problema; ambos lo rechazaron.

**Alternativa considerada y descartada por Alex:** Reformular como "personalidad juguetona o
exagerada" (el modelo inventa cosas pero en modo lúdico, sin instrucción de ocultamiento).
Podría retomarse con ese enfoque distinto si se quisiera una versión menos estricta del
concepto original.

---

## Qué no hacer

- No activar SITY_LOCAL_AI_ENABLED=true en producción sin modelo validado
- No subir data/, datasets/, work/ a git
- No tocar /etc/asound.conf ni el pipeline HDMI (ver raspberry-setup repo)
- No modificar data/app.db en producción

## Verificación correcta de deploy

"push hecho" ≠ "desplegado". Dos pasos, ambos obligatorios:

1. **Confirmar que el commit llegó al remoto:**
   `git fetch origin && git log origin/main -1`
   Verifica el hash. Si no coincide con el commit local, el push falló.

2. **Confirmar que el proceso lo cargó:**
   Buscar el evento `backend_started` en `data/logs/app-YYYY-MM-DD.jsonl`
   y verificar que `payload.git_commit` coincide con el hash esperado.
   El proceso puede estar corriendo con una versión anterior si el reinicio
   falló o si se reinició antes del push.

Omitir el paso 2 causó rondas de diagnóstico circular en 2026-08-13:
el código local estaba bien, los tests pasaban, pero el proceso en
producción seguía con la versión anterior — y los síntomas eran idénticos
al bug que se acababa de corregir.

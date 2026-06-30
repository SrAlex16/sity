# Decisiones de arquitectura

## 2026-06-29

### Imágenes (visión)

- Fase 1 (actual): imágenes enviadas siempre a Claude API (Haiku).
  No hay caché de imágenes — cada imagen es contenido nuevo.
  Sí se cachea todo lo que rodea la imagen (system prompt, tools,
  historial) con prompt caching existente.
- Fase 2 (tras fine-tuning multimodal): imágenes procesadas por
  modelo local Gemma con capacidad multimodal.
  El dataset de imágenes se acumula durante la Fase 1.

### Caché de web_search

Los resultados de web_search se cachean en SQLite con TTL:
- Noticias / contenido dinámico: 1 hora
- Documentación técnica: 24 horas

No se cachean las queries en sí, sino los resultados por URL/query hash.
Pendiente de implementar.

### Google OAuth

- Scopes: Gmail readonly, Calendar read+write, Drive readonly
- Credenciales: client_id + client_secret en .env (nunca en el repo)
- Token OAuth: guardado en archivo local en la Pi, fuera del repo
- Primera autenticación: manual una sola vez (URL en navegador)
- Cuenta: fija (alex) en .env. Sin UI para cambiar cuenta por ahora.
- Posición en roadmap: después de visión (imágenes)

### Tool handlers — extracción mínima

Los handlers de Google (y futuros) aplican extracción estructurada
antes de pasar datos al modelo, sin intervención del LLM:
- Email: primeros 2.000 caracteres + campos clave (de, asunto, fecha)
- Calendario: eventos próximos 7 días, campos mínimos
- Drive: solo metadatos salvo que Claude pida el contenido explícitamente

Diseño lazy: Claude solicita más información en tool calls adicionales
si necesita. Evita volcar contexto innecesario.

Compatibilidad con Gemma: los handlers aceptan un parámetro de modo
(`'claude' | 'gemma'`). En modo Gemma la extracción es más estricta
(menos texto, más estructura, sin texto libre largo). El model router
pasa el modo activo al tool executor en cada turno.

### Domótica

Sin código por dispositivo. Enfoque:
1. Tool genérica `local_http_request` o `run_python_script`
2. Sity usa web_search para encontrar la API del dispositivo
3. Sity ejecuta la llamada via la tool genérica

Restricciones de seguridad pendientes de diseñar:
- Solo IPs rango local (192.168.x.x)
- Solo puertos conocidos
- Confirmación del usuario para acciones irreversibles

Posición en roadmap: después de Google OAuth.

### Alertas del panel — roadmap

Implementadas: sity-backend (critical), caddy (grave),
cloudflared (medium), cpu-high (medium), cpu-temp (grave).

Pendientes:
- Disco >95% (critical)
- RAM >90% sostenida (grave)
- Disco >80% (medium)
- Temperatura 70-80°C (low)
- Zombies >5 (low)
- Historial de alertas con timestamps
- Uptime por servicio
- Logs on-click en barra de servicios

## 2026-06-29 (sesión 2)

### Refactorización persona_engine — literales hardcodeados

Completado el batch 2 de la auditoría de literales (A3-A6, B5-B6).

**A3 — CRITICAL_KEYWORDS a config**
La lista de keywords que bypass refusal_mode estaba hardcodeada
en Python. Movida a config/persona.yaml bajo
refusal.bypass_keywords. El código lee la lista al
importar el módulo via load_default_config(). Añadir o quitar una keyword
ya no requiere tocar código ni reiniciar el backend.

**A4, A5 — Instrucciones de override y refusal a constantes de módulo**
Los bloques de texto _ORDER_OVERRIDE, _REFUSAL_ACTIVE y
_REFUSAL_INACTIVE estaban inline en build_persona_prompt().
Extraídos a constantes de módulo — se cargan una vez al importar.
La lógica condicional (qué bloque usar) sigue en el método.

**A6 — Directivas de estilo a constantes de módulo**
29 constantes _DIR_* (path cloud) y 25 constantes _LOC_* (path
local) extraídas de _build_style_directives y
_build_local_voice_directives. Los métodos quedan como lógica
pura (if/elif + append) sin ningún string literal inline.

**B5, B6 — Umbrales de personalidad a config y unificación**
Los umbrales 0.8/0.2 (cloud) y 0.75/0.25 (local) estaban
hardcodeados en Python y eran inconsistentes entre paths.
Unificados en config/persona.yaml bajo
style_thresholds.high/low (0.80/0.20).
Ambos paths leen los mismos valores al inicializar el módulo.

### Panel de control — nota operacional

Tras cambios en panel/, el flujo correcto es:
```
npm run build    ← compila TypeScript
npm run package  ← actualiza el binario en release/
```
Solo después de `package` el autoarranque (/etc/xdg/autostart/)
y el icono del escritorio usan el código nuevo.

## 2026-06-30

### Canal de divulgación Tech & IA — especificación futura

Documentada en docs/canal-spec.md. Sity actuaría como orquestadora
de un canal de YouTube de divulgación tech/IA, con revisión humana
obligatoria en cada paso crítico (mismo principio de pending action
+ confirmación que ya tiene Sity).

Posición en el roadmap: después de domótica. Depende de tener
tool-calling maduro y el patrón de specialist agents asentado.

**Notas de Claude (revisión de la spec):**

- Medir coste real de Sonnet en el primer guion generado antes de
  asumir que el coste semanal es trivial.
- Fase C (imágenes): priorizar capturas reales y stock sobre
  generación con IA al inicio — más barato, sin riesgo de licencia,
  y coherente con la transparencia que es el diferenciador del canal.
- Verificar costes de Twitter/X API antes de implementar Fase F
  para esa plataforma — han cambiado varias veces y pueden no
  compensar para un canal que empieza.
- Añadir gate de calidad antes de avanzar de fase: no implementar
  fetch_metrics ni comentarios automatizados hasta validar el
  formato con al menos 3 guiones aprobados sin ediciones mayores
  por parte de Alex. Evita sobre-construir antes de saber si el
  formato funciona.

**Orden de implementación cuando se aborde** (de canal-spec.md
sección 10):
1. Tabla news_items en SQLite
2. config/content_sources.yaml
3. Ampliar system_access.yaml con rutas de /home/alex/canal/*
4. Tool fetch_rss_news (sin Claude, feedparser local)
5. Tool generate_script (Claude Sonnet + DOCX)
6. Validar ciclo completo y calidad antes de continuar
7. Tool generate_tts (ElevenLabs, con confirmación)
8. Tool upload_youtube (con confirmación)
9. Tool fetch_metrics
10. Sistema de comentarios con revisión humana en batch
11. Evaluar montaje online (Shotstack/Creatomate) si procede

## 2026-06-30 (sesión 2) — fixes de UX y comportamiento

### Lag en el input del chat móvil

Causa real: ChatScreen renderizaba la lista completa de mensajes
(AnimatePresence + Framer Motion) en el mismo componente que el
textarea. Cada tecla pulsada disparaba setInputText, que
re-renderizaba también la lista completa de mensajes — costoso
con Framer Motion en conversaciones largas.

Primer intento (debounce de localStorage) no resolvió el problema
porque la causa no era el I/O a disco sino el re-render de la
lista de mensajes.

Fix definitivo: extraído MessageList a componente separado con
React.memo. handleAudioPlay/handleAudioEnded envueltos en
useCallback para no romper la memoización por cambio de
referencia. El input ya no provoca re-render de los mensajes.

Lección: con estado elevado a App.tsx (useChat vive ahí desde
una sesión anterior), cualquier componente hijo que reciba listas
grandes como prop debe memoizarse explícitamente, o cualquier
cambio de estado local en el padre las re-renderiza igualmente.

### refusal_mode sin criterio sobre el contenido del mensaje

_should_refuse() decidía con un roll de probabilidad puro, sin
evaluar si la petición era trivial/de ocio (el caso para el que
refusal_mode está pensado) o sustancial (opinión personal genuina,
decisión real del usuario). Causaba negativas incoherentes en
preguntas legítimas.

Fix: el roll de probabilidad sigue decidiendo si refusal_mode
está "disponible" en el turno, pero _REFUSAL_ACTIVE ahora da al
modelo un criterio explícito para evaluar el mensaje antes de
ejercerlo. Si la petición no es trivial, el modelo puede no
aplicar la negativa aunque esté disponible.

tone_snapshot documentado: "active" = disponible para el turno,
no implica que el modelo lo haya ejercido en la respuesta final.

### Alucinación de hechos no verificados

Sity inventaba detalles específicos (nombres de archivo, acciones
del usuario) al responder preguntas tipo "¿qué he hecho hoy?"
porque no tenía ninguna tool que diera datos reales sobre
actividad del usuario fuera del chat — solo tenía
search_conversation_history (chats pasados) y read_own_trace
(sus propios turnos).

Fix de dos partes:
- Regla anti-invención reforzada en persona_system.md: distinguir
  explícitamente entre información real (contexto/tools) y
  contenido plausible inventado. Preferir "no lo sé" a una
  respuesta inventada que suene segura.
- git_read_log mejorado con parámetro hours_back y description
  explícita: acceso real de solo lectura al historial de commits.
  Sin pending action (solo lectura, sin riesgo).

Patrón general: cuando el usuario pregunta por algo que requiere
datos reales del sistema/proyecto y Sity no tiene tool para ello,
el síntoma es invención de contenido plausible. La solución
sistemática es dar la tool real, no solo reforzar la instrucción
de "no inventes" — la regla ayuda pero no sustituye tener la
fuente de verdad disponible.

## 2026-06-30 (sesión 3) — Visión (imágenes) implementada y depurada

### Implementación inicial

Soporte de imágenes en el chat vía Claude API multimodal:
- AIRequest extendido con campo `images: list[dict[str, str]]`
- ClaudeProvider construye content blocks `[image, text]` cuando hay imágenes adjuntas
- ChatMessageRequest acepta `images` con validación de tipo (jpeg/png/webp/gif) y tamaño (máx 5MB)
- Botón del clip en mobile, antes placeholder sin función, ahora funcional: selección de archivo,
  redimensionado a 1024px máx en cliente (canvas, ahorro de tokens), preview antes de enviar
- `persona_system.md` actualizado: Sity puede ver imágenes

### Bug encontrado: el planner no veía las imágenes

La implementación inicial propagaba `images` correctamente al chat normal y al `after_tools`,
pero NO a `build_planner_ai_request` — el planner (quien decide si usar `web_search` u otra tool)
evaluaba el mensaje sin contexto visual. Resultado: peticiones como "busca quién es esta persona
de la foto" caían a `no_action_required` porque el planner no veía nada que justificara una búsqueda.

Fix: `build_planner_ai_request` acepta y propaga `images`. Confirmado con logs reales
(`data/logs/app-YYYY-MM-DD.jsonl`) que tras el fix el planner sí invoca `web_search`
con `tool_calls_count: 1` al recibir una imagen con petición de búsqueda.

Lección: cuando se añade un campo nuevo a `AIRequest`, hay que verificar TODOS los builders
que lo construyen (planner, chat, after_tools, local), no solo los que parecen obviamente
relacionados con la feature.

### Calidad de queries con imagen

Tras el fix del planner, las queries generadas para `web_search` con imagen eran demasiado
genéricas y mezclaban idiomas (ej: "manga girl character antifaz gorro de punto"). Añadida
regla específica en el prompt del planner: describir rasgos visuales distintivos, idioma
coherente, incluir sospechas de autor/serie aunque no haya certeza total.

Validado con prueba real: una imagen de un personaje de manga poco conocido no fue identificable
ni por Sity ni por ChatGPT sin contexto adicional — confirma que el límite no era de
implementación sino de información disponible. Con una pista del usuario (autor de la obra),
Sity resolvió correctamente usando conocimiento propio sin necesitar nueva búsqueda.

### Persistencia de imágenes

Las imágenes NO se persisten en el backend: viajan en base64 en el payload JSON, se usan para
la llamada a la API de Anthropic, y no se escriben a disco ni a SQLite en ningún punto del flujo.
En el frontend, la preview vive en estado de React (`useChat`), no en localStorage — desaparece
al recargar.

Pendiente para el futuro: si se decide guardar imágenes para generar dataset multimodal
(fine-tuning de Gemma), diseñar política de retención con borrado automático desde el principio,
no añadir persistencia primero y política de borrado después.

---

## 2026-06-30 (sesión 4) — Google OAuth implementado y depurado

### Integración inicial

OAuth2 con Google para Gmail, Calendar y Drive:
- Scopes: gmail.readonly, calendar.readonly, calendar.events, drive.readonly
- Credenciales: client_id/client_secret en backend/.env (nunca en repo)
- Token: data/google_token.json, fuera del repo (.gitignore)
- Primera autenticación: flujo manual con URL + código de copiar/pegar
  (no depende de servidor local — compatible con SSH sin X forwarding)
- Refresh automático del access_token sin intervención del usuario

Tools implementadas:
- gmail_search: solo lectura, filtra por bandeja Principal por defecto
  (category:primary). NO puede enviar, borrar, archivar ni modificar.
- calendar_list_events: lista eventos futuros, devuelve event_id
- calendar_create_event: crea eventos con pending action + timezone
  del sistema (timedatectl, fallback Europe/Madrid)
- calendar_edit_event: edita eventos por event_title O event_id —
  busca internamente por título si no hay event_id
- calendar_delete_event: borra eventos con pending action,
  mismo patrón de búsqueda por título
- drive_search: busca archivos por nombre en todo el Drive
- drive_list_folder: lista contenido de una carpeta específica
  o el Drive raíz si no se especifica carpeta

### Bugs encontrados y resueltos

**Bug 1 — GOOGLE_TOOLSET con regex de keywords frágil:**
El selector activaba las tools de Google solo si el mensaje contenía
palabras exactas ("correo", "agenda", etc.). Preguntas naturales como
"¿qué tengo hoy?" no activaban nada — el planner nunca veía las tools.
Fix: GOOGLE_TOOLSET eliminado, las 7 tools integradas en BASE_TOOLSET.
Siempre disponibles para el planner, sin clasificación por keywords.
Coste extra mínimo por el cacheo de prompts existente.

**Bug 2 — Timezone faltante al crear eventos:**
HttpError 400 "Missing time zone definition". La API de Google Calendar
requiere timezone en los eventos. Fix: _get_system_timezone() lee la
timezone con timedatectl (fallback Europe/Madrid).

**Bug 3 — Sity inventaba capacidades de Gmail:**
Con scope gmail.readonly, Sity decía que podía "marcar como leído,
archivar, eliminar". Fix: descripción del tool y reglas del planner
explícitas sobre los límites reales del scope.

**Bug 4 — Gmail no filtraba por bandeja Principal:**
Sin filtro explícito, la búsqueda incluía Promociones, Social y
Notificaciones. Fix: category:primary añadido automáticamente a la
query salvo que el usuario especifique otra bandeja.

**Bug 5 — Drive no encontraba carpetas por mayúsculas/acentos:**
La query usaba name = 'X' (exacto, case-sensitive). Fix: cambiado a
name contains 'X', que tolera variaciones de mayúsculas y acentos.

**Bug 6 — Drive listaba archivos compartidos en vez del Drive propio:**
La query por defecto devolvía archivos de otros. Fix: query vacía
usa 'me' in owners con orderBy por fecha de modificación.

**Bug 7 — drive_list_folder buscaba carpeta "root" cuando se pedía la raíz:**
El modelo pasaba folder_name="root" para listar el nivel superior.
Fix: aliases detectados (root, raíz, inicio...) → 'root' in parents.

**Bug 8 — calendar_edit_event nunca se llamaba (bug estructural):**
El planner hace UNA sola tool call por turno. El flujo "list eventos
para obtener event_id → edit en el turno siguiente" no funcionaba
porque el resultado del primer turno no llegaba al planner del segundo.
Fix estructural: calendar_edit_event y calendar_delete_event aceptan
event_title. El handler busca el event_id internamente antes de crear
la pending action — todo en una sola tool call.

**Bug 9 — Planner usaba search_conversation_history antes de actuar:**
Cuando el usuario daba todos los datos ("añade X al evento Y"), el
planner llamaba a search_conversation_history en vez de actuar
directamente. Fix: regla de acción directa en el prompt del planner:
si el mensaje contiene todos los datos necesarios, ejecutar la tool
sin pasos previos de "preparación".

### Lecciones aprendidas

- Las tools de Google deben estar siempre en BASE_TOOLSET: cualquier
  mecanismo de selección por keywords es frágil porque el lenguaje
  natural es impredecible. El coste de tenerlas siempre disponibles
  es bajo con el cacheo de prompts.
- El planner de una sola tool call por turno no puede hacer flujos
  encadenados (list → edit). Diseñar tools que sean autocontenidas:
  que resuelvan internamente lo que necesitan (buscar el event_id)
  sin depender del contexto de turnos anteriores.
- search_conversation_history es una "herramienta de procrastinación"
  cuando el modelo no sabe qué hacer. La regla de acción directa
  evita que se use como paso previo innecesario.

### Capacidades actuales de Google en Sity

Gmail: solo lectura/búsqueda. Bandeja Principal por defecto.
Calendar: leer eventos, crear eventos (pending action), editar
eventos por título o ID (pending action), borrar eventos (pending action).
Drive: buscar archivos por nombre, listar contenido de carpetas,
listar el Drive raíz.

Pendiente (no implementado aún):
- Gmail: envío de correos (requeriría scope gmail.send)
- Calendar: gestión de recordatorios/alertas en eventos
- Drive: leer contenido de archivos (solo metadatos por ahora)
- Drive: subir/crear archivos en Drive

---

## 2026-06-30 (sesión 4 cont.) — Fixes de UX y comportamiento

### Panel de control — nota operacional

Tras cambios en panel/, el flujo correcto para que el autoarranque
use el código nuevo:
- `npm run build` — compila TypeScript
- `npm run package` — actualiza el binario en release/

Sin `npm run package`, el autoarranque sigue usando el binario anterior.

### Caché de web_search

Resultados cacheados en data/search_cache.db con TTL decidido por el modelo
(is_dynamic: true/false en el tool input). TTL corto (1h) para contenido
dinámico, TTL largo (24h) para estable. Ver commit feat(tools): caché SQLite
para web_search.

---

## Deuda técnica documentada

### Fallbacks duplicados en código Python (B3, B8)

`turn_context.py` y `persona_engine.py` tienen valores numéricos de fallback
en `.get("key", valor)` que replican los defaults de `config/default_config.yaml`.

Riesgo: si se cambia un default en el YAML sin actualizar el código, el fallback
en Python queda desactualizado silenciosamente. Solo afecta si falta la clave
en el YAML (no ocurre en producción con la config completa).

Solución pendiente: validar presencia de claves al cargar config y lanzar error
explícito si falta alguna clave requerida. Prioridad: baja.

### Literales de comportamiento en persona_engine.py (A3–A6)

`CRITICAL_KEYWORDS`, `order_override_instruction`, `refusal_instruction` y las
directivas de `_build_style_directives` son strings de comportamiento del modelo
embebidos en Python. Cambiarlos requiere editar código + restart.

Solución pendiente: extraer a `config/persona.yaml` y/o al template
`prompts/persona_system.md`. Pendiente de sesión de refactorización dedicada.

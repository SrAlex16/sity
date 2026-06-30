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

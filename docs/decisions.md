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

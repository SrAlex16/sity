# Flujo de desarrollo

Última actualización: 2026-07-30.

## Entornos

**PC / Windows (WSL):**
- Training LoRA con Unsloth + RTX 3060 Ti
- Hugging Face, scripts de training
- Edición desde IDE

**Raspberry Pi 4 (producción):**
- Backend/runtime real de Sity
- Panel de control (Electron, autoarranque)
- Home Assistant (Docker)
- Cámara, micrófono, pantalla RasPad 3
- No usar para entrenar modelos

## Flujo de trabajo habitual

1. Desarrollo con Claude Code directamente en la Pi (SSH)
2. Tests: python -m pytest --tb=short -q tests/
3. Commit + push desde la Pi
4. CI en GitHub Actions verifica automáticamente

```bash
cd ~/projects/sity
python -m pytest --tb=short -q tests/
git add -A
git commit -m "mensaje"
git push
```

## Servicios — comandos útiles

```bash
# Estado
sudo systemctl status sity-backend caddy cloudflared
docker inspect --format="{{.State.Running}}" homeassistant

# Reiniciar
sudo systemctl restart sity-backend
sudo systemctl reload caddy

# Logs
sudo journalctl -u sity-backend -n 50 --no-pager
cat ~/projects/sity/data/logs/app-$(date -u +%Y-%m-%d).jsonl | tail -20
```

## Panel de control

Tras cambios en panel/:

```bash
cd panel && npm run build && npm run package
```

El binario en release/linux-arm64-unpacked/ se actualiza.
El autoarranque (/etc/xdg/autostart/) apunta a ese binario.

## Deploy (frontend + backend)

```bash
cd ~/projects/sity && ./deploy.sh
```

El script detecta automáticamente qué ha cambiado y hace lo mínimo necesario:

| Condición | Acción |
|---|---|
| Algún archivo en `mobile/src/` o `mobile/public/` es más nuevo que el bundle en `dist/` | `npm run build` en `mobile/` |
| Ningún cambio de frontend desde el último build | Omite el build |
| Siempre | `sudo systemctl restart sity-backend` |

Caddy **no necesita reload** tras cambios de frontend: sirve los archivos estáticos
directamente de `mobile/dist/` desde disco. En cuanto el build actualiza los ficheros,
se sirven en la siguiente petición. Solo hace falta `sudo systemctl reload caddy` si
cambia el propio `Caddyfile`.

### ⚠️ Checklist obligatorio al añadir un router nuevo con prefix propio

Este bug ha aparecido tres veces (auth, events, shared+notifications). La raíz: Caddy
actúa como proxy selectivo — solo reenvía al backend los paths que tiene listados
explícitamente. El `handle` final sirve siempre el `index.html` de la SPA, por lo que
cualquier ruta no declarada en Caddy llega al frontend como 404 silencioso en vez de
llegar al backend.

**Regla:** si añades un router FastAPI cuyo prefix **no** está anidado bajo uno ya
existente (ej. `/chat/*`, `/auth/*`), debes añadir su propia línea en el Caddyfile
antes de hacer el deploy.

```bash
# 1. Editar el Caddyfile real en la Pi:
sudo nano /etc/caddy/Caddyfile
# Añadir, junto a las demás líneas handle:
#   handle /mi-nuevo-prefix/* { reverse_proxy localhost:8000 }

# 2. Actualizar el ejemplo en el repo (deploy/caddy/Caddyfile.example) — mismo cambio.

# 3. Recargar Caddy sin downtime:
sudo systemctl reload caddy

# 4. Verificar que el path llega al backend y no a la SPA:
curl -I https://sity.aletm.com/mi-nuevo-prefix/algo
# → debe devolver un código real del backend (200, 404 FastAPI, 401…),
#   NO el 200 del index.html con Content-Type: text/html
```

Prefixes actualmente declarados en el Caddyfile (actualizar esta lista con cada nuevo router):

| Prefix | Router | Notas |
|--------|--------|-------|
| `/chat/stream/*` | `routes_chat.py` | SSE — flush_interval -1 |
| `/events/*` | `realtime_events` | SSE — flush_interval -1 |
| `/chat/*` | `routes_chat.py` | |
| `/audio/*` | `routes_audio.py` | |
| `/auth/*` | `routes_auth.py` + OAuth | Cubre también `/auth/integrations/*` |
| `/settings/*` | `routes_settings.py` | |
| `/debug/*` | `routes_debug.py` | |
| `/notifications/*` | `routes_notifications.py` | Web Push (VAPID, subscribe) |
| `/health` | `main.py` | |

> **Nota sobre `/shared/*`:** el path de página `/shared/{id}` cae intencionalmente en el `handle` genérico de la SPA (`try_files → index.html`). React detecta la URL y renderiza `SharedConversationView`, que llama a la API bajo `/chat/shared/{id}` (cubierto por `/chat/*`). NO añadir `/shared/*` al reverse_proxy.

**El servicio `sity-frontend` no tiene relación con producción** — es un dev server
de Vite en el puerto 5173. `sudo systemctl restart sity-frontend` no reconstruye ni
redespliega nada.

**Verificar que un build llegó al navegador:**
1. El script imprime el nombre del nuevo bundle (`index-XXXXXXXX.js`). Confirmar que cambió.
2. Recarga dura en el navegador (cerrar pestaña y volver a abrir, o Shift+F5).
3. DevTools → Sources → confirmar que el hash del bundle cargado coincide.
4. Si no coincide: DevTools → Application → Service Workers — puede haber
   una versión en "waiting to activate". Pulsar "skipWaiting" y recargar.
   (Ver docs/turn-cancellation.md §7a para el detalle completo.)

**PWA instalada en Android (WebAPK) — contexto separado:**

Cuando Sity está instalada como PWA (icono en el home screen), Android la ejecuta
en un WebAPK — un contexto completamente separado del Chrome del navegador. Las
APIs `clients.claim()` y `skipWaiting()` del Service Worker activan la nueva versión
en el contexto donde el SW está registrado, pero el WebAPK tiene su propia instancia.
Borrar "cookies y datos" en Chrome no afecta al WebAPK.

Para resetear la PWA instalada en Android:
> Ajustes del sistema → Aplicaciones → [nombre de la app Sity] → Almacenamiento
> → **Borrar caché** + **Borrar datos**

O desinstalar la PWA (mantener pulsado el icono → Desinstalar) y volver a añadirla.

El síntoma de esta situación: DevTools del navegador muestra el bundle nuevo
(`index-CmgWdExL.js`) y el bundle SÍ contiene los cambios, pero la pantalla
(del WebAPK, no de la pestaña del navegador) sigue mostrando la versión antigua.

## Qué no subir a git

```
.env
data/
datasets/
work/
captures/
backend/.venv/
*/node_modules/
training/output/
reports/
```

## Observabilidad y logs

### Archivos de log

Los logs se escriben en `data/logs/` como `.jsonl` (una línea JSON por evento):

- `app-YYYY-MM-DD.jsonl` — eventos de aplicación (INFO, WARN, ERROR)
- `audit-YYYY-MM-DD.jsonl` — eventos de auditoría (cambios de personalidad, etc.)

### Eventos instrumentados (Fase 1)

| `module`    | `event`                        | Cuándo                                            |
|-------------|--------------------------------|---------------------------------------------------|
| `backend`   | `backend_started`              | Arranque de FastAPI (incluye `git_commit`)        |
| `backend`   | `backend_shutdown`             | Apagado limpio de FastAPI                         |
| `tools`     | `tool_call_started`            | Antes de ejecutar cualquier tool (payload: `session_id`) |
| `tools`     | `tool_call_finished`           | Después de ejecutar cualquier tool (ok/WARN, `session_id`) |
| `tools`     | `tool_chain_continued`         | Bucle multi-turno avanza a ronda siguiente        |
| `spotify`   | `spotify_api_call`             | Cada llamada HTTP real a `api.spotify.com`        |
| `google`    | `google_api_call`              | Cada llamada a la Google API (gmail/calendar/drive) |
| `ha`        | `ha_api_call`                  | Cada llamada HTTP a Home Assistant                |
| `realtime_events` | `sse_subscriber_connected` | Cliente SSE conectado                          |
| `realtime_events` | `sse_subscriber_disconnected` | Cliente SSE desconectado                    |
| `realtime_events` | `session_queues_gc`        | GC de colas SSE inactivas                        |
| `realtime_events` | `log_files_purged`         | Purga de logs antiguos                           |

### Eventos instrumentados (Fase 2 — senses)

| `module`  | `event`                    | Cuándo                                                    |
|-----------|----------------------------|-----------------------------------------------------------|
| `senses`  | `audio_devices_listed`     | Al ejecutar `list_audio_devices` (sources count + errores) |
| `senses`  | `audio_capture_started`    | Antes de lanzar `arecord` (device, duration_seconds)      |
| `senses`  | `audio_capture_finished`   | Al terminar la grabación (ok/WARN, file_size o motivo)    |
| `senses`  | `camera_devices_listed`    | Al ejecutar `list_camera_devices` (device count)          |
| `senses`  | `camera_capture_started`   | Antes de lanzar `fswebcam` (device, resolution)           |
| `senses`  | `camera_capture_finished`  | Al terminar la captura (ok/WARN, file_size o motivo)      |
| `senses`  | `senses_retention_cleanup` | Al ejecutar `clean_old_captures` (WARN si hay errores)    |

Casos que producen WARN en `audio_capture_finished`: `loopback_device_refused`,
`timeout`, `arecord_not_found`, `cancelled`, o returncode ≠ 0. Ídem para
`camera_capture_finished`: `timeout`, `fswebcam_not_found`, `cancelled`, returncode ≠ 0.

### Eventos instrumentados (Fase 2 — audio TTS/STT)

| `module` | `event`                     | Cuándo                                                        |
|----------|-----------------------------|---------------------------------------------------------------|
| `audio`  | `tts_synthesis_started`     | Antes de invocar Piper (payload: `text_len`)                  |
| `audio`  | `tts_synthesis_finished`    | Al terminar síntesis (ok/WARN, `audio_size_bytes`+`duration_ms` o motivo) |
| `audio`  | `stt_model_loading`         | Antes de cargar WhisperModel (primera vez o cambio de config) |
| `audio`  | `stt_model_loaded`          | Al terminar la carga (ok/WARN con motivo de fallo)            |
| `audio`  | `stt_transcription_started` | Antes de transcribir (payload: `audio_size_bytes`)            |
| `audio`  | `stt_transcription_finished`| Al terminar transcripción (ok/WARN, `transcript_len`+`duration_ms` o motivo) |

**Privacidad**: estos logs contienen únicamente metadatos (longitudes, tamaños,
duraciones, códigos de error). Ni el texto sintetizado ni la transcripción real
se escriben en ningún log — solo `text_len` y `transcript_len`.

### Eventos instrumentados (Fase 2 — memory)

| `module`  | `event`                    | Cuándo                                                              |
|-----------|----------------------------|---------------------------------------------------------------------|
| `memory`  | `db_initialized`           | Al terminar `init_db()` (ok/WARN con motivo si falla el arranque)  |
| `memory`  | `db_migration_applied`     | Si `_migrate_chatmessage` añadió columnas nuevas (lista en payload) |
| `memory`  | `memory_search_started`    | Antes de buscar en historial (payload: `query`, `limit`)            |
| `memory`  | `memory_search_finished`   | Al terminar búsqueda (`count`, `fts_used`; **WARN si count=0**)    |
| `memory`  | `memory_window_read`       | Al leer ventana de contexto alrededor de un anchor                  |
| `memory`  | `memory_fts_rebuild`       | Al reconstruir el índice FTS5 (ok/WARN)                             |
| `memory`  | `memory_recall_started`    | Antes del ciclo iterativo de recall (`query`, `trace_id`)           |
| `memory`  | `memory_recall_finished`   | Al terminar recall (`status`, `confidence`, `fragments`, `windows`) |

`memory_search_finished` emite **WARN** cuando `count=0` — esta es la condición
de riesgo de alucinación: el modelo recibió cero fragmentos reales pero puede
responder de todas formas. Ver la `query` en el payload para diagnosticar si
el caso se repite.

**Privacidad**: la query de búsqueda se loguea (es lo que el usuario pidió buscar,
no historial de terceros). El contenido de los fragmentos recuperados **no se
loguea** — solo cantidades y metadatos.

### Eventos instrumentados (Fase 2 — frontend JS)

| `module`    | `event`           | Cuándo                                                           |
|-------------|-------------------|------------------------------------------------------------------|
| `frontend`  | `frontend_error`  | Error JS no manejado o promesa rechazada sin catch en la PWA     |

Capturado vía `window.addEventListener('error')` y `unhandledrejection` en
`mobile/src/main.tsx`. El endpoint `POST /debug/frontend-error` acepta el
mensaje (truncado a 500 chars), stack trace (truncado a 2000 chars) y URL.
Rate limit: 20 errores/minuto en memoria (se resetea al reiniciar el backend).

**Alcance**: solo errores JS no capturados. No es un sistema de analytics ni de
logging de comportamiento normal — solo fallos inesperados que de otra forma
serían invisibles.

### Eventos instrumentados (Fase 2 — auth/sesión)

| `module` | `event`                | Cuándo                                                         |
|----------|------------------------|----------------------------------------------------------------|
| `auth`   | `guest_session_created`| Primera visita de un Guest: se genera `sity_guest_session` UUID nuevo |

Solo se emite en la **primera** petición de una sesión Guest (cookie ausente).
Las resoluciones posteriores (cookie ya existente) no loguean nada — serían
ruido excesivo. El `session_id` del Guest (`guest:uuid`) viaja en los eventos
`tool_call_started/finished` y `ai_call_started` de cada turno.

Los eventos `tool_call_started/finished` cubren automáticamente todas las tools
actuales y futuras — no hay que tocar los handlers individuales. Los inputs
sensibles (token, secret, password, authorization, api_key) se redactan como
`"***"` antes de loguearse.

### Filtrar logs desde la terminal

```bash
# Todos los tool_call de hoy
cat data/logs/app-$(date -u +%Y-%m-%d).jsonl | python3 -c "
import sys, json
for l in sys.stdin:
    d = json.loads(l)
    if d.get('event') in ('tool_call_started','tool_call_finished'):
        print(json.dumps(d))
"

# Solo llamadas Spotify de un trace concreto
cat data/logs/app-$(date -u +%Y-%m-%d).jsonl | grep 'spotify_api_call' | grep 'trc_XXXX'

# Todos los WARN (errores de API)
cat data/logs/app-$(date -u +%Y-%m-%d).jsonl | python3 -c "
import sys, json
for l in sys.stdin:
    d = json.loads(l)
    if d.get('level') == 'WARN':
        print(json.dumps(d))
"
```

### Retención automática de logs

Los `.jsonl` con más de **14 días** se borran automáticamente. La purga corre
cada 10 minutos desde el `_gc_loop` en `realtime_events.py` (mismo loop que
limpia las colas SSE inactivas). Para cambiar el periodo:

```python
# backend/app/core/realtime_events.py, en _gc_loop():
deleted = purge_old_logs(retention_days=30)  # cambiar aquí
```

### Logs de servicios systemd (journalctl)

Los eventos de arranque/parada/fallo de los servicios los gestiona systemd.
Comandos de referencia:

```bash
# Últimas 50 líneas de cada servicio
sudo journalctl -u sity-backend -n 50 --no-pager
sudo journalctl -u caddy -n 50 --no-pager
sudo journalctl -u cloudflared -n 50 --no-pager

# Seguir logs en tiempo real
sudo journalctl -u sity-backend -f

# Eventos de la última hora de todos los servicios Sity
sudo journalctl -u sity-backend -u caddy -u cloudflared --since "1 hour ago"

# Ver si un servicio falló recientemente
sudo journalctl -u sity-backend -p err --since today
```

Para ver el `backend_started`/`backend_shutdown` registrados por la propia app:

```bash
cat data/logs/app-$(date -u +%Y-%m-%d).jsonl | grep '"event":"backend_'
```

---

## Timestamps: SQLite devuelve datetimes naive

SQLite no almacena información de zona horaria. Cuando SQLModel/SQLAlchemy lee
un `datetime` de la BD, el objeto Python resultante tiene `tzinfo=None`
(datetime "naive"). Si ese datetime llega al frontend sin normalización, la
serialización JSON omite el sufijo de zona (`"2026-07-10T22:42:00"` en vez de
`"2026-07-10T22:42:00+00:00"`), y JavaScript lo interpreta como hora LOCAL del
navegador en vez de UTC — lo que produce timestamps incorrectos tras un F5 o
cualquier carga de historial.

Este patrón apareció dos veces el mismo día (2026-07-11):
- `task_context.py` → parcheado con `if updated_at.tzinfo is None: updated_at = updated_at.replace(tzinfo=timezone.utc)`
- `ChatMessageItem.created_at` → parcheado con `@field_serializer` en `schemas.py` (commit `1343ff8`)

**Regla para cualquier endpoint nuevo que exponga datetimes de la BD:**

Normalizar antes de serializar. En Pydantic v2, la forma más limpia es un
`@field_serializer` en el schema de respuesta:

```python
from datetime import datetime, timezone
from pydantic import field_serializer

class MiSchema(BaseModel):
    created_at: Optional[datetime] = None

    @field_serializer("created_at")
    def _serialize_created_at(self, v: Optional[datetime]) -> Optional[str]:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
```

Esto garantiza que el JSON lleve `+00:00` y que `new Date(ts)` en el
navegador siempre interprete correctamente la cadena como UTC.

---

## Regla de seguridad operativa

Si hay dos opciones y una toca runtime real, elegir primero
la opción local/mock/manual. No hacer cambios destructivos
sin confirmación clara.

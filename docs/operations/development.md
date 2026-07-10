# Flujo de desarrollo

Última actualización: 2026-07-08.

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

## Frontend PWA (mobile/)

```bash
cd mobile && npm run build
sudo systemctl reload caddy
```

**⚠️ El build es obligatorio tras cualquier cambio en `mobile/src/` o
`mobile/public/`.** Caddy sirve directamente el contenido de
`mobile/dist/` — Vite genera nombres de archivo con hash de contenido,
así que sin rebuild el archivo en disco no cambia y ningún cambio de
código llega al navegador, Service Worker o no.

El servicio systemd `sity-frontend` es **solo el servidor de desarrollo
de Vite en el puerto 5173** — no tiene ninguna relación con lo que
Caddy sirve en producción. Reiniciarlo no reconstruye ni redespliega nada.

**Verificar que un build llegó al navegador:**
1. Comprobar que el hash de `dist/assets/index-*.js` cambió tras el build.
2. `Shift+F5` en el navegador.
3. DevTools → Sources → confirmar que el hash del bundle cargado coincide
   con el recién generado.
4. Si no coincide: DevTools → Application → Service Workers — puede haber
   una versión en "waiting to activate". Pulsar "skipWaiting" y recargar.
   (Ver docs/turn-cancellation.md §7a para el detalle completo.)

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
| `tools`     | `tool_call_started`            | Antes de ejecutar cualquier tool                  |
| `tools`     | `tool_call_finished`           | Después de ejecutar cualquier tool (ok/WARN)      |
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

## Regla de seguridad operativa

Si hay dos opciones y una toca runtime real, elegir primero
la opción local/mock/manual. No hacer cambios destructivos
sin confirmación clara.

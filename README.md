# Sity

Sity es una IA doméstica de ocio pensada para ejecutarse en una Raspberry Pi/RasPad y vivir en un entorno local controlado.

El objetivo del proyecto no es solo tener un chatbot, sino una asistente con personalidad configurable, memoria conversacional, acceso controlado al sistema, integración progresiva con hardware y capacidad de ejecutar acciones reales con confirmación explícita cuando corresponde.

Actualmente Sity usa Claude como proveedor principal de IA, con una arquitectura preparada para añadir fallback a otros modelos y más capacidades locales en el futuro.

---

## Estado actual

### Funciona

- Backend FastAPI.
- Frontend web con chat.
- Integración con Claude API.
- Personalidad dinámica configurable.
- Sliders de personalidad.
- Modificación de personalidad desde chat mediante tools.
- Historial persistente de conversación.
- Uso de SQLite como base local.
- Logs y trazas.
- Debug tools.
- Lectura de estado del sistema.
- Lectura de estado Git.
- Acciones Git con confirmación.
- Acciones systemd con confirmación.
- Gestión dinámica de allowlist de servicios.
- Servicios systemd versionados en el repo.
- Servicio de prueba `sity-test`.
- Presupuesto diario local de tokens y avisos de uso.
- Prompt/tool routing corregido para no usar debug en conversación normal.
- Reconocimiento de personalidad actual desde el estado inyectado por backend.
- Cámara USB detectada y funcionando.
- Micrófono USB de webcam detectado y funcionando.
- Captura de cámara desde backend y frontend.
- Grabación corta de audio desde backend y frontend.
- Preview de imagen en el chat.
- Reproductor de audio en el chat.
- Descarga de capturas desde navegador.
- Eventos en tiempo real mediante SSE.
- Estado visible mientras Sity usa herramientas.
- Cancelación de grabación de audio.
- Cancelación de captura de cámara.
- Micro-reacciones con personalidad para eventos pequeños.
- Limpieza de capturas antiguas.
- Workaround de audio RasPad 3 documentado.
- Audio HDMI funcionando mediante pipeline ALSA Loopback → IEC958.
- Vivaldi y VLC funcionando con el pipeline custom de audio.

---

## Arquitectura general

```text
frontend/
  Interfaz web de chat, sliders, previews y controles.

backend/
  API FastAPI.
  Núcleo de conversación.
  Gateway IA.
  Providers.
  Tools.
  Confirmaciones.
  Acceso controlado a sistema/Git.
  Sensores.
  Eventos en tiempo real.
  Micro-reacciones.

config/
  Configuración local versionada.

data/
  SQLite, logs y datos runtime.
  Ignorado por git.

deploy/
  Plantillas systemd, sudoers y documentación de despliegue.

scripts/
  Scripts de desarrollo, instalación, estado y limpieza.

services/
  Servicios auxiliares del proyecto.

captures/
  Capturas temporales de cámara/audio.
  Ignorado por git salvo `.gitkeep`.
```

---

## Backend

El backend expone, entre otros:

```text
GET  /health
POST /chat/message
GET  /chat/current
GET  /settings/personality
POST /settings/personality/adjust
GET  /debug/events/recent
GET  /debug/last-trace
GET  /captures/camera/{filename}
GET  /captures/audio/{filename}
GET  /events/chat/{client_turn_id}
POST /events/chat/{client_turn_id}/cancel
```

Endpoint principal:

```text
POST /chat/message
```

Ejemplo:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
```

Health check:

```bash
curl http://localhost:8000/health
```

---

## Frontend

El frontend permite:

- Chatear con Sity.
- Ver respuestas en formato texto.
- Ver proveedor/modelo/trace.
- Ver uso de tokens.
- Ajustar personalidad con sliders.
- Mantener conversación tras refrescar la página.
- Mostrar historial persistente desde backend.
- Consultar paneles de debug.
- Mostrar imágenes capturadas.
- Reproducir audios grabados.
- Descargar archivos generados.
- Mostrar estado mientras Sity trabaja.
- Cancelar operaciones de cámara/audio cuando sea posible.

El frontend usa:

```text
VITE_SITY_API_BASE
```

Ejemplo:

```env
VITE_SITY_API_BASE=http://192.168.1.133:8000
```

---

## IA / Claude

Actualmente Sity usa Claude como proveedor principal.

Modelo usado durante el desarrollo:

```text
claude-haiku-4-5-20251001
```

Claude se usa para:

- Conversación.
- Interpretación flexible de intención.
- Decidir cuándo usar tools.
- Transformar peticiones naturales en acciones estructuradas.
- Responder con personalidad actual.
- Generar micro-reacciones breves para eventos pequeños.

El backend se encarga de:

- Seguridad.
- Confirmaciones.
- Ejecución de acciones.
- Persistencia.
- Logs.
- Control de costes.
- Políticas de riesgo.
- Eventos en tiempo real.
- Cancelación de procesos.
- Validación de rutas y dispositivos.

---

## Personalidad

Sity tiene personalidad parametrizable. Los parámetros actuales incluyen:

```text
sarcasm_level
rudeness_level
warmth_level
honesty_level
initiative_level
dry_humor_level
tsundere_level
contrarian_level
patience_level
refusal_chance
helpfulness_level
verbosity_level
melancholy_level
```

Estos parámetros pueden cambiarse:

1. Desde el frontend, con sliders.
2. Desde API.
3. Desde chat, mediante tool use de Claude.

Ejemplos:

```text
sube la melancolía al 90%
pon todos los parámetros al 50%
baja el sarcasmo al 30%
hazte menos borde pero mantén algo de sarcasmo
```

La personalidad actual inyectada por el backend es la fuente de verdad.

Si el usuario cambia sliders desde el frontend, Sity debe usar los valores actuales recibidos en el prompt. No necesita una confirmación de tool para reconocer cambios hechos desde la UI.

Solo debe hablar de "cambio aplicado por tool" cuando el backend indique explícitamente que una tool de personalidad ha ejecutado un cambio.

---

## Micro-reacciones

Sity puede generar respuestas breves para eventos pequeños sin pasar por todo el flujo normal de chat.

Ejemplos:

```text
audio_recording_cancelled
camera_capture_cancelled
audio_recording_finished
camera_capture_finished
```

Objetivo:

```text
- Respuestas naturales.
- Una frase breve.
- Sin tools.
- Sin historial largo.
- Pocos tokens.
- Fallback local si falla Claude.
```

Ejemplo:

```text
Usuario cancela grabación
Sity: Vale, cancelado. He parado la grabación antes de que esto se volviera documental.
```

Las micro-reacciones usan:

```text
- personalidad compacta
- max_tokens bajo
- sin tools
- sin contexto conversacional largo
```

Si Claude falla, se usa respuesta local:

```text
Cancelado. He parado la grabación de audio.
```

---

## Memoria conversacional

Sity mantiene historial persistente de conversación en backend.

Esto permite:

- Recargar la UI sin perder conversación.
- Usar contexto anterior.
- Evitar depender de memoria temporal del frontend.
- Consultar `/chat/current` para reconstruir la conversación.

La memoria de frontend se ha reducido para evitar contradicciones. El backend es la fuente principal de verdad.

Sity no debe decir que “pierde memoria al recargar la página”. La conversación se conserva en SQLite. Lo correcto es distinguir entre:

```text
- memoria/historial existente en backend
- contexto concreto que el modelo recibe en un turno
```

Si no ve algo en el contexto actual, debe decir:

```text
No lo veo en el contexto que recibí ahora.
```

No:

```text
No tengo memoria persistente.
```

---

## Tools

Sity usa tools para acciones estructuradas.

Tipos actuales:

```text
Personality tools
Debug tools
System read tools
Git read tools
Git action tools
System action tools
System config tools
Sense tools
Capture retention tools
No-action / respuesta normal
Micro-reactions
```

Las tools críticas no se ejecutan directamente. Se crea una acción pendiente y se exige confirmación.

Las herramientas de debug solo deben usarse cuando el usuario pide explícitamente:

```text
logs
trazas
errores
eventos
tools ejecutadas
diagnóstico técnico
auditoría
```

No deben usarse para conversación normal, frases ambiguas o seguimiento contextual.

---

## Routing de intención

La interpretación de lenguaje natural debe recaer en Sity/Claude, no en literales hardcodeados en backend.

Principio:

```text
Claude/Sity interpreta intención.
Backend valida permisos, riesgo y ejecución.
Backend no decide por frases sueltas como “foto”, “front”, “déjalo” o “porfi”.
```

El backend conserva lógica determinista para:

```text
- confirmaciones exactas
- validación de riesgo
- ejecución de tools
- deduplicación de acciones
- allowlists
- control de permisos
- cancelación técnica
```

No debe intentar interpretar lenguaje natural de forma extensa con regex o literales, porque eso crea falsos positivos.

---

## Confirmation Manager

Las acciones que modifican el sistema o Git pasan por un `Confirmation Manager`.

Flujo:

```text
1. Usuario pide una acción.
2. Claude interpreta intención y elige tool.
3. Backend evalúa riesgo.
4. Si requiere confirmación, backend crea pending_action.
5. Sity muestra qué va a hacer.
6. Usuario confirma.
7. Backend ejecuta localmente.
```

Ejemplo:

```text
Usuario:
reinicia el frontend

Sity:
Acción pendiente creada: Reiniciar servicio sity-frontend

Para ejecutarla, confirma con:
confirmo ejecutar act_xxxxxxxx

También puedes decir:
sí, reinicia frontend
```

Confirmaciones soportadas:

```text
confirmo ejecutar act_xxxxxxxx
sí, hazlo
dale
sí, reinicia frontend
sí, reinicia sity-test
sí, añade sity-test
```

Reglas importantes:

- Si hay varias acciones pendientes, una confirmación genérica no debe adivinar.
- Si una acción ya fue ejecutada, no se repite.
- Si un ID no existe o está expirado, se responde localmente.
- Las confirmaciones viejas no caen en Claude.
- Repetir una orden no cuenta como confirmación.
- Si ya existe una acción pendiente equivalente, se reutiliza.
- Las acciones duplicadas se detectan.
- La confirmación contextual exige intención explícita.

---

## Política de riesgo

El riesgo debe depender de la herramienta/acción, no de cómo el usuario lo expresa.

Ejemplo de política conceptual:

```text
read               → ejecutar directo
sensitive_direct   → ejecutar directo si es puntual y limitado
safe_confirm       → pending action
critical_confirm   → pending action
blocked            → rechazar
```

Ejemplos:

```text
list_camera_devices          → read
list_audio_devices           → read
capture_camera_snapshot      → sensitive_direct
record_audio_sample          → sensitive_direct
clean_old_captures           → safe/directo conservador
git_push                     → critical_confirm
git_pull                     → critical_confirm
system_restart_service       → safe_confirm
system_stop_service          → safe_confirm
system_config_update         → critical_confirm
```

---

## Git

Sity puede leer estado Git:

```text
status
log
branches
remotes
diff
```

Y puede proponer acciones Git con confirmación:

```text
fetch
pull --ff-only
push
crear rama
cambiar de rama
commit
```

Ejemplos:

```text
cómo está el repo sity?
qué últimos commits tiene el repo sity?
haz pull del repo sity
haz fetch del repo sity
crea una rama feature/test
cambia a la rama main
```

Las acciones modificadoras requieren confirmación.

---

## System Access

Sity puede leer información del sistema:

```text
estado básico
CPU/RAM
disco
procesos
servicios permitidos
directorios permitidos
```

También puede controlar servicios systemd permitidos:

```text
start
stop
restart
```

Actualmente se usan:

```text
sity-backend
sity-frontend
sity-test
```

---

## Allowlist dinámica de servicios

Sity puede modificar la allowlist de servicios con confirmación.

Ejemplos:

```text
qué servicios puedes controlar?
añade sity-test a servicios permitidos
quita sity-test de servicios permitidos
```

Esto modifica:

```text
config/system_access.yaml
```

Importante:

- Añadir un servicio a la allowlist no crea el servicio systemd.
- Quitar un servicio de la allowlist no borra el servicio systemd.
- Solo cambia qué servicios puede consultar/controlar Sity.
- La modificación de allowlist requiere confirmación.

---

## Servicios systemd

El proyecto incluye plantillas versionadas en:

```text
deploy/systemd/
```

Servicios actuales:

```text
sity-backend.service
sity-frontend.service
sity-test.service
```

### sity-backend

Servicio FastAPI/Uvicorn.

```text
http://localhost:8000
```

### sity-frontend

Servicio Vite dev server.

```text
http://localhost:5173
```

En red local:

```text
http://192.168.1.133:5173
```

### sity-test

Servicio HTTP mínimo para pruebas.

```text
http://localhost:8099
```

Devuelve:

```text
sity service test
```

Está pensado para probar control de servicios sin levantar algo pesado como Minecraft.

---

## Sudoers

La allowlist sudoers está versionada en:

```text
deploy/sudoers/sity
```

Permite a `alex` ejecutar sin password únicamente comandos concretos sobre servicios permitidos.

No se concede sudo general.

---

## Instalación de servicios

Script:

```bash
./scripts/install_systemd_services.sh
```

Hace:

```text
1. Copia servicios a /etc/systemd/system/
2. Copia sudoers a /etc/sudoers.d/sity
3. Valida sudoers con visudo
4. Recarga systemd
5. Habilita servicios
```

Después se pueden arrancar manualmente:

```bash
sudo systemctl start sity-backend
sudo systemctl start sity-frontend
sudo systemctl start sity-test
```

---

## Estado rápido de servicios

Script:

```bash
./scripts/status_services.sh
```

Muestra:

```text
is-enabled
is-active
health backend
respuesta de sity-test
```

---

## Cámara y micrófono

Hardware detectado:

```text
Cámara:
Full HD webcam
/dev/video0
/dev/video1

Micrófono:
Full HD webcam
plughw:CARD=webcam,DEV=0
PipeWire source Full HD webcam Mono
```

La cámara funciona, pero necesita tiempo para autoexposición. Las capturas usan `fswebcam` con `--skip 20` o similar.

Ejemplo manual:

```bash
fswebcam -d /dev/video0 -r 1280x720 --no-banner --skip 20 captures/camera/test.jpg
```

El micro de la webcam graba correctamente.

Ejemplo manual:

```bash
arecord -D plughw:CARD=webcam,DEV=0 -d 5 -f cd captures/audio/test-webcam.wav
```

Importante:

- No usar `Loopback` como micrófono real.
- `Loopback` forma parte del pipeline de audio HDMI.
- Cámara y micrófono son sensores sensibles.
- Capturar foto puntual se permite cuando el usuario lo pide explícitamente.
- Grabar audio corto se permite cuando el usuario lo pide explícitamente.
- Captura continua/vigilancia no está implementada y debe bloquearse o requerir política fuerte.
- Listar dispositivos puede ser local/directo.

---

## Captura de cámara

Sity puede sacar fotos desde backend/frontend.

Flujo:

```text
Usuario pide una foto.
Claude interpreta intención y llama tool.
Backend ejecuta capture_camera_snapshot.
Frontend recibe artifact de imagen.
Frontend muestra preview y descarga.
```

La cámara usa:

```text
/dev/video0
fswebcam
--skip 20
```

La captura puede cancelarse desde el frontend. Para que la cancelación funcione de verdad, la ejecución usa proceso cancelable y registra la operación activa.

---

## Grabación de audio

Sity puede grabar muestras cortas de audio desde el micro real de la webcam.

Dispositivo:

```text
plughw:CARD=webcam,DEV=0
```

Flujo:

```text
Usuario pide grabar audio.
Claude interpreta intención y llama tool.
Backend ejecuta record_audio_sample.
Frontend muestra estado “Grabando audio…”.
Usuario puede cancelar.
Frontend recibe artifact de audio.
Frontend muestra reproductor y descarga.
```

La grabación puede cancelarse desde el frontend. Cancelar no se trata como error.

---

## Media artifacts

Las respuestas de chat pueden incluir artifacts:

```json
{
  "type": "image",
  "url": "/captures/camera/snapshot-123.jpg",
  "filename": "snapshot-123.jpg",
  "mime_type": "image/jpeg"
}
```

o:

```json
{
  "type": "audio",
  "url": "/captures/audio/audio-123.wav",
  "filename": "audio-123.wav",
  "mime_type": "audio/wav"
}
```

El frontend renderiza:

```text
image → preview + enlace de descarga
audio → reproductor + enlace de descarga
file  → enlace de descarga
```

Los archivos se sirven desde endpoints controlados:

```text
GET /captures/camera/{filename}
GET /captures/audio/{filename}
```

Validaciones:

```text
- sin rutas relativas
- sin /
- sin \
- solo extensiones permitidas
- solo dentro de captures/camera o captures/audio
```

---

## Eventos en tiempo real

Sity usa SSE para informar al frontend de acciones en curso.

Endpoint:

```text
GET /events/chat/{client_turn_id}
```

Eventos actuales:

```text
tool_started
tool_finished
cancelled
done
error
```

Ejemplo:

```json
{
  "type": "tool_started",
  "tool": "record_audio_sample",
  "label": "Grabando audio…",
  "can_cancel": true
}
```

El frontend usa estos eventos para:

```text
- mostrar “Grabando audio…”
- mostrar “Sacando foto…”
- activar botón Cancelar
- limpiar estado al terminar
```

El `client_turn_id` se genera en frontend y se manda en `/chat/message`.

Si `crypto.randomUUID()` no existe en el navegador, se usa fallback:

```text
turn_{timestamp}_{random}
```

---

## Cancelación

Sity soporta cancelación de operaciones activas mediante:

```text
POST /events/chat/{client_turn_id}/cancel
```

Actualmente se usa para:

```text
record_audio_sample
capture_camera_snapshot
```

La cancelación:

```text
- marca operación como cancelada
- termina el proceso si sigue vivo
- borra archivo parcial si corresponde
- publica evento cancelled
- genera micro-reacción
- no se trata como error
```

Resultado esperado:

```text
Usuario: graba 10 segundos de audio
UI: Grabando audio… [Cancelar]
Usuario pulsa Cancelar
Sity: Vale, cancelado. He parado la grabación.
```

---

## Retención de capturas

Sity puede consultar y limpiar capturas antiguas.

Directorios:

```text
captures/camera/
captures/audio/
```

Política por defecto:

```text
older_than_days: 7
max_files_per_type: 100
```

Tools:

```text
get_capture_storage_summary
clean_old_captures
```

Ejemplos:

```text
cuántas capturas tengo guardadas?
simula limpiar capturas antiguas
limpia capturas antiguas de más de 7 días
```

La limpieza solo borra archivos permitidos dentro de:

```text
captures/camera
captures/audio
```

No toca rutas externas.

También puede existir script manual:

```bash
./scripts/clean_captures.sh 7
```

---

## Audio RasPad 3

El RasPad 3 no expone correctamente HPD en HDMI. El driver `vc4-hdmi` no ofrece audio PCM normal y solo expone `IEC958_SUBFRAME_LE`.

Para resolverlo, el sistema usa un pipeline custom:

```text
Vivaldi / VLC / ALSA
  -> snd-aloop Loopback
  -> arecord hw:Loopback,1,0
  -> pcm2iec958.py
  -> aplay hw:vc4hdmi0,0 IEC958_SUBFRAME_LE
  -> HDMI
```

Componentes documentados en:

```text
deploy/audio/
```

Puntos importantes:

- `snd-aloop` crea una tarjeta virtual Loopback.
- `/etc/asound.conf` redirige ALSA `default` a `hw:Loopback,0`.
- `pcm2iec958.py` convierte PCM S16LE a `IEC958_SUBFRAME_LE`.
- `hdmi-audio-forward.service` mantiene el pipeline activo.
- WirePlumber debe ignorar Loopback para evitar feedback con el micrófono.
- Vivaldi 32-bit usa ALSA directo y necesita que `default` apunte al Loopback.
- VLC necesita `aout=alsa` y `alsa-audio-device=hw:Loopback,0`.

No tocar a ciegas:

```text
/etc/asound.conf
/etc/modules-load.d/snd-aloop.conf
/home/alex/.local/bin/pcm2iec958.py
~/.config/systemd/user/hdmi-audio-forward.service
~/.config/wireplumber/main.lua.d/51-default-sink.lua
~/.config/vlc/vlcrc
```

---

## Configuración principal

Archivo:

```text
config/system_access.yaml
```

Define:

```text
system_access.read.allowed_paths
system_access.read.allowed_services
system_access.safe_actions.allowed_services
git_access.read.allowed_repositories
```

---

## Variables de entorno

Archivo local no versionado:

```text
.env
```

Incluye claves como:

```text
ANTHROPIC_API_KEY
OPENAI_API_KEY
PC_AGENT_TOKEN
SITY_ENV
```

No debe subirse a Git.

Frontend local:

```text
frontend/.env.local
```

Ejemplo:

```env
VITE_SITY_API_BASE=http://192.168.1.133:8000
```

---

## Logs y datos

Runtime local:

```text
data/
```

Incluye:

```text
app.db
logs
audit logs
```

Debe permanecer fuera de Git.

Logs systemd:

```bash
journalctl -u sity-backend -n 80 --no-pager
journalctl -u sity-frontend -n 80 --no-pager
journalctl -u sity-test -n 80 --no-pager
```

---

## Capturas temporales

Directorio:

```text
captures/
```

Usado para capturas de cámara/audio.

Debe estar ignorado por git salvo `.gitkeep`.

`.gitignore` debe incluir:

```gitignore
captures/camera/*
captures/audio/*
!captures/.gitkeep
```

---

## Seguridad

Principios actuales:

```text
1. Lectura directa solo en zonas permitidas.
2. Acciones modificadoras requieren confirmación según riesgo.
3. Servicios controlables limitados por allowlist.
4. Sudoers limitado a comandos concretos.
5. Sin shell arbitraria.
6. Sin sudo general.
7. Las acciones viejas no se reejecutan.
8. Las acciones duplicadas se detectan.
9. Confirmación contextual solo con intención explícita.
10. Las herramientas de debug no se usan para conversación normal.
11. Cámara y micro no se activan salvo petición explícita.
12. Audio Loopback se trata como dispositivo virtual, no como micro real.
13. Capturas se sirven desde endpoints validados.
14. Cancelar una acción no se trata como error.
```

Regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar según política de riesgo.
```

Para acciones críticas:

```text
Primero plan.
Luego confirmación.
Después ejecución.
```

Para capacidades externas:

```text
Primero permiso.
Luego consulta.
Después respuesta con trazabilidad.
```

---

## Desarrollo

### Backend

Si el backend está corriendo como servicio, lanzarlo manualmente puede dar:

```text
ERROR: [Errno 98] Address already in use
```

Eso es normal: el puerto `8000` ya está ocupado por `sity-backend.service`.

Reiniciar backend:

```bash
sudo systemctl restart sity-backend
```

Comprobar salud:

```bash
curl http://localhost:8000/health
```

### Frontend

Reiniciar frontend:

```bash
sudo systemctl restart sity-frontend
```

Abrir:

```text
http://192.168.1.133:5173
```

---

## Comandos útiles

### Backend

```bash
sudo systemctl restart sity-backend
curl http://localhost:8000/health
```

### Frontend

```bash
sudo systemctl restart sity-frontend
```

### Servicios

```bash
./scripts/status_services.sh
./scripts/install_systemd_services.sh
```

### Sity test service

```bash
curl http://localhost:8099
```

### SQLite

```bash
sqlite3 data/app.db
```

Expirar acciones pendientes:

```bash
sqlite3 data/app.db "update pendingaction set status='expired' where status='pending';"
```

### Chat API

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"qué servicios puedes controlar?"}' | python3 -m json.tool
```

### CORS / preflight

```bash
curl -i -X OPTIONS http://localhost:8000/chat/message \
  -H "Origin: http://192.168.1.133:5173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```

### Cámara

```bash
fswebcam -d /dev/video0 -r 1280x720 --no-banner --skip 20 captures/camera/test.jpg
```

### Micrófono real de webcam

```bash
arecord -D plughw:CARD=webcam,DEV=0 -d 5 -f cd captures/audio/test-webcam.wav
```

### Audio HDMI workaround

```bash
systemctl --user status hdmi-audio-forward.service
systemctl --user restart hdmi-audio-forward.service
```

### Capturas

```bash
find captures/camera captures/audio -type f | wc -l
du -sh captures
./scripts/clean_captures.sh 7
```

---

## Roadmap

### Core pendiente

- Mejorar manejo de múltiples acciones pendientes.
- Añadir vista/listado de pending actions desde chat.
- Permitir cancelar acciones pendientes desde chat.
- Deduplicar también acciones Git.
- Mejorar mensajes de confirmación para usar nombres humanos en vez de nombres systemd.
- Añadir tests automatizados para confirmation manager.
- Añadir migraciones de base de datos si el esquema crece.
- Mejorar compactación de historial largo.
- Evitar que `/chat/current` devuelva mensajes antiguos cuando debería devolver los últimos.
- Añadir búsqueda de memoria/historial.
- Añadir tool `search_chat_history`.

### Respuesta adaptativa

Pendiente:

- Añadir parámetro interno `contextual_brevity_level`.
- Responder de forma breve cuando la pregunta sea de sí/no o verificación simple.
- Resumir salidas largas de tools salvo que el usuario pida detalle.
- Mantener el tono según personalidad actual.
- Evitar que tools locales vuelquen resultados técnicos completos cuando basta una respuesta natural.

### Conciencia temporal conversacional

Pendiente:

- Hacer que Sity sea consciente del tiempo transcurrido entre mensajes.
- Inyectar en el prompt:
  - hora actual
  - fecha actual
  - tiempo desde el último mensaje
  - tiempo desde la última interacción importante
  - si han pasado minutos, horas o días
- Permitir que reaccione al paso del tiempo según contexto y personalidad.
- Ejemplos:
  - si han pasado 5 minutos: “¿seguimos?”
  - si han pasado horas: “has vuelto”
  - si han pasado días: “bueno, mira quién se acuerda de mí”
  - si el contexto es técnico, no dramatizar y continuar.
- Modular la reacción con parámetros:
  - warmth_level
  - sarcasm_level
  - melancholy_level
  - patience_level
  - initiative_level
  - verbosity_level
- No forzar siempre una reacción temporal.
- Evitar comentarios repetitivos sobre el tiempo si no aportan nada.
- Usar el tiempo para mejorar memoria y contexto:
  - “ayer estuvimos con audio”
  - “hace un rato estabas probando la cámara”
  - “han pasado dos días desde el último cambio”

### Identidad y autodescripción de Sity

Pendiente:

- Configurar que Sity hable de sí misma en femenino.
- Evitar frases como “yo mismo” y preferir “yo misma”.
- Inyectar en prompt:
  “Sity se refiere a sí misma en femenino.”
- Aplicarlo también a micro-reacciones.
- Mantenerlo separado del género/identidad del usuario.

### Perfil de usuario y límites de tono

Pendiente:

- Añadir perfil local del usuario.
- Guardar datos básicos explícitos:
  - edad: 26
  - adulto: true
  - preferencias de tono
- Permitir que Sity use humor más ácido, negro, palabrotas o expresiones más adultas si encaja.
- No forzar ese tono en cada respuesta.
- Modularlo con parámetros existentes:
  - sarcasm_level
  - rudeness_level
  - dry_humor_level
  - warmth_level
  - patience_level
  - verbosity_level
- Añadir nuevos parámetros si hace falta:
  - profanity_level
  - dark_humor_level
  - spicy_comment_level
- Mantener límites:
  - no convertir todo en chiste negro
  - no ser desagradable si el contexto es serio
  - no sexualizar respuestas técnicas normales
  - adaptar tono al estado emocional del usuario
- Inyectar al prompt algo tipo:
  “El usuario es adulto y permite lenguaje más ácido/adulto, pero úsalo solo cuando sea natural y según personalidad.”

### System Access

- Añadir gestión de allowlist de rutas.
- Añadir lectura segura de archivos permitidos.
- Añadir escritura segura de archivos permitidos.
- Añadir edición tipo patch/diff.
- Añadir logs de servicios systemd.
- Añadir health checks por servicio.
- Añadir plantillas para crear nuevos servicios systemd desde planes confirmados.
- Añadir acciones críticas planificadas para instalar/configurar servicios.
- Integrar servicios pesados como Minecraft solo bajo confirmación.
- Permitir añadir/quitar servicios conforme el usuario los cree o elimine.

### System Agent / Claude Code parity

Objetivo futuro:

Dar a Sity un nivel de acceso parecido al de Claude Code sobre la Raspberry, pero con más trazabilidad, confirmaciones y políticas de seguridad.

Claude Code corre como el usuario que lo invoca. Puede hacer todo lo que puede hacer `alex`:

- Leer/escribir ficheros accesibles por `alex`.
- Ejecutar comandos shell.
- Usar Git sin restricciones del propio programa.
- Crear/matar procesos.
- Acceder a hardware si `alex` pertenece a los grupos correctos.
- Usar red.
- Usar `sudo` si está configurado para comandos concretos.

Sity no debe empezar con una shell libre. En su lugar, se ampliará por capas:

#### Fase 1: Filesystem ampliado

- Ampliar `allowed_paths` en `config/system_access.yaml`.
- Añadir lectura segura de archivos permitidos.
- Añadir escritura segura de archivos permitidos.
- Añadir edición tipo patch/diff.
- Evitar rutas fuera de allowlist.
- Bloquear rutas sensibles salvo confirmación fuerte:
  - `.ssh`
  - `.env`
  - credenciales
  - tokens
  - claves privadas
  - `/etc`
  - `/boot`
  - configs de audio críticas

#### Fase 2: Comandos permitidos por alias

- Añadir `run_allowed_command`.
- No aceptar shell libre.
- Definir comandos por alias en YAML.
- Ejemplo:
  - `restart_backend`
  - `status_services`
  - `install_dependencies`
  - `run_tests`
  - `npm_build`
  - `git_status`
- Cada alias define:
  - comando real
  - working directory
  - timeout
  - riesgo
  - si requiere confirmación
  - si permite argumentos
  - patrón de argumentos permitidos

#### Fase 3: Plan + confirmación para acciones críticas

- Para acciones críticas, Sity debe generar un plan.
- El usuario confirma el plan antes de ejecutar.
- Ejemplos críticos:
  - instalar paquetes
  - editar `/etc`
  - tocar systemd
  - modificar sudoers
  - cambiar audio routing
  - borrar archivos
  - hacer push
  - matar procesos
  - abrir puertos
  - modificar red

#### Fase 4: Shell avanzada controlada

- Evaluar una tool `run_shell_command` solo como modo avanzado.
- Debe estar desactivada por defecto.
- Debe requerir confirmación explícita por comando.
- Debe mostrar:
  - comando exacto
  - cwd
  - usuario
  - timeout
  - efectos esperados
- Debe bloquear patrones peligrosos salvo override manual:
  - `rm -rf /`
  - `curl | bash`
  - escritura en `.ssh`
  - dump de secretos
  - chmod/chown recursivo amplio
  - redirecciones destructivas
- Debe registrar todo en audit log.

#### Fase 5: Modo mantenimiento

- Permitir a Sity actuar como agente local de mantenimiento.
- Revisar logs.
- Diagnosticar servicios.
- Proponer fixes.
- Aplicar patches con confirmación.
- Ejecutar tests.
- Reiniciar servicios.
- Hacer commit/push si se confirma.

Principio:

```text
Sity puede tener mucho acceso, pero no debe tener impulsividad.
Debe poder mirar y proponer casi todo.
Debe ejecutar solo bajo política clara.
```

### Git

- Prevalidación más inteligente antes de pull/push/commit.
- Proponer stash/commit si el working tree está sucio.
- Crear PRs en GitHub.
- Leer issues y pull requests.
- Integración con GitHub CLI o API.
- Gestión segura de ramas remotas.
- Deduplicar acciones Git pendientes igual que system actions.

### Sentidos / Hardware

Pendiente:

- Detectar orientación de RasPad 3.
- Leer sensores disponibles.
- Detectar estado de pantalla.
- Explorar integración con sensor de movimiento/orientación.
- Describir imágenes capturadas usando modelo con visión.
- Transcribir audio grabado.
- Añadir wake word o modo escucha.
- Añadir indicador visual cuando se use cámara o micro.
- Mejorar selección automática de cámara/micro.
- Ignorar dispositivos virtuales en selección automática.

### Audio routing

Pendiente:

- Detectar dispositivos virtuales como `Loopback`.
- No usar `Loopback` como micrófono por defecto.
- Exponer estado del pipeline HDMI audio forward.
- Tool local para comprobar si `hdmi-audio-forward.service` está activo.
- Evitar que futuras tools de audio rompan:
  - `/etc/asound.conf`
  - WirePlumber
  - `snd-aloop`
  - `pcm2iec958.py`
  - configuración VLC/Vivaldi

### Domótica / Smart Home

Pendiente:

- Integración con Tapo.
- Integración con SmartLife / Tuya.
- Detectar luces, enchufes y otros dispositivos inteligentes.
- Consultar estado de dispositivos:
  - encendido/apagado
  - consumo si el enchufe lo soporta
  - brillo/color si la bombilla lo soporta
- Acciones bajo petición:
  - encender luces
  - apagar luces
  - cambiar brillo
  - cambiar color
  - encender/apagar enchufes
- Agrupar dispositivos por habitación o alias:
  - “luz del escritorio”
  - “enchufe del servidor”
  - “luces del salón”
- Crear allowlist de dispositivos controlables.
- Pedir confirmación para acciones sensibles:
  - apagar dispositivos críticos
  - cambiar enchufes que alimenten servidores
  - ejecutar escenas que afecten varios dispositivos
- Registrar acciones en audit logs.
- Evitar guardar credenciales de Tapo/Tuya/SmartLife en Git.
- Explorar API local primero si existe; usar cloud solo si es necesario.

### Interacción local con escritorio/pantalla/audio

Pendiente:

- Consultar hora local y zona horaria desde el sistema.
- Sacar capturas de pantalla bajo petición.
- Mostrar imágenes en pantalla.
- Reproducir archivos de audio.
- Reproducir sonidos cortos o avisos.
- Mostrar mensajes visuales en pantalla.
- Abrir/cerrar aplicaciones permitidas.
- Controlar brillo de pantalla si el hardware lo permite.
- Detectar si la pantalla está encendida.
- Apagar/encender pantalla si el sistema lo permite.
- Integrar con orientación de RasPad 3.
- Mantener allowlist de acciones gráficas permitidas.
- Pedir confirmación para acciones invasivas:
  - capturar pantalla
  - mostrar contenido en pantalla
  - reproducir audio alto
  - cerrar aplicaciones
- Evitar modificar configuración gráfica/audio crítica sin plan y confirmación.

### Conectividad local

Pendiente:

- Integración con Bluetooth de la Raspberry.
- Escaneo de dispositivos Bluetooth cercanos.
- Emparejamiento controlado de dispositivos.
- Transferencia de archivos por Bluetooth con confirmación.
- Integración con WiFi.
- Lectura de redes WiFi visibles.
- Diagnóstico de conectividad local.
- Gestión segura de conexiones conocidas.
- Compartición o recepción de archivos en red local.
- Detección de dispositivos de la LAN.
- Acciones de red siempre bajo allowlist y confirmación.

### Presencia local / proximidad

Pendiente:

- Detectar si el usuario está cerca de la Raspberry.
- Explorar varias señales posibles:
  - conexión Bluetooth del teléfono
  - presencia del teléfono en la red WiFi/LAN
  - ping/ARP/mDNS del dispositivo
  - conexión a un servicio local
  - integración futura con ubicación del móvil si existe app/agente propio
- Permitir eventos tipo:
  - “usuario llegó a casa”
  - “usuario salió de casa”
  - “teléfono conectado”
  - “teléfono desconectado”
- Usar estos eventos para automatizaciones locales:
  - encender pantalla
  - saludar
  - cambiar modo de Sity
  - preparar música
  - mostrar estado del sistema
- Requerir consentimiento explícito antes de activar tracking de presencia.
- Guardar solo eventos mínimos y evitar historial invasivo.
- Permitir desactivar/borrar historial de presencia.
- No usar Bluetooth/WiFi para rastreo continuo sin confirmación clara.

### Internet / Web Access

Pendiente:

- Añadir herramienta de búsqueda web.
- Sity debe preguntar antes de buscar en internet si la acción implica salir del entorno local.
- Separar claramente conocimiento local de información buscada online.
- Mostrar fuentes/enlaces usados para responder.
- Resumir resultados sin inventar.
- Permitir preguntas como:
  - “¿Cuándo sale Forza Horizon 6?”
  - “Busca documentación de X.”
  - “Qué ha pasado hoy con Y.”
- Definir política de permisos:
  - búsqueda puntual con confirmación
  - dominios permitidos/opcionales
  - bloqueo de webs sensibles si hace falta
- Cachear búsquedas recientes para ahorrar llamadas.

### Google Integration

Pendiente:

- OAuth local.
- Google Drive read-only.
- Gmail read-only.
- Google Calendar read-only.
- Confirmación para acciones sensibles:
  - enviar email
  - borrar email
  - mover archivos
  - crear/modificar eventos
- Separar scopes por capacidad.
- Guardar tokens fuera de Git.
- Revocación/rotación de credenciales.
- Mostrar claramente cuándo Sity está consultando Google.

### Música / Spotify

Pendiente:

- Integración con Spotify.
- Explorar dos rutas:
  - Spotify Web en Vivaldi.
  - Raspotify como Spotify Connect en Raspberry.
- Permitir acciones como:
  - “pon música”
  - “pon mi playlist X”
  - “pausa”
  - “siguiente canción”
  - “qué está sonando”
- Leer gustos/playlists si se usa API de Spotify.
- Pedir permiso antes de enlazar cuentas o controlar reproducción.
- No romper el pipeline custom de audio HDMI.

### IA / Modelos

Pendiente:

- Fallback a futuros modelos.
- Mejor routing entre modelo barato/caro.
- Compresión de contexto.
- Resumen automático de memoria.
- Control más fino del coste de tokens.
- Modo offline/local en el futuro si hay modelo viable.
- Separar mejor planner, conversación y ejecución.
- Evitar llamadas a IA en casos claramente locales.
- Micro-reactions para más eventos visibles sin pasar por flujo completo.

### Frontend

Pendiente:

- Vista de acciones pendientes.
- Botones de confirmar/cancelar acción.
- Panel de servicios permitidos.
- Panel de estado de sistema.
- Panel de logs/debug.
- Mejor visualización de tokens.
- Mejor edición de personalidad.
- Mejor UX móvil/RasPad.
- Scroll automático robusto al último mensaje.
- Mostrar errores de red/API de forma clara.
- Mostrar si una respuesta vino de Claude o de tool local.
- Mejor UX de eventos en curso.
- Historial con artifacts persistidos en `/chat/current`.

---

## Filosofía del proyecto

Sity debe ser útil, local, extensible y con personalidad propia, pero sin perder control.

No debe convertirse en una shell con cara amable ni en una IA que ejecuta cosas sin explicar.

La regla base:

```text
Puede mirar.
Puede proponer.
Puede actuar según política.
```

Para acciones críticas:

```text
Primero plan.
Luego confirmación.
Después ejecución.
```

Para capacidades externas:

```text
Primero permiso.
Luego consulta.
Después respuesta con trazabilidad.
```

Para sensores:

```text
Uso puntual bajo petición explícita.
Nada de vigilancia continua sin política específica.
Nada de micrófono/cámara ocultos.
```
